"""Hardware-free checks of the packet viewer and processing trace."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import zlib

import numpy as np

from packet_viewer import PacketViewer, packet_line
from processing_demo import ProcessingDemo, ResultTrace
from process_telemetry import BODY, CRC, InferenceWindow, PacketError
from main import InferenceWorker


def payload(sequence=0, *, checked=True, flags=0x81, ax=4096):
    body = BODY.pack(sequence, sequence * 10, ax, -4096, 2048,
                     16384, -16384, 0, 5, flags)
    return body + CRC.pack(zlib.crc32(body)) if checked else body


def message(data=None, topic="esp32/board1/telemetry", retain=False):
    return SimpleNamespace(topic=topic, retain=retain,
                           payload=payload() if data is None else data)


class PacketViewerTests(unittest.TestCase):
    def test_all_wire_fields_and_crc_are_printed(self):
        line = packet_line("board1", payload(7))
        for field in ("[board1]", "sample_index=7", "timestamp_ms=70",
                      "accel_x=4096", "accel_y=-4096", "accel_z=2048",
                      "gyro_x=16384", "gyro_y=-16384", "gyro_z=0",
                      "touch_mask=0x0005", "flags=0x81",
                      f"crc32=0x{zlib.crc32(payload(7)[:-4]):08x} (valid)"):
            self.assertIn(field, line)

    def test_legacy_and_crc_rejection(self):
        self.assertIn("crc32=absent (legacy)", packet_line("board1", payload(checked=False)))
        for data, strict in ((payload(checked=False), True),
                             (payload()[:-1] + bytes([payload()[-1] ^ 1]), False),
                             (b"bad length", False)):
            with self.subTest(data=data, strict=strict), self.assertRaises(PacketError):
                packet_line("board1", data, strict)

    def test_only_live_selected_telemetry_and_no_publishes(self):
        output, client = Mock(), Mock()
        viewer = PacketViewer("board1", output=output)
        for msg in (message(retain=True), message(topic="esp32/board2/telemetry"),
                    message(topic="esp32/board1/status"), message(topic="esp32/+/telemetry"),
                    message(b"bad")):
            viewer.on_message(client, None, msg)
        output.assert_not_called()
        viewer.on_message(client, None, message())
        viewer.on_message(client, None, message())
        self.assertEqual(output.call_count, 2)
        client.publish.assert_not_called()


class ProcessingTests(unittest.TestCase):
    def setUp(self):
        self.output = Mock()
        self.trace = ResultTrace(output=self.output)
        self.client = Mock()
        self.client.publish.return_value.rc = 0
        self.worker = InferenceWorker()
        self.demo = ProcessingDemo(self.client, self.worker, self.trace, model_id="board1")

    def test_rejects_retained_other_device_and_corrupt_packets_before_processing(self):
        for msg in (message(retain=True), message(topic="esp32/other/telemetry"),
                    message(b"bad"), message(payload()[:-1] + b"\0")):
            self.demo.on_message(self.client, None, msg)
        self.assertFalse(self.demo.processors)
        self.client.publish.assert_not_called()

    def test_ack_only_for_crc_verified_probes(self):
        self.demo.on_message(self.client, None, message())
        self.client.publish.assert_called_once_with(
            "esp32/board1/telemetry_ack", payload()[:8] + payload()[-4:], qos=0, retain=False)
        self.client.reset_mock()
        self.demo.on_message(self.client, None, message(payload(1, flags=1)))
        self.demo.on_message(self.client, None, message(payload(2, checked=False)))
        self.client.publish.assert_not_called()
        strict = ProcessingDemo(self.client, self.worker, self.trace, require_crc=True)
        strict.on_message(self.client, None, message(payload(3, checked=False)))
        self.assertFalse(strict.processors)

    def test_marker_requires_fresh_published_match_and_tracks_each_board(self):
        trace = ResultTrace(expected="THROW", output=self.output)
        features = np.zeros((256, 8))
        result = dict(model_id="board1", action="THROW", confidence=0.9,
                      inference_source="fixture", skipped_windows=0, timestamp_ms=10000,
                      status="PUBLISHED", published_action="CATCH_THROW",
                      timing_ms=dict(receive_to_result=300, queue=100, inference=100))
        trace.mark(now=10.0)
        trace.result(result, InferenceWindow(features, 255, None, 9.0, 9.1), 10.2)
        self.assertFalse(trace.marked_devices)
        window = InferenceWindow(features, 280, 2800, 10.1, 10.2)
        for status in ("LOW_CONFIDENCE", "SUPPRESSED", "PUBLISH_FAILED"):
            result['status'] = status
            trace.result(result, window, 10.4)
            self.assertFalse(trace.marked_devices)
        result.update(status="PUBLISHED", action="AIM")
        trace.result(result, window, 10.4)
        self.assertFalse(trace.marked_devices)
        result['action'] = 'THROW'
        trace.result(result, window, 10.4)
        line = self.output.call_args_list[-2].args[0]
        self.assertIn("mark_to_result_ms=400.00", line)
        self.assertIn("inference_ms=100.00", line)
        self.assertEqual(trace.marked_devices, {"board1"})
        trace.result(result, window, 10.5)
        self.assertNotIn("mark_to_result_ms", self.output.call_args_list[-2].args[0])
        result['model_id'] = 'board2'
        trace.result(result, window, 10.5)
        self.assertEqual(trace.marked_devices, {"board1", "board2"})
        trace.mark(now=11)
        self.assertFalse(trace.marked_devices)


if __name__ == "__main__":
    unittest.main()
