#include "singleHoldButton.h"

SingleHoldButton::SingleHoldButton(int pin, unsigned long holdTimeMs)
  : TouchButton(pin), holdTimeMs_(holdTimeMs) {}

bool SingleHoldButton::checkHoldConfirmed() {
  if (touchedState_ && !firedThisTouch_ && heldForMs() >= holdTimeMs_) {
    firedThisTouch_ = true;
    return true;
  }
  return false;
}

void SingleHoldButton::onFreshTouch() { 
  firedThisTouch_ = false; 
}

void SingleHoldButton::onRelease() { 
  firedThisTouch_ = false; 
}
