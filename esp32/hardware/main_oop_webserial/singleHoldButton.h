#ifndef SINGLE_HOLD_BUTTON_H
#define SINGLE_HOLD_BUTTON_H

#include "TouchButton.h"

// =====================================================
// SingleHoldButton: fires exactly once per continuous
// touch, once heldForMs() crosses a threshold. Used for
// middle/ring's single 0.5s hold-to-toggle behavior.
// =====================================================
class SingleHoldButton : public TouchButton {
  private:
    unsigned long holdTimeMs_;
    bool firedThisTouch_ = false;
    
  public:
    SingleHoldButton(int pin, int threshold, unsigned long holdTimeMs);

    // Returns true exactly once per touch, the moment the hold threshold is crossed
    bool checkHoldConfirmed();

  protected:
    void onFreshTouch() override;
    void onRelease() override;


};

#endif 