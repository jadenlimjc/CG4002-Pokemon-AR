#ifndef CONFIG_H
#define CONFIG_H

// =====================================================
// Pin assignments
// =====================================================
#define RED_PIN   D4
#define GREEN_PIN D6
#define BLUE_PIN  D5

#define HALL_ANALOG_PIN  A2
#define HALL_DIGITAL_PIN D2

#define BUZZER_PIN D7
#define VIBRATION_MOTOR_PIN D3

// FireBeetle ESP32 (DFR0478) - original ESP32, TOUCH_V1
const int TOUCH_INDEX  = T3; // A4/IO15
const int TOUCH_MIDDLE = T5; // MCLK/IO12
const int TOUCH_RING   = T6; // BCLK/E014

// =====================================================
// Touch / timing configuration
// =====================================================
const int TOUCH_THRESHOLD = 350;

const unsigned long START_HOLD_TIME_MS  = 5000;  // index: hold to start/stop
const unsigned long SELECT_HOLD_TIME_MS = 500;   // index: hold to select (Battle only)
const unsigned long TOGGLE_HOLD_TIME_MS = 600;   // middle/ring: single hold
const unsigned long MOTOR_RUN_TIME_MS   = 500;
const unsigned long CONNECTION_LED_BLINK_MS = 500;
const unsigned long THROW_MODE_DEBOUNCE_MS = 250;
const unsigned long GESTURE_BUZZER_DURATION_MS = 2000;

// =====================================================
// PWM configuration
// =====================================================
#define LED_PWM_FREQUENCY  5000
#define LED_PWM_RESOLUTION 8
#define CONNECTION_LED_BLUE_BRIGHTNESS 64 // 25% of the 8-bit PWM range
#define BUZZER_PWM_FREQUENCY  1500
#define BUZZER_PWM_RESOLUTION 8

// =====================================================
// Sensor thresholds
// =====================================================
const float ACCEL_THRESHOLD = 5.0;

#endif // CONFIG_H
