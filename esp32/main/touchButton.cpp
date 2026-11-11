#include "touchButton.h"

TouchButton::TouchButton(int pin, int threshold)
  : pin_(pin), threshold_(threshold) {}

void TouchButton::begin(void (*isrFunc)()) {
  touchAttachInterrupt(pin_, isrFunc, threshold_);
}

void TouchButton::onIsr() {
  isrFlag_ = true;
}

void TouchButton::update() {
  // ESP touch interrupts announce contact but not necessarily release. Sample
  // at the hardware task cadence so diagnostics remain current and release is
  // always observed. touchArmed_ stays false across resetTouchState(), which
  // prevents a held pad from being treated as a second touch.
  const bool interrupted = isrFlag_;
  isrFlag_ = false;
  rawValue_ = touchRead(pin_);
  if (interrupted) {
    Serial.print("Touch sensor raw value");
    Serial.println(rawValue_);
  }
  const bool touchedNow = (rawValue_ < threshold_);
  const unsigned long now = millis();

  if (touchedNow && !touchedState_ && touchArmed_) {
    touchedState_ = true;
    freshTouch_ = true;
    touchArmed_ = false;
    startMillis_ = now;
    onFreshTouch();
  } else if (!touchedNow) {
    if (touchedState_) {
      touchedState_ = false;
      onRelease();
    }
    touchArmed_ = true;
  }
}

bool TouchButton::isTouched() const { return touchedState_; }
int TouchButton::rawValue() const { return rawValue_; }
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
  isrFlag_ = false;
  touchArmed_ = false;
}

void TouchButton::onFreshTouch() {}
void TouchButton::onRelease() {}
