#ifndef TOUCH_BUTTON_H
#define TOUCH_BUTTON_H

#include <Arduino.h>

// =====================================================
// TouchButton: encapsulates one touch pad's ISR flag,
// touched-state tracking, and hold-duration timing.
// ISRs on ESP32 must be free functions, so each TouchButton
// exposes a public onIsr() that the global ISR calls into.
// =====================================================
class TouchButton {
  public:
    TouchButton(int pin, int threshold);

    void begin(void (*isrFunc)());

    // Called from the global ISR - keep minimal, no Serial/delay.
    void onIsr();

    // Call every loop(). Updates touchedState_ and startMillis_
    // based on the ISR flag and current touchRead().
    void update();

    bool isTouched() const;
    unsigned long heldForMs() const;
    unsigned long startMillis() const;

    void resetTouchState();

  protected:

    // Hooks subclasses can override for extra per-touch reset logic.
    virtual void onFreshTouch();
    virtual void onRelease();

    int pin_;
    int threshold_;
    volatile bool isrFlag_ = false;
    bool touchedState_ = false;
    unsigned long startMillis_ = 0;
};

#endif 