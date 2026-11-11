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

    // Call every loop(). Polling supplies live diagnostics and observes release
    // so one physical press can produce only one fresh edge.
    void update();

    bool isTouched() const;
    int rawValue() const;
    // Returns true once for each new touch edge.
    bool consumeFreshTouch();
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
    bool freshTouch_ = false;
    bool touchArmed_ = true;
    int rawValue_ = -1;
    unsigned long startMillis_ = 0;
};

#endif // TOUCH_BUTTON_H
