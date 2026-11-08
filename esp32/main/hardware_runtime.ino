// Copied from hardware/main_oop/main_oop.ino. Hardware objects and lifecycle
// stay here; main.ino schedules updateHardware() and transports sensor events.
// OFF: send every 50 Hz reading. ON: send only significant motion changes.
constexpr bool DETECT_MOTION = false;

#include "config.h"
#include "touchButton.h"
#include "singleHoldButton.h"
#include "vibrationMotor.h"
#include "rgbLed.h"
#include "passiveBuzzer.h"
#include "motionSensor.h"
#include "appStateMachine.h"

// =====================================================
// Global objects
// =====================================================
TouchButton indexButton(TOUCH_INDEX, TOUCH_THRESHOLD);
SingleHoldButton middleButton(TOUCH_MIDDLE, TOUCH_THRESHOLD, TOGGLE_HOLD_TIME_MS);
SingleHoldButton ringButton(TOUCH_RING, TOUCH_THRESHOLD, TOGGLE_HOLD_TIME_MS);

VibrationMotor motor(VIBRATION_MOTOR_PIN, MOTOR_RUN_TIME_MS);
RgbLed led(RED_PIN, GREEN_PIN, BLUE_PIN, LED_PWM_FREQUENCY, LED_PWM_RESOLUTION);
PassiveBuzzer buzzer(BUZZER_PIN, BUZZER_PWM_FREQUENCY, BUZZER_PWM_RESOLUTION);
MotionSensor motion;
AppStateMachine app;

bool programStarted = false; //Start program flag
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

bool isUpPressed = false; //used to send status to ultra96
bool isDownPressed = false;
bool isSelectPressed = false;

bool indexSelectFiredTouch = false;

// =====================================================
// Free-function ISRs (required - cannot be member functions)
// =====================================================
void IRAM_ATTR onIndexTouchIsr()  { 
  indexButton.onIsr(); 
}
void IRAM_ATTR onMiddleTouchIsr() { 
  middleButton.onIsr(); 
}
void IRAM_ATTR onRingTouchIsr()   { 
  ringButton.onIsr(); 
}

void handleIndexHoldToggle();
void checkSelectGesture();
void routeGestures();
void checkSimulatedModelResponse();
void runSensorCycle();
void initHardware();
void shutdownHardware();
void updateConnectionLed(bool connected);

// =====================================================
// setup / loop
// =====================================================
void setupHardware() {
  indexButton.begin(onIndexTouchIsr);
  middleButton.begin(onMiddleTouchIsr);
  ringButton.begin(onRingTouchIsr);

  initHardware();
  programStarted = true;

  motor.begin();
  motor.registerRunningFlag(&indexMotorRunning);
  motor.registerRunningFlag(&middleMotorRunning);
  motor.registerRunningFlag(&ringMotorRunning);

  buzzer.begin();
  buzzer.off();

  led.begin();
  led.off();

}

void updateHardware(bool telemetryEnabled, bool gestureSound, bool connected) {
  if (!telemetryEnabled) telemetryStreamStart = true;
  static bool gestureSoundPlaying = false;
  static unsigned long gestureSoundStartedAt = 0;
  const bool wasStarted = programStarted;
  handleIndexHoldToggle();
  if (indexButton.consumeFreshTouch()) indexMotorTrigger = true;
  middleButton.update();
  ringButton.update();
  if (middleButton.consumeFreshTouch()) middleMotorTrigger = true;
  if (ringButton.consumeFreshTouch()) ringMotorTrigger = true;
  if (programStarted != wasStarted || !telemetryEnabled) {
    if (gestureSoundPlaying) buzzer.off();
    gestureSoundPlaying = false;
  }
  if (gestureSound && telemetryEnabled && programStarted) {
    buzzer.on(BUZZER_PWM_FREQUENCY);
    gestureSoundStartedAt = millis();
    gestureSoundPlaying = true;
  }
  if (gestureSoundPlaying &&
      millis() - gestureSoundStartedAt >= GESTURE_BUZZER_DURATION_MS) {
    buzzer.off();
    gestureSoundPlaying = false;
  }

  if (programStarted) {
    checkSelectGesture();
    routeGestures();
    checkSimulatedModelResponse();
    // checkHallStatusChange();

    if (telemetryEnabled) runSensorCycle();

    isUpPressed = false;
    isDownPressed = false;
    isSelectPressed = false;

  } else {
    middleButton.resetTouchState();
    ringButton.resetTouchState();
  }

  motor.checkTrigger(middleMotorTrigger, middleMotorRunning, middleMotorStart, "Middle finger");
  motor.checkTrigger(ringMotorTrigger,   ringMotorRunning,   ringMotorStart,  "Ring finger");
  motor.checkTrigger(indexMotorTrigger,  indexMotorRunning,  indexMotorStart,  "Index finger");
  updateConnectionLed(connected);
}

// MQTT is the usable end-to-end connection: blink while it is being established
// or recovered, then hold a dim blue once it is available.
void updateConnectionLed(bool connected) {
  const bool blinkOn = (millis() / CONNECTION_LED_BLINK_MS) % 2 == 0;
  if (connected || blinkOn) {
    led.blue(CONNECTION_LED_BLUE_BRIGHTNESS);
  } else {
    led.off();
  }
}

// -------------------------------------------------
// Index: 5s hold-to-toggle start/stop
// -------------------------------------------------
void handleIndexHoldToggle() {
  indexButton.update();

  if (indexButton.isTouched() && indexButton.heldForMs() >= START_HOLD_TIME_MS) {
    indexButton.resetTouchState();
    programStarted = !programStarted;

    if (programStarted) {
      Serial.println("Hold confirmed - starting program");
      initHardware();
      buzzer.playStartSound();
    } else {
      Serial.println("Hold confirmed - ending program");
      buzzer.playEndSound();
      shutdownHardware();
    }
  }
}

// -------------------------------------------------
// Index 0.5s select / exit-browse gesture
// -------------------------------------------------
void checkSelectGesture() {
  if (!indexButton.isTouched()) {
    indexSelectFiredTouch = false;  // reset once finger lifts
    return;
  }

  if (!indexSelectFiredTouch &&
      indexButton.heldForMs() >= SELECT_HOLD_TIME_MS &&
      indexButton.heldForMs() < START_HOLD_TIME_MS) {

    indexSelectFiredTouch = true;
    app.handleIndexAction();
    isSelectPressed = true;
  }
}

// -------------------------------------------------
// Middle -> cycle app state. Ring -> cycle browse target.
// -------------------------------------------------
void routeGestures() {
  if (middleButton.checkHoldConfirmed()) {
    isUpPressed = true;
    app.cycleState();
    app.printAll();
  }

  if (ringButton.checkHoldConfirmed()) {
    isDownPressed = true;
    app.cycleRing();
    app.printAll();
  }
}

// -------------------------------------------------
// SIMULATED model response for Battle/Explorer sub-mode
// switching. Type 'p'/'i'/'n' + Enter in Serial Monitor.
// -------------------------------------------------
void checkSimulatedModelResponse() {
  if (app.current != STATE_EXPLORER && app.current != STATE_BATTLE) {
    while (Serial.available()) {
      Serial.read();
    }
    return;
  }
  if (Serial.available()) {
    char c = Serial.read();
    if (c == 'p' || c == 'P' || c == 'i' || c == 'I' || c == 'n' || c == 'N') {
      app.applySimulatedReach(c);
      app.printAll();
    }
  }
}

// -------------------------------------------------
// Debug CSV: IMU,timestamp_ms,ax,ay,az,gx,gy,gz.
// Acceleration is m/s^2; rotation is rad/s. Four decimals match the collector's
// display precision; the transmitted float32 values are not rounded.
void printImuReadings(const sensors_event_t& a, const sensors_event_t& g) {
  Serial.printf("IMU,%lu,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f\n",
                static_cast<unsigned long>(a.timestamp),
                a.acceleration.x, a.acceleration.y, a.acceleration.z,
                g.gyro.x, g.gyro.y, g.gyro.z);
}

// -------------------------------------------------
// Main sensing cycle: MPU6050 motion
// Called by updateHardware() while started and automatic telemetry is enabled.
// -------------------------------------------------
void runSensorCycle() {
  // SensorSampleTask supplies the 50 Hz cadence. Preserve MotionSensor's
  // initialization, SI conversion and internal buffer without changing it.
  if (!motionReady) {
    if (millis() - lastMotionInitAttempt < 1000) return;
    motionReady = motion.begin();
    lastMotionInitAttempt = millis();
    return;
  }

  sensors_event_t a, g, temp;
  motion.read(a, g, temp);   // reads AND buffers internally
  // printImuReadings(a, g);

  // Always read and buffer at 50 Hz. Optional gating uses the unchanged API.
  const uint8_t touchFlags =
      (isSelectPressed ? TELEMETRY_TOUCH_INDEX : 0) |
      (isUpPressed ? TELEMETRY_TOUCH_MIDDLE : 0) |
      (isDownPressed ? TELEMETRY_TOUCH_RING : 0);
  if ((!DETECT_MOTION || touchFlags || motion.hasSignificantChange()) &&
      enqueueMotionSample(a, g, touchFlags, telemetryStreamStart, DETECT_MOTION)) {
    motion.markTransmitted();
    telemetryStreamStart = false;
  }
}
// -------------------------------------------------
// Hardware init / shutdown, called on index 5s toggle
// -------------------------------------------------
void initHardware() {
  telemetryStreamStart = true;

  motor.stopAll();
  indexMotorRunning = middleMotorRunning = ringMotorRunning = false;

  motionReady = motion.begin();
  lastMotionInitAttempt = millis();

  Serial.println("Program has started!");
}

void shutdownHardware() {
  motionReady = false;
  motor.stopAll();
  indexMotorRunning = middleMotorRunning = ringMotorRunning = false;
  indexMotorTrigger = middleMotorTrigger = ringMotorTrigger = false;

  led.off();
  buzzer.off();

  middleButton.resetTouchState();
  ringButton.resetTouchState();
  indexButton.resetTouchState();
  indexSelectFiredTouch = false;

  app.reset();

  isUpPressed = isDownPressed = isSelectPressed = false;

  Serial.println("Program stopped. Hardware shut down. All state reset to initial.");
}
