#include "buzzer_feedback.h"

bool BuzzerFeedback::begin() {
    pending.store(0);
    playing = false;
    ready = ledcAttach(pin, hardware::BUZZER_PWM_FREQUENCY_HZ, hardware::BUZZER_PWM_RESOLUTION_BITS);
    if (ready) ledcWriteTone(pin, 0);
    return ready;
}

void BuzzerFeedback::beep(uint16_t frequencyHz, uint16_t durationMs) {
    if (!frequencyHz || !durationMs) return;
    pending.store((uint32_t(durationMs) << PARAMETER_BITS) | frequencyHz);
}

void BuzzerFeedback::stop() {
    pending.store(STOP_REQUEST);
}

void BuzzerFeedback::update() {
    const uint32_t request = pending.exchange(0);
    if (!ready) return;
    const uint32_t now = millis();
    if (request == STOP_REQUEST) {
        ledcWriteTone(pin, 0);
        playing = false;
    } else if (request) {
        duration = request >> PARAMETER_BITS;
        startedAt = now;
        playing = true;
        ledcWriteTone(pin, request & PARAMETER_MASK);
    }
    if (playing && uint32_t(now - startedAt) >= duration) {
        ledcWriteTone(pin, 0);
        playing = false;
    }
}
