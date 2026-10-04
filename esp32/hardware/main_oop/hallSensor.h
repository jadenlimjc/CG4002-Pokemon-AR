#ifndef HALL_SENSOR_H
#define HALL_SENSOR_H

#include <Arduino.h>

// =====================================================
// HallSensor: KY-024 hall effect sensor wrapper.
// ISR is a free function (defined in the main .ino) that
// calls onIsr().
// =====================================================
class HallSensor {
  private:
    int digitalPin_;
    int analogPin_;
    volatile int state_ = 1;
    
  public:
    HallSensor(int digitalPin, int analogPin);

    void begin(void (*isrFunc)());
    void end();

    // Called from the global ISR.
    void onIsr();

    void printStatus() const;
    int state() const;

};

#endif // HALL_SENSOR_H