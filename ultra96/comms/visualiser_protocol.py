"""Translate classifier labels into the AR app's GesturePayload contract.

No MQTT, numpy or Unity dependencies. Keep game-specific naming out of the
transport; future inference implementations can call this same boundary.
"""

import math
import time
from dataclasses import dataclass

DEFAULT_CONFIDENCE_THRESHOLD = 0.60


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

# Add classifier-label-specific overrides here. Labels not listed use
# DEFAULT_CONFIDENCE_THRESHOLD.
GESTURE_CONFIDENCE_THRESHOLDS = {
    "FLEE": 0.90,
    "NEUTRAL": 0.80,
    "AIM": 0.50,
    "DOWNWARD_SWIPE": 0.85,
}


def confidence_threshold_overrides(values=None):
    values = GESTURE_CONFIDENCE_THRESHOLDS if values is None else values
    overrides = {}
    for action, value in dict(values).items():
        if action not in GESTURE_MAPPING:
            raise ValueError(f"Unsupported confidence-threshold action: {action!r}")
        overrides[action] = confidence_threshold(value)
    return overrides


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

    Aim arms one throw. Stop Aim explicitly cancels/rearms; Neutral is consumed
    without changing the catch state. After a throw, Stop Aim is required before
    another gesture. Battle actions return immediately to the ready state; the
    live caller applies a post-publish cooldown before accepting another gesture.

    No voting, dwell time, or changes to the model window are applied here.
    evaluate() is pure; commit() lets transport failure leave the state intact.
    """
    def __init__(self, threshold=DEFAULT_CONFIDENCE_THRESHOLD, threshold_overrides=None):
        self.confidence_threshold = confidence_threshold(threshold)
        self.confidence_threshold_overrides = confidence_threshold_overrides(
            threshold_overrides
        )
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

    def confidence_threshold_for(self, predicted_action):
        if predicted_action not in GESTURE_MAPPING:
            raise ValueError(f"Unsupported classifier action: {predicted_action!r}")
        return self.confidence_threshold_overrides.get(
            predicted_action, self.confidence_threshold
        )

    def evaluate(self, predicted_action, confidence, *, timestamp_ms=None):
        payload = create_gesture_payload(predicted_action, confidence,
                                         timestamp_ms=timestamp_ms)
        before = self._state

        def reject(reason, detail):
            return GestureDecision(before, before, None, reason, detail)

        threshold = self.confidence_threshold_for(predicted_action)
        if payload["confidence"] < threshold:
            return reject("LOW_CONFIDENCE", f"Confidence {payload['confidence']:.2%} is below "
                          f"the {threshold:.2%} threshold; state unchanged.")

        if predicted_action == "NEUTRAL":
            return reject("NEUTRAL", "Neutral is ignored; gesture state unchanged.")

        if predicted_action == "AIM":
            if self.aiming:
                return reject("ALREADY_AIMING", "AIM already sent; waiting for THROW or STOP_AIMING.")
            after = SequenceState("AIMING")

        elif predicted_action in {"THROW", "STOP_AIMING"}:
            if not self.aiming:
                return reject(
                    "NOT_AIMING",
                    f"{predicted_action} is invalid until AIM has been sent.",
                )
            after = SequenceState()

        else:
            after = before

        return GestureDecision(
            before,
            after,
            payload,
            "VALID",
            "Confidence and gesture sequence are valid.",
        )

    def commit(self, decision):
        if self._state != decision.before:
            raise ValueError("Cannot commit a decision from an outdated gesture state")
        self._state = decision.after

    def consume(self, predicted_action, confidence, *, timestamp_ms=None):
        """Convenience for transport-free consumers; live sends use evaluate/commit."""
        decision = self.evaluate(predicted_action, confidence, timestamp_ms=timestamp_ms)
        self.commit(decision)
        return decision.payload
