"""Exclusive, renewable ESP32-to-visualiser pairing leases over MQTT."""

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
from threading import RLock
import time


LEASE_SECONDS = 5 * 60
PAIR_REQUEST_SUBSCRIPTION = "visualiser/+/pair/request"
DEVICE_STATUS_SUBSCRIPTION = "esp32/+/status"
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,64}")

# Public player labels stay stable even though the ESP32s identify themselves
# with their hardware-derived model IDs. Only Ultra96 knows this translation.
PLAYER_TO_MODEL_ID = {
    "1": "dce6f6215788",
    "2": "cc386a2b1838",
}
MODEL_ID_TO_PLAYER = {model_id: player_id
                      for player_id, model_id in PLAYER_TO_MODEL_ID.items()}


def validate_identifier(value, field="identifier"):
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{field} must contain 1-64 letters, digits, underscores or hyphens")
    return value


def player_id_for_model(model_id):
    """Return the phone-facing player label for a physical ESP32 ID."""
    validate_identifier(model_id, "model_id")
    return MODEL_ID_TO_PLAYER.get(model_id)


def validate_player_id(player_id):
    validate_identifier(player_id, "device_id")
    if player_id not in PLAYER_TO_MODEL_ID:
        raise ValueError("device_id must be 1 or 2")
    return player_id


def status_is_online(payload):
    """Interpret the retained ESP32 online publication or offline LWT."""
    if len(payload) > 512:
        return False
    try:
        status = json.loads(payload)
    except (TypeError, ValueError, UnicodeError):
        return False
    return isinstance(status, dict) and status.get("state") == "online"


@dataclass(frozen=True)
class PairingLease:
    phone_id: str
    device_id: str
    expires_at: float


class PairingRegistry:
    """Thread-safe, one-phone-to-one-device leases persisted across restarts."""

    def __init__(self, path=None, lease_seconds=LEASE_SECONDS, clock=time.time):
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self.path = Path(path) if path is not None else Path(__file__).with_name("pairing_leases.json")
        self.lease_seconds = lease_seconds
        self.clock = clock
        self.lock = RLock()
        self.by_device = {}
        self.by_phone = {}
        self._load()

    def _load(self):
        try:
            records = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError, UnicodeError):
            return
        if not isinstance(records, list):
            return
        now = self.clock()
        for record in records:
            try:
                lease = PairingLease(
                    validate_identifier(record["phone_id"], "phone_id"),
                    validate_identifier(record["device_id"], "device_id"),
                    float(record["expires_at"]),
                )
            except (KeyError, TypeError, ValueError):
                continue
            if (lease.expires_at <= now or lease.device_id in self.by_device
                    or lease.phone_id in self.by_phone):
                continue
            self.by_device[lease.device_id] = lease
            self.by_phone[lease.phone_id] = lease

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        records = [asdict(lease) for lease in sorted(
            self.by_device.values(), key=lambda item: item.device_id)]
        with temporary.open("w", encoding="utf-8") as output:
            json.dump(records, output, separators=(",", ":"), sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, self.path)

    def _expire(self, now):
        expired = [lease for lease in self.by_device.values() if lease.expires_at <= now]
        for lease in expired:
            self.by_device.pop(lease.device_id, None)
            self.by_phone.pop(lease.phone_id, None)
        return bool(expired)

    def acquire(self, phone_id, device_id):
        phone_id = validate_identifier(phone_id, "phone_id")
        device_id = validate_identifier(device_id, "device_id")
        with self.lock:
            now = self.clock()
            changed = self._expire(now)
            owner = self.by_device.get(device_id)
            if owner is not None and owner.phone_id != phone_id:
                if changed:
                    self._save()
                return self._result("LOCKED", owner, now)

            previous = self.by_phone.get(phone_id)
            if previous is not None and previous.device_id != device_id:
                self.by_device.pop(previous.device_id, None)
            lease = PairingLease(phone_id, device_id, now + self.lease_seconds)
            self.by_device[device_id] = lease
            self.by_phone[phone_id] = lease
            self._save()
            return self._result("RECLAIMED" if owner is not None else "ACQUIRED", lease, now)

    def renew(self, phone_id, device_id):
        phone_id = validate_identifier(phone_id, "phone_id")
        device_id = validate_identifier(device_id, "device_id")
        with self.lock:
            now = self.clock()
            self._expire(now)
            lease = self.by_device.get(device_id)
            if lease is None or lease.phone_id != phone_id:
                self._save()
                return {"status": "EXPIRED", "device_id": device_id, "lease_remaining_ms": 0}
            renewed = PairingLease(phone_id, device_id, now + self.lease_seconds)
            self.by_device[device_id] = renewed
            self.by_phone[phone_id] = renewed
            self._save()
            return self._result("RENEWED", renewed, now)

    def release(self, phone_id, device_id):
        phone_id = validate_identifier(phone_id, "phone_id")
        device_id = validate_identifier(device_id, "device_id")
        with self.lock:
            now = self.clock()
            self._expire(now)
            lease = self.by_device.get(device_id)
            if lease is not None and lease.phone_id != phone_id:
                self._save()
                return self._result("LOCKED", lease, now)
            if lease is not None:
                self.by_device.pop(device_id, None)
                self.by_phone.pop(phone_id, None)
            self._save()
            return {"status": "RELEASED", "device_id": device_id, "lease_remaining_ms": 0}

    def lease_for_device(self, device_id):
        device_id = validate_identifier(device_id, "device_id")
        with self.lock:
            now = self.clock()
            if self._expire(now):
                self._save()
            return self.by_device.get(device_id)

    @staticmethod
    def _result(status, lease, now):
        return {
            "status": status,
            "device_id": lease.device_id,
            "lease_expires_at_ms": int(lease.expires_at * 1000),
            "lease_remaining_ms": max(0, int((lease.expires_at - now) * 1000)),
        }


class PairingService:
    """Translate MQTT presence and request messages into registry operations."""

    def __init__(self, client, registry=None):
        self.client = client
        self.registry = registry or PairingRegistry()
        self.online_devices = set()
        self.lock = RLock()

    def is_device_online(self, device_id):
        validate_player_id(device_id)
        with self.lock:
            return device_id in self.online_devices

    def handle_message(self, message):
        parts = (message.topic or "").split("/")
        if len(parts) == 3 and parts[0] == "esp32" and parts[2] == "status":
            try:
                model_id = validate_identifier(parts[1], "model_id")
            except ValueError:
                return True
            player_id = player_id_for_model(model_id)
            if player_id is None:
                return True
            online = status_is_online(message.payload)
            with self.lock:
                if online:
                    self.online_devices.add(player_id)
                else:
                    self.online_devices.discard(player_id)
            payload = json.dumps({"device_id": player_id,
                                  "state": "online" if online else "offline"},
                                 separators=(",", ":"), sort_keys=True)
            self.client.publish(f"ultra96/{player_id}/status", payload,
                                qos=1, retain=True)
            return True

        if (len(parts) != 4 or parts[0] != "visualiser" or parts[2:] != ["pair", "request"]):
            return False
        if message.retain:
            return True
        try:
            phone_id = validate_identifier(parts[1], "phone_id")
        except ValueError:
            return True
        request_id = None
        try:
            if len(message.payload) > 1024:
                raise ValueError("oversized request")
            request = json.loads(message.payload)
            if not isinstance(request, dict):
                raise ValueError("expected request object")
            request_id = validate_identifier(request.get("request_id"), "request_id")
            device_id = validate_player_id(request.get("device_id"))
            action = request.get("action")
            if action == "acquire":
                current = self.registry.lease_for_device(device_id)
                if current is None and not self.is_device_online(device_id):
                    result = {"status": "OFFLINE", "device_id": device_id,
                              "lease_remaining_ms": 0}
                else:
                    result = self.registry.acquire(phone_id, device_id)
            elif action == "renew":
                result = self.registry.renew(phone_id, device_id)
            elif action == "release":
                result = self.registry.release(phone_id, device_id)
            else:
                raise ValueError("unknown action")
        except (TypeError, ValueError, UnicodeError) as error:
            result = {"status": "INVALID", "device_id": "", "lease_remaining_ms": 0,
                      "detail": str(error)}

        result["request_id"] = request_id
        payload = json.dumps(result, separators=(",", ":"), sort_keys=True)
        self.client.publish(f"visualiser/{phone_id}/pair/result", payload,
                            qos=1, retain=False)
        return True
