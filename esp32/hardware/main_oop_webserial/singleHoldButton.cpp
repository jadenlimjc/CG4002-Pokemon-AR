#include "singleHoldButton.h"
#include "DualPrint.h"

SingleHoldButton::SingleHoldButton(int pin, int threshold, unsigned long holdTimeMs)
  : TouchButton(pin, threshold), holdTimeMs_(holdTimeMs) {}

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