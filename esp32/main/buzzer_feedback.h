#pragma once

#include "hardware_config.h"
#include <atomic>

// No touch gestures or application state. begin()/update() belong to loop's
// task; beep()/stop() are safe to call from other tasks (not ISRs).
class BuzzerFeedback {
public:
    explicit BuzzerFeedback(uint8_t pin = hardware::BUZZER_PIN) : pin(pin) {}
    bool begin();
    void beep(uint16_t frequencyHz = hardware::BEEP_FREQUENCY_HZ,
              uint16_t durationMs = hardware::BEEP_DURATION_MS);
    void stop();
    void update();

private:
    // One atomic word keeps each request's frequency and duration together.
    // Duration occupies the high half; zero duration with nonzero frequency
    // is reserved for an explicit stop command. Latest pending request wins.
    static constexpr uint8_t PARAMETER_BITS = 16;
    static constexpr uint32_t PARAMETER_MASK = UINT16_MAX;
    static constexpr uint32_t STOP_REQUEST = 1;
    uint8_t pin;
    std::atomic<uint32_t> pending{0};
    bool ready = false, playing = false;
    uint32_t startedAt = 0;
    uint16_t duration = 0;
};
