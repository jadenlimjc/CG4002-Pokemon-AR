"""Translate classifier labels into the AR app's GesturePayload contract.

No MQTT, numpy or Unity dependencies. Keep game-specific naming out of the
transport; future inference implementations can call this same boundary.
"""

import math
import time

# Canonical labels for the new gesture set. IDs are game move slots, not CNN class indices.
GESTURE_MAPPING = {
    "AIM": ("ARM_PULLBACK", 0),
    "STOP_AIMING": ("CANCEL", 0),
    "THROW": ("CATCH_THROW", 0),
    "PUNCH": ("BATTLE_MOVE", 1),
    "DOWNWARD_SWIPE": ("BATTLE_MOVE", 2),
    "UPPERCUT": ("BATTLE_MOVE", 3),
    "GUARD": ("BATTLE_MOVE", 4),
    "FLEE": ("BATTLE_ACTION", 1),
    "SWITCH_POKEMON": ("BATTLE_ACTION", 2),
    "USE_ITEM": ("BATTLE_ACTION", 3),
    "NEUTRAL": ("NONE", 0),
}


def create_gesture_payload(predicted_action, confidence, *, timestamp_ms=None):
    """Return Unity's four fields; caller may append diagnostic metadata.

    NEUTRAL is represented internally as NONE and consumed by GestureSequence;
    it is never published as a gameplay action.
    Unknown labels and invalid confidence fail instead of triggering gameplay.
    """
    try:
        action, gesture_id = GESTURE_MAPPING[predicted_action]
    except KeyError:
        raise ValueError(f"Unsupported classifier action: {predicted_action!r}") from None
    confidence = float(confidence)
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("confidence must be finite and between 0 and 1")
    if timestamp_ms is None:
        timestamp_ms = time.time_ns() // 1_000_000
    if type(timestamp_ms) is not int or timestamp_ms < 0:
        raise ValueError("timestamp_ms must be a non-negative integer")
    return {
        "action": action,
        "gesture_id": gesture_id,
        "confidence": confidence,
        "timestamp": timestamp_ms,
    }


class GestureSequence:
    """Per-device recognition state, independent of transport and game phase.

    Aim arms one throw. Stop Aim or Neutral cancels/rearms; after a throw that
    reset is required before another gesture is accepted. Repeated windows of
    the same non-neutral gesture produce one event, until the label changes.
    """
    def __init__(self):
        self.aiming = False
        self.awaiting_reset = False
        self.last_action = None

    def consume(self, predicted_action, confidence, *, timestamp_ms=None):
        # Validate before changing state, including for a neutral observation.
        payload = create_gesture_payload(predicted_action, confidence, timestamp_ms=timestamp_ms)
        if predicted_action in ("NEUTRAL", "STOP_AIMING"):
            had_catch_sequence = self.aiming or self.awaiting_reset
            self.aiming = False
            self.awaiting_reset = False
            self.last_action = None
            if had_catch_sequence:
                return create_gesture_payload("STOP_AIMING", confidence,
                                              timestamp_ms=payload["timestamp"])
            return None
        if self.awaiting_reset:
            return None
        if predicted_action == "AIM":
            if self.aiming:
                return None
            self.aiming = True
        elif predicted_action == "THROW":
            if not self.aiming:
                return None
            self.aiming = False
            self.awaiting_reset = True
        elif self.aiming:
            return None  # Finish/cancel the catch sequence before another action.
        elif predicted_action == self.last_action:
            return None
        self.last_action = predicted_action
        return payload
