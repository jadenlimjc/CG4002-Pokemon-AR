#ifndef TOUCH_BUTTON_H
#define TOUCH_BUTTON_H

#include <Arduino.h>

// =====================================================
// TouchButton: calibrates an untouched startup baseline, tracks slow drift,
// and debounces the large relative drop caused by a finger.
// =====================================================
class TouchButton {
  public:
    explicit TouchButton(int pin);

    void begin();

    // Call every loop(). Polling supplies live diagnostics and observes release
    // so one physical press can produce only one fresh edge.
    void update();

    bool isTouched() const;
    bool isCalibrated() const;
    int rawValue() const;
    int baselineValue() const;
    int touchThreshold() const;
    // Returns true once for each new touch edge.
    bool consumeFreshTouch();
    unsigned long heldForMs() const;
    unsigned long startMillis() const;

    void resetTouchState();

  protected:
    // Hooks subclasses can override for extra per-touch reset logic.
    virtual void onFreshTouch();
    virtual void onRelease();

    int requiredDrop(uint8_t percent, int minimum) const;
    int thresholdFor(uint8_t percent, int minimum) const;

    int pin_;
    bool touchedState_ = false;
    bool freshTouch_ = false;
    bool touchArmed_ = false;
    bool calibrated_ = false;
    int rawValue_ = -1;
    float baseline_ = 0.0f;
    uint32_t baselineAccumulator_ = 0;
    uint16_t baselineSamples_ = 0;
    uint8_t pressSamples_ = 0;
    uint8_t releaseSamples_ = 0;
    unsigned long startMillis_ = 0;
};

#endif // TOUCH_BUTTON_H
