#include "touchButton.h"
#include "config.h"

TouchButton::TouchButton(int pin) : pin_(pin) {}

void TouchButton::begin() {
  touchedState_ = false;
  freshTouch_ = false;
  touchArmed_ = false;
  calibrated_ = false;
  rawValue_ = -1;
  baseline_ = 0.0f;
  baselineAccumulator_ = 0;
  baselineSamples_ = 0;
  pressSamples_ = 0;
  releaseSamples_ = 0;
}

void TouchButton::update() {
  // Poll at 50 Hz. During the first second all readings are assumed untouched
  // and averaged. Afterwards the low-pass baseline follows only slow, clearly
  // untouched drift; a sudden downward step is treated as contact.
  rawValue_ = touchRead(pin_);
  if (!calibrated_) {
    baselineAccumulator_ += static_cast<uint32_t>(rawValue_);
    ++baselineSamples_;
    if (baselineSamples_ >= TOUCH_BASELINE_SAMPLE_COUNT) {
      baseline_ = static_cast<float>(baselineAccumulator_) /
          static_cast<float>(baselineSamples_);
      calibrated_ = true;
      touchArmed_ = true;
      Serial.printf("Touch pin %d baseline: %d, touch at or below %d\n",
                    pin_, baselineValue(), touchThreshold());
    }
    return;
  }

  const int pressThreshold = touchThreshold();
  const int releaseThreshold = thresholdFor(
      TOUCH_RELEASE_DROP_PERCENT, TOUCH_RELEASE_MIN_DROP);

  if (touchedState_) {
    pressSamples_ = 0;
    if (rawValue_ > releaseThreshold) {
      if (++releaseSamples_ >= TOUCH_RELEASE_DEBOUNCE_SAMPLES) {
        touchedState_ = false;
        touchArmed_ = true;
        releaseSamples_ = 0;
        onRelease();
      }
    } else {
      releaseSamples_ = 0;
    }
    return;
  }

  // resetTouchState() deliberately disarms the button. Require the same stable
  // physical release before it can generate another edge.
  if (!touchArmed_) {
    pressSamples_ = 0;
    if (rawValue_ > releaseThreshold) {
      if (++releaseSamples_ >= TOUCH_RELEASE_DEBOUNCE_SAMPLES) {
        touchArmed_ = true;
        releaseSamples_ = 0;
      }
    } else {
      releaseSamples_ = 0;
    }
    return;
  }

  releaseSamples_ = 0;
  if (rawValue_ <= pressThreshold) {
    if (++pressSamples_ >= TOUCH_PRESS_DEBOUNCE_SAMPLES) {
      touchedState_ = true;
      freshTouch_ = true;
      touchArmed_ = false;
      pressSamples_ = 0;
      startMillis_ = millis();
      onFreshTouch();
    }
  } else {
    pressSamples_ = 0;
    if (rawValue_ > releaseThreshold) {
      baseline_ += (static_cast<float>(rawValue_) - baseline_) *
          TOUCH_BASELINE_TRACKING_ALPHA;
    }
  }
}

bool TouchButton::isTouched() const { return touchedState_; }
bool TouchButton::isCalibrated() const { return calibrated_; }
int TouchButton::rawValue() const { return rawValue_; }
int TouchButton::baselineValue() const {
  return calibrated_ ? static_cast<int>(baseline_ + 0.5f) : -1;
}
int TouchButton::touchThreshold() const {
  return calibrated_ ? thresholdFor(TOUCH_DROP_PERCENT, TOUCH_MIN_DROP) : -1;
}
bool TouchButton::consumeFreshTouch() {
  const bool wasFresh = freshTouch_;
  freshTouch_ = false;
  return wasFresh;
}
unsigned long TouchButton::heldForMs() const { 
  return millis() - startMillis_; 
}

unsigned long TouchButton::startMillis() const { 
  return startMillis_; 
}

void TouchButton::resetTouchState() {
  touchedState_ = false;
  freshTouch_ = false;
  touchArmed_ = false;
  pressSamples_ = 0;
  releaseSamples_ = 0;
}

int TouchButton::requiredDrop(uint8_t percent, int minimum) const {
  const int relative = static_cast<int>(baseline_ * static_cast<float>(percent) / 100.0f);
  return relative > minimum ? relative : minimum;
}

int TouchButton::thresholdFor(uint8_t percent, int minimum) const {
  const int threshold = baselineValue() - requiredDrop(percent, minimum);
  return threshold > 0 ? threshold : 0;
}

void TouchButton::onFreshTouch() {}
void TouchButton::onRelease() {}
