"""Hardware-free checks for exclusive visualiser pairing leases."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from pairing import (
    PairingRegistry, PairingService, player_id_for_model,
    status_is_online, validate_player_id,
)


PLAYER_1_MODEL = "dce6f6215788"
PLAYER_2_MODEL = "cc386a2b1838"


def message(topic, payload, retain=False):
    if isinstance(payload, dict):
        payload = json.dumps(payload).encode()
    return SimpleNamespace(topic=topic, payload=payload, retain=retain)


class PairingRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.path = Path(self.temporary.name) / "leases.json"
        self.now = 1000.0
        self.registry = PairingRegistry(self.path, lease_seconds=300, clock=lambda: self.now)

    def tearDown(self):
        self.temporary.cleanup()

    def test_first_phone_locks_device_and_other_phone_is_rejected(self):
        first = self.registry.acquire("phone-a", "esp-a")
        blocked = self.registry.acquire("phone-b", "esp-a")
        self.assertEqual(first["status"], "ACQUIRED")
        self.assertEqual(blocked["status"], "LOCKED")
        self.assertEqual(blocked["lease_remaining_ms"], 300000)

    def test_same_phone_reclaims_and_atomic_switch_preserves_old_on_failure(self):
        self.registry.acquire("phone-a", "esp-a")
        self.registry.acquire("phone-b", "esp-b")
        self.assertEqual(self.registry.acquire("phone-a", "esp-a")["status"], "RECLAIMED")
        self.assertEqual(self.registry.acquire("phone-a", "esp-b")["status"], "LOCKED")
        self.assertEqual(self.registry.lease_for_device("esp-a").phone_id, "phone-a")
        self.registry.release("phone-b", "esp-b")
        self.assertEqual(self.registry.acquire("phone-a", "esp-b")["status"], "ACQUIRED")
        self.assertIsNone(self.registry.lease_for_device("esp-a"))

    def test_renewal_and_expiry(self):
        self.registry.acquire("phone-a", "esp-a")
        self.now += 250
        renewed = self.registry.renew("phone-a", "esp-a")
        self.assertEqual(renewed["status"], "RENEWED")
        self.now += 299
        self.assertEqual(self.registry.acquire("phone-b", "esp-a")["status"], "LOCKED")
        self.now += 2
        self.assertEqual(self.registry.acquire("phone-b", "esp-a")["status"], "ACQUIRED")

    def test_leases_survive_service_restart(self):
        self.registry.acquire("phone-a", "esp-a")
        restored = PairingRegistry(self.path, lease_seconds=300, clock=lambda: self.now)
        self.assertEqual(restored.acquire("phone-a", "esp-a")["status"], "RECLAIMED")
        self.assertEqual(restored.acquire("phone-b", "esp-a")["status"], "LOCKED")

    def test_release_is_idempotent_and_cannot_release_another_phone(self):
        self.registry.acquire("phone-a", "esp-a")
        self.assertEqual(self.registry.release("phone-b", "esp-a")["status"], "LOCKED")
        self.assertEqual(self.registry.release("phone-a", "esp-a")["status"], "RELEASED")
        self.assertEqual(self.registry.release("phone-a", "esp-a")["status"], "RELEASED")


class PairingServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.now = 1000.0
        self.client = Mock()
        registry = PairingRegistry(Path(self.temporary.name) / "leases.json",
                                   lease_seconds=300, clock=lambda: self.now)
        self.service = PairingService(self.client, registry)

    def tearDown(self):
        self.temporary.cleanup()

    def request(self, phone, action, device="1", request_id="request-1"):
        self.service.handle_message(message(f"visualiser/{phone}/pair/request", {
            "action": action, "device_id": device, "request_id": request_id,
        }))
        return json.loads(self.client.publish.call_args.args[1])

    def test_retained_lwt_status_drives_availability_but_not_unlocking(self):
        self.assertTrue(status_is_online(b'{"state":"online"}'))
        self.service.handle_message(message(
            f"esp32/{PLAYER_1_MODEL}/status", {"state": "online"}, retain=True))
        self.assertEqual(self.request("phone-a", "acquire")["status"], "ACQUIRED")
        self.service.handle_message(message(
            f"esp32/{PLAYER_1_MODEL}/status", {"state": "offline"}, retain=True))
        self.assertFalse(self.service.is_device_online("1"))
        self.assertEqual(self.request("phone-b", "acquire")["status"], "LOCKED")
        self.assertEqual(self.request("phone-a", "renew")["status"], "RENEWED")

    def test_new_offline_device_cannot_be_acquired(self):
        result = self.request("phone-a", "acquire")
        self.assertEqual(result["status"], "OFFLINE")

    def test_request_response_topic_and_qos(self):
        self.service.handle_message(message(
            f"esp32/{PLAYER_1_MODEL}/status", {"state": "online"}))
        result = self.request("phone-a", "acquire")
        self.assertEqual(result["request_id"], "request-1")
        self.client.publish.assert_called_with("visualiser/phone-a/pair/result",
                                               self.client.publish.call_args.args[1],
                                               qos=1, retain=False)

    def test_retained_and_malformed_requests_do_not_change_lock(self):
        retained = message("visualiser/phone-a/pair/request", {
            "action": "acquire", "device_id": "1", "request_id": "request-1",
        }, retain=True)
        self.service.handle_message(retained)
        self.client.publish.assert_not_called()
        self.service.handle_message(message("visualiser/phone-a/pair/request", b"not-json"))
        result = json.loads(self.client.publish.call_args.args[1])
        self.assertEqual(result["status"], "INVALID")

    def test_invalid_action_returns_correlated_error(self):
        result = self.request("phone-a", "not-an-action")
        self.assertEqual(result["status"], "INVALID")
        self.assertEqual(result["request_id"], "request-1")

    def test_hardware_ids_are_translated_to_public_player_labels(self):
        self.assertEqual(player_id_for_model(PLAYER_1_MODEL), "1")
        self.assertEqual(player_id_for_model(PLAYER_2_MODEL), "2")
        self.assertEqual(validate_player_id("1"), "1")
        with self.assertRaises(ValueError):
            validate_player_id(PLAYER_1_MODEL)

        self.service.handle_message(message(
            f"esp32/{PLAYER_2_MODEL}/status", {"state": "online"}, retain=True))
        topic, payload = self.client.publish.call_args.args[:2]
        self.assertEqual(topic, "ultra96/2/status")
        self.assertEqual(json.loads(payload), {"device_id": "2", "state": "online"})
        self.assertEqual(self.client.publish.call_args.kwargs, {"qos": 1, "retain": True})
        self.assertTrue(self.service.is_device_online("2"))

if __name__ == "__main__":
    unittest.main()
