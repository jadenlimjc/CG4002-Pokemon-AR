#ifndef PASSIVE_BUZZER_H
#define PASSIVE_BUZZER_H

#include <Arduino.h>

// =====================================================
// PassiveBuzzer: simple PWM-tone buzzer wrapper.
// =====================================================
class PassiveBuzzer {
  private:
    int pin_;
    int freq_;
    int resolution_;

  public:
    PassiveBuzzer(int pin, int freq, int resolution);

    bool begin();
    void playStartSound();
    void playEndSound();
    void on(uint32_t frequency);
    void off();


};

#endif // PASSIVE_BUZZER_H