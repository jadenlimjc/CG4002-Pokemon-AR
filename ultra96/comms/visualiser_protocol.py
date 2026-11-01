"""Translate classifier labels into the AR app's GesturePayload contract.

No MQTT, numpy or Unity dependencies. Keep game-specific naming out of the
transport; future inference implementations can call this same boundary.
"""

import math
import time
from dataclasses import dataclass

DEFAULT_CONFIDENCE_THRESHOLD = 0.75


def confidence_threshold(value):
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("confidence threshold must be finite and between 0 and 1")
    return value

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


@dataclass(frozen=True)
class SequenceState:
    name: str = "NEUTRAL"
    last_action: str | None = None


@dataclass(frozen=True)
class GestureDecision:
    """A proposed transition. Publishing callers commit only after acceptance."""
    before: SequenceState
    after: SequenceState
    payload: dict | None
    reason: str
    detail: str


class GestureSequence:
    """Per-device confidence gate and catch sequencing, owned by inference.

    Aim arms one throw. Stop Aim or Neutral cancels/rearms; after a throw that
    reset is required before another gesture. A battle gesture enters RECOVERING;
    only confident Neutral rearms recognition. Rejected labels, including Stop
    Aim during recovery, never clear the repeat latch. Live callers confirm
    labels before evaluating them here.

    No voting, dwell time, cooldown, or changes to the model window are applied.
    evaluate() is pure; commit() lets transport failure leave the state intact.
    """
    def __init__(self, threshold=DEFAULT_CONFIDENCE_THRESHOLD):
        self.confidence_threshold = confidence_threshold(threshold)
        self._state = SequenceState()

    @property
    def state(self):
        return self._state.name

    @property
    def aiming(self):
        return self.state == "AIMING"

    @property
    def awaiting_reset(self):
        return self.state == "AWAITING_RESET"

    @property
    def last_action(self):
        return self._state.last_action

    def evaluate(self, predicted_action, confidence, *, timestamp_ms=None):
        payload = create_gesture_payload(predicted_action, confidence,
                                         timestamp_ms=timestamp_ms)
        before = self._state

        def reject(reason, detail):
            return GestureDecision(before, before, None, reason, detail)

        if payload["confidence"] < self.confidence_threshold:
            return reject("LOW_CONFIDENCE", f"Confidence {payload['confidence']:.2%} is below "
                          f"{self.confidence_threshold:.2%}; state and repeat latch unchanged.")
        if predicted_action in ("NEUTRAL", "STOP_AIMING"):
            if self.aiming or self.awaiting_reset:
                cancel = create_gesture_payload("STOP_AIMING", confidence,
                                                timestamp_ms=payload["timestamp"])
                return GestureDecision(before, SequenceState(), cancel, "RESET",
                                       "Return to neutral; send CANCEL and rearm gestures.")
            if predicted_action == "STOP_AIMING":
                return reject("NOT_AIMING", "STOP_AIMING is invalid while neutral; repeat latch unchanged.")
            return GestureDecision(before, SequenceState(), None, "NEUTRAL",
                                   "Confident neutral; repeat latch cleared. No gameplay event needed.")
        if self.awaiting_reset:
            return reject("AWAITING_RESET", "Throw already sent; return to NEUTRAL or STOP_AIMING first.")
        if self.state == "RECOVERING":
            if predicted_action == self.last_action:
                return reject("REPEATED", f"{predicted_action} already sent; return to confirmed NEUTRAL first.")
            return reject("RECOVERING", "Battle action already sent; return to confirmed NEUTRAL before another gesture.")
        if predicted_action == "AIM":
            if self.aiming:
                return reject("ALREADY_AIMING", "AIM already sent; waiting for THROW, STOP_AIMING or NEUTRAL.")
            after = SequenceState("AIMING", predicted_action)
        elif predicted_action == "THROW":
            if not self.aiming:
                return reject("NOT_AIMING", "THROW is invalid until AIM has been sent.")
            after = SequenceState("AWAITING_RESET", predicted_action)
        elif self.aiming:
            return reject("AIMING_LOCK", "Finish with THROW or cancel with STOP_AIMING / NEUTRAL first.")
        else:
            after = SequenceState("RECOVERING", predicted_action)
        return GestureDecision(before, after, payload, "VALID", "Confidence and gesture sequence are valid.")

    def commit(self, decision):
        if self._state != decision.before:
            raise ValueError("Cannot commit a decision from an outdated gesture state")
        self._state = decision.after

    def consume(self, predicted_action, confidence, *, timestamp_ms=None):
        """Convenience for transport-free consumers; live sends use evaluate/commit."""
        decision = self.evaluate(predicted_action, confidence, timestamp_ms=timestamp_ms)
        self.commit(decision)
        return decision.payload
