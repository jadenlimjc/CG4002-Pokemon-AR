// Copied from hardware/main_oop/main_oop.ino. Hardware objects and lifecycle
// stay here; main.ino schedules updateHardware() and transports sensor events.
// OFF: send every 100 Hz reading. ON: send only significant motion changes.
constexpr bool DETECT_MOTION = false;

#include "config.h"
#include "touchButton.h"
#include "singleHoldButton.h"
#include "vibrationMotor.h"
#include "rgbLed.h"
#include "passiveBuzzer.h"
#include "hallSensor.h"
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
HallSensor hall(HALL_DIGITAL_PIN, HALL_ANALOG_PIN);
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

bool isHallTriggered = false; //hall sensor state, sent to ultra96
bool hallFirstCheck = true;
bool prevHallState = false;
unsigned long hallLastPrintTime = 0;

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
void IRAM_ATTR onHallChangeIsr()  { 
  hall.onIsr(); 
}

void handleIndexHoldToggle();
void checkSelectGesture();
void routeGestures();
void checkSimulatedModelResponse();
void runSensorCycle();
void checkHallStatusChange();
void initHardware();
void shutdownHardware();

// =====================================================
// setup / loop
// =====================================================
void setupHardware() {

  Serial.println("Touch and hold index finger for 5 seconds to start...");

  indexButton.begin(onIndexTouchIsr);
  middleButton.begin(onMiddleTouchIsr);
  ringButton.begin(onRingTouchIsr);

  motor.begin();
  motor.registerRunningFlag(&indexMotorRunning);
  motor.registerRunningFlag(&middleMotorRunning);
  motor.registerRunningFlag(&ringMotorRunning);

  buzzer.begin();
  buzzer.off();

  led.begin();
  led.off();

}

void updateHardware(bool telemetryEnabled, bool haptic) {
  if (!telemetryEnabled) telemetryStreamStart = true;
  static bool hapticPlaying = false;
  static unsigned long hapticStartedAt = 0;
  const bool wasStarted = programStarted;
  handleIndexHoldToggle();
  if (programStarted != wasStarted || !telemetryEnabled) {
    if (hapticPlaying) buzzer.off();
    hapticPlaying = false;
  }
  if (haptic && telemetryEnabled && programStarted) {
    buzzer.on(BUZZER_PWM_FREQUENCY);
    hapticStartedAt = millis();
    hapticPlaying = true;
  }
  if (hapticPlaying && millis() - hapticStartedAt >= 200) {
    buzzer.off();
    hapticPlaying = false;
  }

  if (programStarted) {
    middleButton.update();
    ringButton.update();

    checkSelectGesture();
    routeGestures();
    checkSimulatedModelResponse();
    // checkHallStatusChange();

    motor.checkTrigger(middleMotorTrigger, middleMotorRunning, middleMotorStart, "Middle finger");
    motor.checkTrigger(ringMotorTrigger,   ringMotorRunning,   ringMotorStart,   "Ring finger");
    motor.checkTrigger(indexMotorTrigger,  indexMotorRunning,  indexMotorStart,  "Index finger");

    if (telemetryEnabled) runSensorCycle();

    isUpPressed = false;
    isDownPressed = false;
    isSelectPressed = false;

  } else {
    middleButton.resetTouchState();
    ringButton.resetTouchState();
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
  if (app.current != STATE_BATTLE && app.current != STATE_EXPLORER) {
    indexSelectFiredTouch = false;
    return;
  }

  if (!indexButton.isTouched()) {
    indexSelectFiredTouch = false;  // reset once finger lifts
    return;
  }

  if (!indexSelectFiredTouch &&
      indexButton.heldForMs() >= SELECT_HOLD_TIME_MS &&
      indexButton.heldForMs() < START_HOLD_TIME_MS) {

    bool indexSelectTouched = app.handleIndexAction();
    if (indexSelectTouched) {
      indexSelectFiredTouch = true;
      indexMotorTrigger = true;
      if (app.current == STATE_BATTLE) {
        isSelectPressed = true;
      }
    }
  }
}

// -------------------------------------------------
// Middle -> cycle app state. Ring -> cycle browse target.
// -------------------------------------------------
void routeGestures() {
  if (middleButton.checkHoldConfirmed()) {
    middleMotorTrigger = true;
    app.cycleState();
    app.printAll();
  }

  if (ringButton.checkHoldConfirmed()) {
    ringMotorTrigger = true;
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
// Main sensing cycle: MPU6050 motion + hall sensor
// Called by updateHardware() while started and automatic telemetry is enabled.
// -------------------------------------------------
void runSensorCycle() {
  // SensorSampleTask supplies the 100 Hz cadence. Preserve MotionSensor's
  // initialization, SI conversion and internal buffer without changing it.
  if (!motionReady) {
    if (millis() - lastMotionInitAttempt < 1000) return;
    motionReady = motion.begin();
    lastMotionInitAttempt = millis();
    return;
  }

  sensors_event_t a, g, temp;
  motion.read(a, g, temp);   // reads AND buffers internally

  // Always read and buffer at 100 Hz. Optional gating uses the unchanged API.
  const uint16_t touchMask =
      (indexButton.isTouched() ? TELEMETRY_TOUCH_INDEX : 0) |
      (middleButton.isTouched() ? TELEMETRY_TOUCH_MIDDLE : 0) |
      (ringButton.isTouched() ? TELEMETRY_TOUCH_RING : 0);
  if ((!DETECT_MOTION || motion.hasSignificantChange()) &&
      enqueueMotionSample(a, g, touchMask, telemetryStreamStart, DETECT_MOTION)) {
    motion.markTransmitted();
    telemetryStreamStart = false;
  }


  bool aboveThreshold = (a.acceleration.z > ACCEL_THRESHOLD);
  if (aboveThreshold) {
    // buzzer.on(BUZZER_PWM_FREQUENCY);
    led.green();
    // Serial.println("STATUS: TRIGGERED - Buzzer ON, LED GREEN");
  } else {
    // buzzer.off();
    led.red();
    // Serial.println("STATUS: NORMAL - Buzzer OFF, LED RED");
  }


  // Serial.println("----------------------------------------------------------------");
  // hall.printStatus();
  // Serial.println("----------------------------------------------------------------");
  // app.printAll();
  // Serial.println("----------------------------------------------------------------");
}


void checkHallStatusChange() {
  if (indexMotorRunning || middleMotorRunning || ringMotorRunning) {
    return; // skip hall check while motor is running - avoid false trigger from motor's own field/noise
  }

  const unsigned long MIN_PRINT_INTERVAL_MS = 200;

  isHallTriggered = (hall.state() == 0);

  bool stateChanged = (prevHallState != isHallTriggered);

  if ((hallFirstCheck || stateChanged) &&
      (millis() - hallLastPrintTime >= MIN_PRINT_INTERVAL_MS)) {
    hall.printStatus();
    hallLastPrintTime = millis();
    hallFirstCheck = false;
  }

  prevHallState = isHallTriggered;
}
// -------------------------------------------------
// Hardware init / shutdown, called on index 5s toggle
// -------------------------------------------------
void initHardware() {
  telemetryStreamStart = true;

  motor.stopAll();
  indexMotorRunning = middleMotorRunning = ringMotorRunning = false;

  // hall.begin(onHallChangeIsr);
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
  // hall.end();

  middleButton.resetTouchState();
  ringButton.resetTouchState();
  indexButton.resetTouchState();
  indexSelectFiredTouch = false;

  app.reset();

  isUpPressed = isDownPressed = isSelectPressed = false;
  // isHallTriggered = false;
  // hallFirstCheck = true;
  // prevHallState = false;

  Serial.println("Program stopped. Hardware shut down. All state reset to initial.");
}
