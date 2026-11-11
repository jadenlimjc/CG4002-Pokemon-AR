// Production hardware runtime. main.ino schedules updateHardware() at 50 Hz
// and transports every sensor sample.

#include "config.h"
#include "touchButton.h"
#include "singleHoldButton.h"
#include "vibrationMotor.h"
#include "rgbLed.h"
#include "passiveBuzzer.h"
#include "motionSensor.h"

// =====================================================
// Global objects
// =====================================================
TouchButton indexButton(TOUCH_INDEX);
SingleHoldButton middleButton(TOUCH_MIDDLE, TOGGLE_HOLD_TIME_MS);
SingleHoldButton ringButton(TOUCH_RING, TOGGLE_HOLD_TIME_MS);

VibrationMotor motor(VIBRATION_MOTOR_PIN, MOTOR_RUN_TIME_MS);
RgbLed led(RED_PIN, GREEN_PIN, BLUE_PIN, LED_PWM_FREQUENCY, LED_PWM_RESOLUTION);
PassiveBuzzer buzzer(BUZZER_PIN, BUZZER_PWM_FREQUENCY, BUZZER_PWM_RESOLUTION);
MotionSensor motion;

bool motionReady = false;
bool telemetryStreamStart = true;
unsigned long lastMotionInitAttempt = 0;

bool indexMotorTrigger = false; //Flags to run motor for each finger touch
bool indexMotorRunning = false;
unsigned long indexMotorStart = 0;

bool middleMotorTrigger = false;
bool middleMotorRunning = false;
unsigned long middleMotorStart = 0;

bool ringMotorTrigger = false;
bool ringMotorRunning = false;
unsigned long ringMotorStart = 0;

bool indexTouchFlag = false;
bool middleTouchFlag = false;
bool ringTouchFlag = false;
bool battleThrowMode = false; // false = catch (blue), true = battle throw (red)

void runSensorCycle();
void updateConnectionLed(bool connected);

// =====================================================
// setup / loop
// =====================================================
void setupHardware() {
  indexButton.begin();
  middleButton.begin();
  ringButton.begin();

  motor.begin();
  motor.registerRunningFlag(&indexMotorRunning);
  motor.registerRunningFlag(&middleMotorRunning);
  motor.registerRunningFlag(&ringMotorRunning);

  buzzer.begin();
  buzzer.off();

  led.begin();
  led.off();

  telemetryStreamStart = true;
  motionReady = motion.begin();
  lastMotionInitAttempt = millis();
  Serial.println("Hardware runtime started");
}

void updateHardware(bool telemetryEnabled, bool gestureSound, bool connected) {
  if (!telemetryEnabled) telemetryStreamStart = true;
  static bool gestureSoundPlaying = false;
  static unsigned long gestureSoundStartedAt = 0;
  indexButton.update();
  if (indexButton.consumeFreshTouch()) {
    indexMotorTrigger = true;
    battleThrowMode = !battleThrowMode;
    indexTouchFlag = true;
    Serial.printf("Throw mode: %s\n", battleThrowMode ? "BATTLE" : "CATCH");
  }
  middleButton.update();
  ringButton.update();
  latestIndexTouchRaw.store(indexButton.rawValue(), std::memory_order_relaxed);
  latestMiddleTouchRaw.store(middleButton.rawValue(), std::memory_order_relaxed);
  latestRingTouchRaw.store(ringButton.rawValue(), std::memory_order_relaxed);
  latestIndexTouchBaseline.store(indexButton.baselineValue(), std::memory_order_relaxed);
  latestMiddleTouchBaseline.store(middleButton.baselineValue(), std::memory_order_relaxed);
  latestRingTouchBaseline.store(ringButton.baselineValue(), std::memory_order_relaxed);
  latestIndexTouchThreshold.store(indexButton.touchThreshold(), std::memory_order_relaxed);
  latestMiddleTouchThreshold.store(middleButton.touchThreshold(), std::memory_order_relaxed);
  latestRingTouchThreshold.store(ringButton.touchThreshold(), std::memory_order_relaxed);
  if (middleButton.consumeFreshTouch()) middleMotorTrigger = true;
  if (ringButton.consumeFreshTouch()) ringMotorTrigger = true;
  if (!telemetryEnabled) {
    if (gestureSoundPlaying) buzzer.off();
    gestureSoundPlaying = false;
  }
  if (gestureSound && telemetryEnabled) {
    buzzer.on(BUZZER_PWM_FREQUENCY);
    gestureSoundStartedAt = millis();
    gestureSoundPlaying = true;
  }
  if (gestureSoundPlaying &&
      millis() - gestureSoundStartedAt >= GESTURE_BUZZER_DURATION_MS) {
    buzzer.off();
    gestureSoundPlaying = false;
  }

  if (middleButton.checkHoldConfirmed()) middleTouchFlag = true;
  if (ringButton.checkHoldConfirmed()) ringTouchFlag = true;

  if (telemetryEnabled) runSensorCycle();

  indexTouchFlag = false;
  middleTouchFlag = false;
  ringTouchFlag = false;

  motor.checkTrigger(middleMotorTrigger, middleMotorRunning, middleMotorStart, "Middle finger");
  motor.checkTrigger(ringMotorTrigger,   ringMotorRunning,   ringMotorStart,  "Ring finger");
  motor.checkTrigger(indexMotorTrigger,  indexMotorRunning,  indexMotorStart,  "Index finger");
  updateConnectionLed(connected);
}

// MQTT is the usable end-to-end connection: blink dim blue while it is being
// established or recovered, then show the ESP-owned throw mode continuously.
// Catch uses steady full blue because the green channel is unreliable on one
// glove; battle remains red.
void updateConnectionLed(bool connected) {
  const bool blinkOn = (millis() / CONNECTION_LED_BLINK_MS) % 2 == 0;
  if (!connected && blinkOn) {
    led.blue(CONNECTION_LED_BLUE_BRIGHTNESS);
  } else if (!connected) {
    led.off();
  } else if (battleThrowMode) {
    led.red();
  } else {
    led.blue();
  }
}

// -------------------------------------------------
// Main sensing cycle: MPU6050 motion
// Called by updateHardware() while automatic telemetry is enabled.
// -------------------------------------------------
void runSensorCycle() {
  // SensorSampleTask supplies the 50 Hz cadence.
  if (!motionReady) {
    if (millis() - lastMotionInitAttempt < 1000) return;
    motionReady = motion.begin();
    lastMotionInitAttempt = millis();
    return;
  }

  sensors_event_t a, g, temp;
  motion.read(a, g, temp);

  const uint8_t controlFlags =
      (indexTouchFlag ? TELEMETRY_TOUCH_INDEX : 0) |
      (middleTouchFlag ? TELEMETRY_TOUCH_MIDDLE : 0) |
      (ringTouchFlag ? TELEMETRY_TOUCH_RING : 0) |
      (battleThrowMode ? TELEMETRY_BATTLE_THROW : 0);
  if (enqueueMotionSample(a, g, controlFlags, telemetryStreamStart)) {
    telemetryStreamStart = false;
  }
}
