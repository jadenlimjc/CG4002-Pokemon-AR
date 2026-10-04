#include "touchButton.h"
#include "DualPrint.h"

TouchButton::TouchButton(int pin, int threshold)
  : pin_(pin), threshold_(threshold) {}

void TouchButton::begin(void (*isrFunc)()) {
  touchAttachInterrupt(pin_, isrFunc, threshold_);
}

void TouchButton::onIsr() {
  isrFlag_ = true;
}

void TouchButton::update() {
  if (isrFlag_) {
    isrFlag_ = false;
    int raw = touchRead(pin_);
    bool touchedNow = (raw < threshold_);
    unsigned long now = millis();

    if (touchedNow && !touchedState_) {
      touchedState_ = true;
      startMillis_ = now;
      onFreshTouch();
    } else if (!touchedNow && touchedState_) {
      touchedState_ = false;
      onRelease();
    }
  }
}

bool TouchButton::isTouched() const { return touchedState_; }
unsigned long TouchButton::heldForMs() const { 
  return millis() - startMillis_; 
}

unsigned long TouchButton::startMillis() const { 
  return startMillis_; 
}

void TouchButton::resetTouchState() {
  touchedState_ = false;
  isrFlag_ = false;
}

void TouchButton::onFreshTouch() {}
void TouchButton::onRelease() {}