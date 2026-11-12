#ifndef CONFIG_H
#define CONFIG_H

// =====================================================
// Pin assignments
// =====================================================
#define RED_PIN   D4
#define GREEN_PIN D6
#define BLUE_PIN  D5

#define BUZZER_PIN D7
#define VIBRATION_MOTOR_PIN D3

// FireBeetle ESP32 (DFR0478) - original ESP32, TOUCH_V1
const int TOUCH_INDEX  = T3; // A4/IO15
const int TOUCH_MIDDLE = T5; // MCLK/IO12
const int TOUCH_RING   = T6; // BCLK/E014

// =====================================================
// Touch / timing configuration
// =====================================================
const uint16_t TOUCH_BASELINE_SAMPLE_COUNT = 50; // 1 second at 50 Hz; keep fingers off at boot
const uint8_t TOUCH_DROP_PERCENT = 15;
const int TOUCH_MIN_DROP = 100;
const uint8_t TOUCH_RELEASE_DROP_PERCENT = 10;
const int TOUCH_RELEASE_MIN_DROP = 50;
const float TOUCH_BASELINE_TRACKING_ALPHA = 0.005f;
const unsigned long TOUCH_BASELINE_RECOVERY_DELAY_MS = 3000;
const uint8_t TOUCH_PRESS_DEBOUNCE_SAMPLES = 3;   // 60 ms at the 50 Hz hardware cadence
const uint8_t TOUCH_RELEASE_DEBOUNCE_SAMPLES = 5; // 100 ms before another touch can fire
static_assert(TOUCH_BASELINE_SAMPLE_COUNT > 0, "Touch calibration needs samples");
static_assert(TOUCH_BASELINE_RECOVERY_DELAY_MS > 0, "Touch recovery needs a delay");
static_assert(TOUCH_PRESS_DEBOUNCE_SAMPLES > 0 && TOUCH_RELEASE_DEBOUNCE_SAMPLES > 0,
              "Touch debounce needs at least one sample");
// static_assert(TOUCH_DROP_PERCENT > TOUCH_RELEASE_DROP_PERCENT,
              // "Touch release must be less sensitive than touch detection");

const unsigned long TOGGLE_HOLD_TIME_MS = 600;   // middle/ring: single hold
const unsigned long MOTOR_RUN_TIME_MS   = 175;
const unsigned long CONNECTION_LED_BLINK_MS = 500;
const unsigned long GESTURE_BUZZER_DURATION_MS = 100;

// =====================================================
// PWM configuration
// =====================================================
#define LED_PWM_FREQUENCY  5000
#define LED_PWM_RESOLUTION 8
#define STATUS_LED_BRIGHTNESS 64 // 25% of the 8-bit PWM range
#define BUZZER_PWM_FREQUENCY  1500
#define BUZZER_PWM_RESOLUTION 8

#endif // CONFIG_H
