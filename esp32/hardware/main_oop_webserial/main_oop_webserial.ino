#include <WiFi.h>
#include <AsyncTCP.h>
#include <ESPAsyncWebServer.h>
#include <WebSerial.h>

#include "config.h"
#include "touchButton.h"
#include "singleHoldButton.h"
#include "vibrationMotor.h"
#include "rgbLed.h"
#include "passiveBuzzer.h"
#include "motionSensor.h"
#include "appStateMachine.h"
#include "DualPrint.h"


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

// WebSerial: AP + async web server
AsyncWebServer server(80);
static const char* WEBSERIAL_AP_NAME = "GestureWearable";

// Global dual-output logger: writes to BOTH Serial and WebSerial.
DualPrint dbg(Serial, WebSerial);

bool programStarted = false;

bool indexMotorTrigger = false;
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

bool buzzerBeeping = false;
unsigned long buzzerBeepStart = 0;
const unsigned long BUZZER_BEEP_DURATION_MS = 200;

// =====================================================
// Free-function ISRs 
// =====================================================
void IRAM_ATTR onIndexTouchIsr()  { indexButton.onIsr(); }
void IRAM_ATTR onMiddleTouchIsr() { middleButton.onIsr(); }
void IRAM_ATTR onRingTouchIsr()   { ringButton.onIsr(); }


void handleIndexHoldToggle();
void checkSelectGesture();
void routeGestures();
void checkSimulatedModelResponse();
void runSensorCycle();
void initHardware();
void shutdownHardware();
void setupWiFiAp();
void setupWebSerial();
void updateWebSerialStatusLed();
void checkBuzzerBeep();


// =====================================================
// Wi-Fi AP setup
// =====================================================
void setupWiFiAp() {
  WiFi.softAP(WEBSERIAL_AP_NAME);
  dbg.print("WebSerial AP IP: ");
  dbg.println(WiFi.softAPIP().toString());
}


// =====================================================
// WebSerial message handling + server setup
// =====================================================
void setupWebSerial() {
  WebSerial.onMessage([](const String& msg) {
  if (!programStarted) return;

  if (msg.length() == 0) return;
  
  char c = msg[0];

  if (app.current != STATE_EXPLORER && app.current != STATE_BATTLE) {
    WebSerial.println("Ignored: not in Explorer/Battle state");
    return;
  }

  if (c == 'p' || c == 'P' || c == 'i' || c == 'I' || c == 'n' || c == 'N') {
    if (!buzzerBeeping) {
      buzzer.on(BUZZER_PWM_FREQUENCY);
      buzzerBeepStart = millis();
      buzzerBeeping = true;
    }

    app.applySimulatedReach(c);
    app.printAll();
    WebSerial.printf("Received command: %c\n", c);

  } else {
  WebSerial.printf("Ignored: unrecognized command '%c'\n", c);
  }


  });
  
  WebSerial.begin(&server);
  WebSerial.setBuffer(100);

  server.onNotFound([](AsyncWebServerRequest* request) {
    request->redirect("/webserial");
  });
  server.begin();
}


// =====================================================
// setup
// =====================================================
void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("Touch and hold index finger for 5 seconds to start...");

  setupWiFiAp();
  setupWebSerial();
  
  led.begin();
  led.red();

  WebSerial.println("Touch and hold index finger for 5 seconds to start...");

  indexButton.begin(onIndexTouchIsr);
  middleButton.begin(onMiddleTouchIsr);
  ringButton.begin(onRingTouchIsr);

  motor.begin();
  motor.registerRunningFlag(&indexMotorRunning);
  motor.registerRunningFlag(&middleMotorRunning);
  motor.registerRunningFlag(&ringMotorRunning);

  buzzer.begin();
  buzzer.off();

}

// =====================================================
// loop
// =====================================================
void loop() {
  handleIndexHoldToggle();
  updateWebSerialStatusLed();
  checkBuzzerBeep();

  if (programStarted) {
    middleButton.update();
    ringButton.update();

    checkSelectGesture();
    routeGestures();
    checkSimulatedModelResponse();

    motor.checkTrigger(middleMotorTrigger, middleMotorRunning, middleMotorStart, "Middle finger");
    motor.checkTrigger(ringMotorTrigger,   ringMotorRunning,   ringMotorStart,   "Ring finger");
    motor.checkTrigger(indexMotorTrigger,  indexMotorRunning,  indexMotorStart,  "Index finger");

    runSensorCycle();

    isUpPressed = false;
    isDownPressed = false;
    isSelectPressed = false;

  } else {
    middleButton.resetTouchState();
    ringButton.resetTouchState();
  }
}

// -------------------------------------------------
// Check number of devices connected to ESP32 AP
// -------------------------------------------------
void updateWebSerialStatusLed() {
  static unsigned long lastCheck = 0;
  const unsigned long CHECK_INTERVAL_MS = 1000;

  unsigned long now = millis();
  if (now - lastCheck < CHECK_INTERVAL_MS) return;
  lastCheck = now;

  int stationCount = WiFi.softAPgetStationNum();
  if (stationCount > 0) {
    led.green();
  } else {
    led.red();
  }
}

// -------------------------------------------------
// Check buzzer run duration & off buzzer
// -------------------------------------------------
void checkBuzzerBeep() {
  if (buzzerBeeping && millis() - buzzerBeepStart >= BUZZER_BEEP_DURATION_MS) {
    buzzer.off();
    buzzerBeeping = false;
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
      dbg.println("Hold confirmed - starting program");
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
// Index: 0.5s select / exit-browse gesture
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
// Middle -> cycle  state. Ring -> cycle submode.
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
// (WebSerial input is handled separately via onMessage
// in setupWebSerial()).
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
// Main sensing cycle: MPU6050 motion 
// Runs every loop() while programStarted == true.
// -------------------------------------------------
void runSensorCycle() {
  static unsigned long lastSensorRead = 0;
  const unsigned long SENSOR_INTERVAL_MS = 500;

  unsigned long now = millis();
  if (now - lastSensorRead < SENSOR_INTERVAL_MS) return;
  lastSensorRead = now;

  sensors_event_t a, g, temp;
  motion.read(a, g, temp);

  if (motion.hasSignificantChange()) {
    motion.printLatest();   
    motion.markTransmitted();
  }

}



// -------------------------------------------------
// Hardware init / shutdown, called on index 5s toggle
// -------------------------------------------------
void initHardware() {


  motor.stopAll();
  indexMotorRunning = middleMotorRunning = ringMotorRunning = false;

  motion.begin();

  dbg.println("Program has started!");
}


void shutdownHardware() {
  WebSerial.println("Hold confirmed - ending program");

  motor.stopAll();
  indexMotorRunning = middleMotorRunning = ringMotorRunning = false;
  indexMotorTrigger = middleMotorTrigger = ringMotorTrigger = false;

  buzzer.off();
  motion.reset();

  middleButton.resetTouchState();
  ringButton.resetTouchState();
  indexButton.resetTouchState();
  indexSelectFiredTouch = false;

  app.reset();

  isUpPressed = isDownPressed = isSelectPressed = false;

  WebSerial.println("Program stopped. Hardware shut down. All state reset to initial.");
  Serial.println("Program stopped. Hardware shut down. All state reset to initial.");
}