"""Hardware-free checks of the packet viewer and processing trace."""

from types import SimpleNamespace
import json
import struct
import unittest
from unittest.mock import Mock
import zlib

import numpy as np

from packet_viewer import PacketViewer, packet_line
from final_demo import GestureDashboard, GestureMonitor, decode_touch_debug
from processing_demo import ProcessingDemo, ResultTrace
from process_telemetry import BODY, CRC, InferenceWindow, PacketError, decode_packet
from main import InferenceWorker, TelemetryService


def payload(sequence=0, *, checked=True, flags=0x81, ax=9.80665):
    body = BODY.pack(sequence, sequence * 10, ax, -9.80665, 4.903325,
                     0.125, -0.25, 0.5, flags)
    return body + CRC.pack(zlib.crc32(body)) if checked else body


def message(data=None, topic="esp32/board1/telemetry", retain=False):
    return SimpleNamespace(topic=topic, retain=retain,
                           payload=payload() if data is None else data)


class PacketViewerTests(unittest.TestCase):
    def test_esp32_float32_layout_and_crc(self):
        # Independent wire fixture: do not derive its format from BODY.
        values = (1.25, -2.5, 9.80665, 0.125, -0.25, 0.5)
        body = struct.pack("<II6fB", 0xffffffff, 1234, *values, 0x85)
        data = body + struct.pack("<I", zlib.crc32(body))
        self.assertEqual(len(data), 37)
        packet = decode_packet(data, require_crc=True)
        self.assertEqual((packet.sequence, packet.timestamp_ms), (0xffffffff, 1234))
        np.testing.assert_allclose(packet.features[:6], values, rtol=1e-7)
        self.assertEqual(packet.features[6:], (0x85,))
        for offset in (8, 32, 33, 36):
            damaged = bytearray(data)
            damaged[offset] ^= 1
            with self.assertRaisesRegex(PacketError, "bad_crc"):
                decode_packet(damaged, require_crc=True)
        old_body = struct.pack("<II6hHB", 1, 10, 1, 2, 3, 4, 5, 6, 5, 0)
        for old in (old_body, old_body + struct.pack("<I", zlib.crc32(old_body))):
            with self.assertRaisesRegex(PacketError, "bad_length"):
                decode_packet(old)

    def test_all_wire_fields_and_crc_are_printed(self):
        line = packet_line("board1", payload(7))
        for field in ("[board1]", "sample_index=7", "timestamp_ms=70",
                      "accel_x=9.80665", "accel_y=-9.80665", "accel_z=4.903325",
                      "gyro_x=0.125", "gyro_y=-0.25", "gyro_z=0.5",
                      "menu_flags=0x01", "throw_mode=catch", "flags=0x81",
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

    def test_menu_bits_piggyback_on_telemetry_and_relay_by_player_label(self):
        worker = SimpleNamespace(confidence_threshold=0.75, submit=Mock())
        service = TelemetryService(self.client, worker)
        service.on_message(
            self.client, None,
            message(payload(7, flags=0x02),
                    topic="esp32/dce6f6215788/telemetry"))
        topic, body = self.client.publish.call_args.args[:2]
        self.assertEqual(topic, "ultra96/1/menu_controls")
        self.assertEqual(json.loads(body), {"flags": 2, "sequence": 7})
        self.assertEqual(self.client.publish.call_args.kwargs,
                         {"qos": 0, "retain": False})
        service.on_message(
            self.client, None,
            message(payload(7, flags=0x02),
                    topic="esp32/dce6f6215788/telemetry"))
        self.assertEqual(self.client.publish.call_count, 1)

    def test_esp_mode_bit_selects_battle_and_index_remains_menu_select(self):
        worker = SimpleNamespace(confidence_threshold=0.75, submit=Mock())
        service = TelemetryService(self.client, worker)
        index_event = message(
            payload(7, flags=0x09),
            topic="esp32/dce6f6215788/telemetry",
        )

        service.on_message(self.client, None, index_event)
        processor = service.processors['dce6f6215788']
        self.assertEqual(processor.throw_action, 'POKEBALL_THROW')
        topic, body = self.client.publish.call_args.args[:2]
        self.assertEqual(topic, "ultra96/1/menu_controls")
        self.assertEqual(json.loads(body), {"flags": 1, "sequence": 7})

        service.on_message(self.client, None, index_event)
        self.assertEqual(processor.throw_action, 'POKEBALL_THROW')
        self.assertEqual(self.client.publish.call_count, 1)

        service.on_message(
            self.client, None,
            message(payload(8, flags=0x08),
                    topic="esp32/dce6f6215788/telemetry"))
        self.assertEqual(processor.throw_action, 'POKEBALL_THROW')
        self.assertEqual(self.client.publish.call_count, 1)

    def test_u96_mode_guard_is_shorter_than_esp_guard(self):
        worker = SimpleNamespace(confidence_threshold=0.75, submit=Mock())
        processor = TelemetryService(self.client, worker).processor_factory(
            self.client, "dce6f6215788", worker)

        processor.process_packet(payload(1, flags=0x08), received_at=10.0)
        self.assertEqual(processor.throw_action, 'POKEBALL_THROW')
        processor.process_packet(payload(2, flags=0), received_at=10.199)
        self.assertEqual(processor.throw_action, 'POKEBALL_THROW')
        processor.process_packet(payload(3, flags=0), received_at=10.201)
        self.assertEqual(processor.throw_action, 'CATCH_THROW')

    def test_index_is_preserved_when_relaying_combined_menu_controls(self):
        worker = SimpleNamespace(confidence_threshold=0.75, submit=Mock())
        service = TelemetryService(self.client, worker)
        service.on_message(
            self.client, None,
            message(payload(7, flags=0x0b),
                    topic="esp32/dce6f6215788/telemetry"))

        topic, body = self.client.publish.call_args.args[:2]
        self.assertEqual(topic, "ultra96/1/menu_controls")
        self.assertEqual(json.loads(body), {"flags": 3, "sequence": 7})
        self.assertEqual(service.processors['dce6f6215788'].throw_action,
                         'POKEBALL_THROW')

    def test_final_dashboard_manual_actions_update_modes_and_use_inference_topic(self):
        processor = Mock(throw_action="CATCH_THROW")
        processor.model_id = "board1"
        processor.client = self.client
        processor.topics = {
            "ack": "esp32/board1/telemetry_ack",
            "inference": "ultra96/board1/inference",
        }
        processor.inference_snapshot.return_value = {
            "current": None,
            "last_sent": None,
            "state": "NEUTRAL",
            "decision_counts": {},
        }
        monitor = GestureMonitor(processor)

        self.assertEqual(monitor.gameplay_mode, "FULL PLAY")
        initial_lines = monitor.lines(10.0)
        self.assertIn(" MODES: throw CATCH_THROW | gameplay FULL PLAY", initial_lines)
        self.assertTrue(any("[1/t] Tutorial" in line for line in initial_lines))
        self.assertTrue(any("Packet rate:" in line for line in initial_lines))
        self.assertTrue(any("Est. one-way:" in line for line in initial_lines))
        self.assertIn(
            " TOUCH RAW/BASE: -- calibrating; keep fingers off for first second after ESP boot",
            initial_lines,
        )

        touch_event = message(
            json.dumps({"raw": [410, 320, 515], "baseline": [810, 720, 900],
                        "touch_below": [608, 540, 675],
                        "drop_percent": 25, "min_drop": 100}).encode(),
            topic="esp32/board1/touch_debug",
        )
        monitor.on_message(touch_event, 10.1)
        self.assertIn(
            " TOUCH RAW/BASE (touch <=): index 410/810 (<=608) | middle 320/720 "
            "(<=540) | ring 515/900 (<=675) | drop >= max(25%, 100)",
            monitor.lines(10.1),
        )
        processor.process_packet.assert_not_called()
        self.assertTrue(monitor.publish_manual_action("SET_TUTORIAL", "TUTORIAL"))
        topic, body = self.client.publish.call_args.args[:2]
        self.assertEqual(topic, "ultra96/board1/inference")
        self.assertEqual(json.loads(body), {
            "action": "SET_TUTORIAL",
            "gesture_id": 0,
            "confidence": 1.0,
            "timestamp": 0,
        })
        self.assertEqual(self.client.publish.call_args.kwargs,
                         {"qos": 0, "retain": False})
        self.assertEqual(monitor.gameplay_mode, "TUTORIAL")

        self.assertTrue(monitor.publish_manual_action("SKIP_STEP"))
        self.assertEqual(monitor.gameplay_mode, "TUTORIAL")

        self.client.publish.return_value.rc = 4
        self.assertFalse(monitor.publish_manual_action("SET_GOD_MODE", "GOD MODE"))
        self.assertEqual(monitor.gameplay_mode, "TUTORIAL")
        with self.assertRaisesRegex(ValueError, "Unsupported manual action"):
            monitor.publish_manual_action("NOT_A_REAL_ACTION")

    def test_touch_debug_validation_and_dashboard_subscription(self):
        self.assertEqual(
            decode_touch_debug(
                b'{"raw":[410,320,515],"baseline":[810,720,900],'
                b'"touch_below":[608,540,675],"drop_percent":25,"min_drop":100}'
            ),
            {"raw": [410, 320, 515], "baseline": [810, 720, 900],
             "touch_below": [608, 540, 675], "drop_percent": 25, "min_drop": 100},
        )
        for invalid in (b'[]', b'{}',
                        b'{"raw":[true,1,2],"baseline":[1,2,3],"touch_below":[1,2,3],'
                        b'"drop_percent":25,"min_drop":100}',
                        b'{"raw":[1,2,3],"baseline":[1,2,3],"touch_below":[1,2,3],'
                        b'"drop_percent":0,"min_drop":100}', b'not json'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                decode_touch_debug(invalid)

        dashboard = GestureDashboard(self.client, SimpleNamespace(confidence_threshold=0.75))
        dashboard.on_connect(self.client, None, None, 0)
        subscriptions = self.client.subscribe.call_args.args[0]
        self.assertIn(("esp32/+/touch_debug", 0), subscriptions)

    def test_final_dashboard_keys_target_selected_device(self):
        worker = SimpleNamespace(confidence_threshold=0.75)
        dashboard = GestureDashboard(self.client, worker)
        first, second = Mock(), Mock()
        dashboard.monitors = {"A": first, "B": second}

        self.assertTrue(dashboard.handle_key("2"))
        first.publish_manual_action.assert_called_once_with("SET_GOD_MODE", "GOD MODE")
        self.assertTrue(dashboard.handle_key("\t"))
        self.assertTrue(dashboard.handle_key("s"))
        second.publish_manual_action.assert_called_once_with("SKIP_STEP", None)
        self.assertFalse(dashboard.handle_key("q"))

    def test_final_dashboard_forwards_status_and_subscribes_for_pairing(self):
        worker = SimpleNamespace(confidence_threshold=0.75)
        dashboard = GestureDashboard(self.client, worker)

        dashboard.on_connect(self.client, None, None, 0)
        subscriptions = self.client.subscribe.call_args.args[0]
        self.assertIn(("esp32/+/status", 1), subscriptions)
        self.assertIn(("visualiser/+/pair/request", 1), subscriptions)

        self.client.publish.return_value.rc = 0
        dashboard.on_message(self.client, None, message(
            b'{"state":"online","device_id":"dce6f6215788"}',
            topic="esp32/dce6f6215788/status",
            retain=True,
        ))
        topic, body = self.client.publish.call_args.args[:2]
        self.assertEqual(topic, "ultra96/1/status")
        self.assertEqual(json.loads(body), {"device_id": "1", "state": "online"})
        self.assertEqual(self.client.publish.call_args.kwargs, {"qos": 1, "retain": True})

    def test_final_dashboard_still_processes_telemetry(self):
        processor = Mock()
        processor.model_id = "board1"
        processor.client = self.client
        processor.topics = {"ack": "esp32/board1/telemetry_ack"}
        monitor = GestureMonitor(processor)

        monitor.on_message(message(payload(7, flags=0x02)), 10.0)
        processor.process_packet.assert_called()

    def test_final_dashboard_relays_index_to_unity_menu_controls(self):
        processor = Mock()
        processor.model_id = "dce6f6215788"
        processor.client = self.client
        processor.topics = {"ack": "esp32/dce6f6215788/telemetry_ack"}
        monitor = GestureMonitor(processor)

        event = message(
            payload(7, flags=0x01),
            topic="esp32/dce6f6215788/telemetry",
        )
        monitor.on_message(event, 10.0)
        topic, body = self.client.publish.call_args.args[:2]
        self.assertEqual(topic, "ultra96/1/menu_controls")
        self.assertEqual(json.loads(body), {"flags": 1, "sequence": 7})
        self.assertEqual(self.client.publish.call_args.kwargs,
                         {"qos": 0, "retain": False})

        monitor.on_message(event, 10.1)
        self.assertEqual(self.client.publish.call_count, 1)

    def test_marker_requires_fresh_published_match_and_tracks_each_board(self):
        trace = ResultTrace(expected="THROW", output=self.output)
        features = np.zeros((128, 8))
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
