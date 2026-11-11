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
  // An ESP touch interrupt reliably announces contact but not necessarily the
  // release edge. Once contact begins, poll until a physical release is seen.
  // touchArmed_ remains false across resetTouchState(), preventing a held pad
  // from being treated as a second touch.
  if (isrFlag_ || touchedState_ || !touchArmed_) {
    const bool interrupted = isrFlag_;
    isrFlag_ = false;
    int raw = touchRead(pin_);
    if (interrupted) {
      Serial.print("Touch sensor raw value");
      Serial.println(raw);
    }
    bool touchedNow = (raw < threshold_);
    unsigned long now = millis();

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
}

bool TouchButton::isTouched() const { return touchedState_; }
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
