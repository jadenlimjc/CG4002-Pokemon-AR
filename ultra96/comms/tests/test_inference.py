"""Exercise the direct FPGA API boundary and two-board scheduling."""

import importlib.util
import asyncio
import json
from pathlib import Path
import sys
import tempfile
from threading import Event, Thread, get_ident
import time
from types import SimpleNamespace
import unittest
import zlib
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from main import Action, InferenceWorker, TelemetryProcessor, TelemetryService, create_accelerator
from process_telemetry import (BODY, CRC,
                               InferenceWindow, TelemetryBuffer, model_input)
from processing_demo import ProbeProcessor, ResultTrace
from test_integration_tools import message, payload


class FakeAccelerator:
    def __init__(self, label=4):
        self.label = label
        self.closed = False

    def predict_logits_timed(self, inputs):
        logits = np.zeros(11, dtype=np.float32)
        logits[self.label] = 10
        return logits, SimpleNamespace(as_dict=lambda: {"total_s": 0.001, "input_preparation_s": 0.0001,
                                                          "dma_s": 0.0008, "accelerator_s": 0.0007, "output_copy_s": 0.0001})

    def close(self):
        self.closed = True


def live_window():
    features = np.zeros((256, 8), dtype=np.float32)
    features[:, :6] = [1, -1, 0.5, 250, -250, 0]
    features.setflags(write=False)
    now = time.monotonic()
    return InferenceWindow(features, 255, 2550, now, now)


class ModelTests(unittest.TestCase):
    def test_normalization_shape_touch_exclusion_and_immutable_input(self):
        window = live_window()
        inputs = model_input(window.features)
        self.assertEqual(inputs.shape, (6, 256))
        self.assertEqual(inputs.dtype, np.float32)
        self.assertTrue(inputs.flags.c_contiguous)
        np.testing.assert_allclose(inputs[:, 0], [0.125, -0.125, 0.0625, 0.5, -0.5, 0])
        np.testing.assert_array_equal(window.features[0, :6], [1, -1, 0.5, 250, -250, 0])
        changed_touch = window.features.copy()
        changed_touch[:, 6:] = [65535, 1]
        np.testing.assert_array_equal(model_input(changed_touch), inputs)
        for invalid in (np.zeros((6, 256)), np.full((256, 8), np.nan)):
            with self.assertRaises(ValueError):
                model_input(invalid)

    def test_wire_to_model_matches_training_csv_preprocessing(self):
        training = Path(__file__).resolve().parents[2] / 'real_data' / 'preprocess_real_gestures.py'
        spec = importlib.util.spec_from_file_location('training_preprocessing', training)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        buffer = TelemetryBuffer()
        for index in range(256):
            buffer.add_packet(payload(index, flags=1))
        window = buffer.output_queue.get_nowait()
        # Independent MotionSensor/Adafruit SI reference for the wire fixture.
        # Use SI readings directly, independently of the receiver conversion.
        physical = np.tile([
            9.80665, -9.80665, 0.5 * 9.80665,
            0.125, -0.25, 0.5,
        ], (256, 1)).astype(np.float32)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'gesture.csv'
            np.savetxt(path, physical, delimiter=',', header='ax,ay,az,gx,gy,gz', comments='')
            expected = module.load_csv(path).T
        np.testing.assert_allclose(model_input(window.features), expected, rtol=1e-6)
        self.assertEqual(len(Action), 11)
        self.assertEqual(list(Action)[10].value, 'UPPERCUT')

    def test_worker_factory_constructs_existing_driver_directly(self):
        driver = SimpleNamespace(GestureCNNAccelerator=Mock())
        with patch.dict(sys.modules, {'ultra96.fpga.deployment.cnn_pynq_ultra96': driver}):
            self.assertIs(create_accelerator(), driver.GestureCNNAccelerator.return_value)
        driver.GestureCNNAccelerator.assert_called_once_with()


class BufferTests(unittest.TestCase):
    @staticmethod
    def packet(sequence, timestamp, ax=9.80665, flags=0):
        body = BODY.pack(sequence, timestamp, ax, 0, 0, 0, 0, 0, 0, flags)
        return body + CRC.pack(zlib.crc32(body))

    def test_small_sequence_gap_holds_previous_float32_sample(self):
        buffer = TelemetryBuffer(window_size=4, hop_size=1)
        buffer.add_packet(self.packet(0, 1000))
        buffer.add_packet(self.packet(3, 1030, ax=19.6133))
        window = buffer.output_queue.get_nowait()
        np.testing.assert_allclose(window.features[:, 0], [1, 1, 1, 2])
        self.assertEqual(window.last_sequence, 3)
        self.assertEqual(buffer.sequence_stats.gap_slots, 2)

    def test_timestamp_gaps_and_flags_do_not_reconstruct_samples(self):
        buffer = TelemetryBuffer(window_size=4, hop_size=1)
        buffer.add_packet(self.packet(0, 10, flags=0x06))
        buffer.add_packet(self.packet(1, 3600010, ax=19.6133, flags=0x02))
        self.assertEqual(len(buffer.buffer), 2)
        np.testing.assert_allclose(np.array(buffer.buffer)[:, 0], [1, 2])
        self.assertTrue(buffer.output_queue.empty())

    def test_large_sequence_gap_resets_buffer(self):
        buffer = TelemetryBuffer(window_size=4, hop_size=1)
        buffer.add_packet(self.packet(0, 100))
        buffer.add_packet(self.packet(10, 200, ax=19.6133))
        self.assertEqual(len(buffer.buffer), 1)
        self.assertAlmostEqual(buffer.buffer[0][0], 2, places=6)
        self.assertTrue(buffer.output_queue.empty())

    def test_sequence_wrap_and_duplicates(self):
        buffer = TelemetryBuffer(window_size=2, hop_size=1)
        buffer.add_packet(self.packet(0xffffffff, 0xfffffff0))
        final = self.packet(0, 14, ax=19.6133)
        buffer.add_packet(final)
        buffer.add_packet(final)
        window = buffer.output_queue.get_nowait()
        np.testing.assert_allclose(window.features[:, 0], [1, 2])
        self.assertTrue(buffer.output_queue.empty())
        self.assertEqual(buffer.sequence_stats.duplicates, 1)


class GameplayTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.publish.return_value.rc = 0
        self.accelerator = FakeAccelerator()
        self.worker = SimpleNamespace(accelerator=self.accelerator, confidence_threshold=0.75)
        self.processor = TelemetryProcessor(self.client, 'A', self.worker)

    def test_real_predictions_preserve_gameplay_contract_and_per_board_state(self):
        results = []
        for label in (1, 3, 4, 0, 4, 4):  # Aim, throw, blocked punch, reset, punch, repeat.
            self.accelerator.label = label
            for _ in range(3):
                result = self.processor.run_inference(live_window())
            results.append(result)
        self.assertEqual([r['status'] for r in results],
                         ['PUBLISHED', 'PUBLISHED', 'SUPPRESSED', 'PUBLISHED', 'PUBLISHED', 'SUPPRESSED'])
        events = [json.loads(call.args[1]) for call in self.client.publish.call_args_list]
        self.assertEqual([event['action'] for event in events],
                         ['ARM_PULLBACK', 'CATCH_THROW', 'CANCEL', 'BATTLE_MOVE'])
        self.assertEqual(events[-1]['gesture_id'], 1)
        self.assertEqual(events[-1]['predicted_action'], 'PUNCH')
        self.assertEqual(events[-1]['timestamp'], events[-1]['timestamp_ms'])
        self.assertEqual(events[-1]['inference_source'], 'fpga')
        self.assertEqual(events[-1]['timing_ms']['total'], 1.0)
        self.assertEqual(events[-1]['model_input_shape'], [6, 256])
        self.assertGreaterEqual(events[-1]['timing_ms']['queue'], 0)
        self.assertGreaterEqual(events[-1]['timing_ms']['receive_to_result'],
                                events[-1]['timing_ms']['inference'])
        other = TelemetryProcessor(self.client, 'B', self.worker)
        for _ in range(2):
            self.assertEqual(other.run_inference(live_window())['status'], 'CONFIRMING')
        self.assertEqual(other.run_inference(live_window())['status'], 'PUBLISHED')
        self.assertEqual(self.client.publish.call_args.args[0], 'ultra96/B/inference')

    def test_low_confidence_does_not_change_sequence_or_publish(self):
        self.accelerator.label = 1
        for _ in range(3):
            self.processor.run_inference(live_window())
        self.client.reset_mock()
        self.accelerator.predict_logits_timed = lambda _: (np.zeros(11), SimpleNamespace(as_dict=lambda: {}))
        result = self.processor.run_inference(live_window())
        self.assertEqual(result['status'], 'LOW_CONFIDENCE')
        self.assertTrue(self.processor.gesture_sequence.aiming)
        self.client.publish.assert_not_called()

    def test_transient_wrong_label_is_not_published(self):
        results = []
        for label in (5, 4, 4, 4, 4):  # Brief swipe B, then sustained punch A.
            self.accelerator.label = label
            results.append(self.processor.run_inference(live_window()))
        self.assertEqual([r['status'] for r in results],
                         ['CONFIRMING', 'CONFIRMING', 'CONFIRMING', 'PUBLISHED', 'SUPPRESSED'])
        self.assertEqual([r['confirmation_count'] for r in results], [1, 1, 2, 3, 3])
        self.client.publish.assert_called_once()
        event = json.loads(self.client.publish.call_args.args[1])
        self.assertEqual(event['predicted_action'], 'PUNCH')

    def test_low_confidence_restarts_confirmation(self):
        for _ in range(2):
            self.processor.run_inference(live_window())
        original = self.accelerator.predict_logits_timed
        self.accelerator.predict_logits_timed = lambda _: (np.zeros(11), SimpleNamespace(as_dict=lambda: {}))
        result = self.processor.run_inference(live_window())
        self.assertEqual(result['confirmation_count'], 0)
        self.accelerator.predict_logits_timed = original
        for _ in range(2):
            self.assertEqual(self.processor.run_inference(live_window())['status'], 'CONFIRMING')
        self.client.publish.assert_not_called()
        self.assertEqual(self.processor.run_inference(live_window())['status'], 'PUBLISHED')

    def test_unconfirmed_neutral_does_not_rearm_gesture(self):
        for _ in range(3):
            self.processor.run_inference(live_window())
        self.accelerator.label = 0
        self.assertEqual(self.processor.run_inference(live_window())['status'], 'CONFIRMING')
        self.assertEqual(self.processor.gesture_sequence.last_action, 'PUNCH')
        self.accelerator.label = 4
        for _ in range(3):
            result = self.processor.run_inference(live_window())
        self.assertEqual(result['status'], 'SUPPRESSED')
        self.client.publish.assert_called_once()

    def test_softmax_stability_and_invalid_fpga_outputs(self):
        self.accelerator.predict_logits_timed = lambda _: (
            np.array([0] * 10 + [10000]), SimpleNamespace(as_dict=lambda: {}))
        result = self.processor.run_inference(live_window())
        self.assertEqual(result['action'], 'UPPERCUT')
        self.assertEqual(result['confidence'], 1.0)
        for invalid in (np.zeros(10), np.zeros((1, 11)), np.full(11, np.nan), np.full(11, np.inf)):
            self.accelerator.predict_logits_timed = lambda _, values=invalid: (
                values, SimpleNamespace(as_dict=lambda: {}))
            with self.assertRaises(ValueError):
                self.processor.run_inference(live_window())

    def test_publish_failure_is_not_reported_as_published(self):
        self.client.publish.return_value.rc = 4
        for _ in range(3):
            result = self.processor.run_inference(live_window())
        self.assertEqual(result['status'], 'PUBLISH_FAILED')


class SchedulingTests(unittest.TestCase):
    def test_worker_has_event_loop_until_accelerator_cleanup(self):
        loops = []

        class Accelerator(FakeAccelerator):
            def __init__(self):
                super().__init__()
                loops.append(asyncio.get_event_loop())

            def close(self):
                loops.append(asyncio.get_event_loop())
                self_loop = loops[-1]
                if self_loop.is_closed():
                    raise RuntimeError('event loop closed before accelerator')
                super().close()

        worker = InferenceWorker(Accelerator)
        try:
            worker.start()
        finally:
            worker.close()
        worker.raise_if_failed()
        self.assertEqual(len(loops), 2)
        self.assertIs(loops[0], loops[1])
        self.assertTrue(loops[0].is_closed())

    def test_two_boards_keep_receiving_and_get_fair_latest_windows(self):
        entered, release, done = Event(), Event(), Event()
        calls, completed, lifecycle = [], [], []
        trace = ResultTrace(output=Mock())
        trace.mark()

        class Accelerator(FakeAccelerator):
            def __init__(self):
                super().__init__()
                lifecycle.append(('open', get_ident()))

            def predict_logits_timed(self, inputs):
                calls.append((get_ident(), inputs.copy()))
                if len(calls) == 1:
                    entered.set()
                    if not release.wait(3):
                        raise RuntimeError('test gate timed out')
                return super().predict_logits_timed(inputs)

            def close(self):
                lifecycle.append(('close', get_ident()))
                super().close()

        class Processor(ProbeProcessor):
            def __init__(self, client, model_id, worker):
                super().__init__(client, model_id, worker, trace, confirmation_steps=1)

            def run_inference(self, window):
                result = super().run_inference(window)
                completed.append((self.model_id, window.last_sequence, result))
                if len(completed) == 3:
                    done.set()

        client = Mock()
        client.publish.return_value.rc = 0
        worker = InferenceWorker(Accelerator)
        service = TelemetryService(client, worker, processor_factory=Processor)

        def send(board, first, last):
            for index in range(first, last):
                service.on_message(client, None, message(
                    payload(index, flags=1, ax=9.80665 if board == 'A' else 19.6133),
                    topic=f'esp32/{board}/telemetry'))

        worker.start()
        try:
            send('A', 0, 256)
            self.assertTrue(entered.wait(2))
            # Inference is held at the gate throughout all these MQTT callbacks.
            send('B', 0, 256)
            send('A', 256, 281)
            send('B', 256, 281)
            send('A', 281, 306)
            with worker.condition:
                self.assertEqual(list(worker.pending), ['B', 'A'])
                self.assertEqual(worker.pending['B'][1].last_sequence, 280)
                self.assertEqual(worker.pending['A'][1].last_sequence, 305)
            self.assertEqual(service.processors['A'].skipped_windows, 1)
            self.assertEqual(service.processors['B'].skipped_windows, 1)
            release.set()
            self.assertTrue(done.wait(3))
            worker.raise_if_failed()
        finally:
            release.set()
            worker.close()
        self.assertEqual([(board, seq) for board, seq, _ in completed],
                         [('A', 255), ('B', 280), ('A', 305)])
        self.assertEqual([inputs[0, -1] for _, inputs in calls], [0.125, 0.25, 0.125])
        owner = calls[0][0]
        self.assertNotEqual(owner, get_ident())
        self.assertTrue(all(thread == owner for thread, _ in calls))
        self.assertEqual(lifecycle, [('open', owner), ('close', owner)])
        self.assertEqual(client.publish.call_count, 2)  # Independent per-board sequence state.
        self.assertEqual(trace.marked_devices, {'A', 'B'})
        lines = [call.args[0] for call in trace.output.call_args_list]
        self.assertEqual(sum(line.startswith('RESULT ') for line in lines), 3)
        self.assertEqual(sum(line.startswith('  FPGA ms:') for line in lines), 3)

    def test_startup_failure_is_reported_to_caller(self):
        worker = InferenceWorker(lambda: (_ for _ in ()).throw(FileNotFoundError('missing model')))
        with self.assertRaisesRegex(RuntimeError, 'missing model'):
            worker.start()
        worker.close()
        self.assertTrue(worker.failed.is_set())

    def test_inference_error_stops_worker_and_closes_accelerator(self):
        accelerator = FakeAccelerator()
        accelerator.predict_logits_timed = lambda _: (_ for _ in ()).throw(TimeoutError('DMA timed out'))
        worker = InferenceWorker(lambda: accelerator)
        client = Mock()
        worker.start()
        processor = TelemetryProcessor(client, 'A', worker)
        worker.submit(processor, live_window())
        self.assertTrue(worker.failed.wait(2))
        worker.close()
        self.assertTrue(accelerator.closed)
        client.publish.assert_not_called()
        with self.assertRaisesRegex(RuntimeError, 'DMA timed out'):
            worker.raise_if_failed()

    def test_shutdown_does_not_close_accelerator_during_inference(self):
        entered, release, closed = Event(), Event(), Event()
        accelerator = FakeAccelerator()
        original = accelerator.predict_logits_timed

        def blocked(inputs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError('test gate timed out')
            return original(inputs)

        accelerator.predict_logits_timed = blocked
        worker = InferenceWorker(lambda: accelerator)
        client = Mock()
        client.publish.return_value.rc = 0
        worker.start()
        worker.submit(TelemetryProcessor(client, 'A', worker), live_window())
        self.assertTrue(entered.wait(2))
        closer = Thread(target=lambda: (worker.close(), closed.set()))
        closer.start()
        try:
            deadline = time.monotonic() + 2
            while not worker.stopping and time.monotonic() < deadline:
                time.sleep(0.001)
            self.assertTrue(worker.stopping)
            self.assertFalse(accelerator.closed)
            self.assertFalse(closed.is_set())
        finally:
            release.set()
            closer.join(4)
        self.assertTrue(closed.is_set())
        self.assertTrue(accelerator.closed)


if __name__ == '__main__':
    unittest.main()
