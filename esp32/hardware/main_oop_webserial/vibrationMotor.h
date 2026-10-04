#ifndef VIBRATION_MOTOR_H
#define VIBRATION_MOTOR_H

#include <Arduino.h>

// =====================================================
// VibrationMotor: single physical motor pin, shared
// across multiple trigger sources (middle/ring/index).
// Each caller passes its own one-shot trigger + running
// state, the class coordinates the shared physical pin
// so one source's pulse ending doesn't cut off another's.
// =====================================================
class VibrationMotor {
  private:
    bool anySourceRunning() const;

    int pin_;
    unsigned long runTimeMs_;
    bool anyPhysicallyOn_ = false;
    unsigned long pulseStartMillis_ = 0;

    static const int MAX_FLAGS = 3;
    bool* runningFlags_[MAX_FLAGS];
    int numFlags_ = 0;
  public:
    VibrationMotor(int pin, unsigned long runTimeMs);

    void begin();

    // trigger: one-shot flag from a finger/select action.
    void checkTrigger(bool &trigger, bool &running, unsigned long &startMillis, const char* label);

    // Registers a running-flag pointer so anySourceRunning() can
    // check all sources without the motor needing to know about
    // fingers explicitly
    void registerRunningFlag(bool *flag);

    void stopAll();


};

#endif