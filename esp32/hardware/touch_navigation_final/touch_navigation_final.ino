#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <Wire.h>

Adafruit_MPU6050 mpu;

// -------------------------------------------------
// KY-016 RGB LED pins
// -------------------------------------------------
#define RED_PIN   D4
#define GREEN_PIN D5
#define BLUE_PIN  D6

// -------------------------------------------------
// KY-024 Hall Effect sensor
// -------------------------------------------------
#define hall_analog  A2
#define hall_digital D2

// -------------------------------------------------
// Passive buzzer pin
// -------------------------------------------------
#define BUZZER_PIN D7

// -------------------------------------------------
// Vibration motor pin
// -------------------------------------------------
#define vibration_motor D3

// -------------------------------------------------
// Touch sensor pins
// FireBeetle ESP32 (DFR0478) - original ESP32, TOUCH_V1
// -------------------------------------------------
const int TOUCH_INDEX  = T3;
const int TOUCH_MIDDLE = T5;
const int TOUCH_RING   = T6;

const int TOUCH_THRESHOLD_INDEX  = 450;
const int TOUCH_THRESHOLD_MIDDLE = 450;
const int TOUCH_THRESHOLD_RING   = 450;

const unsigned long START_HOLD_TIME_MS  = 5000;  // index: hold to start/stop
const unsigned long SELECT_HOLD_TIME_MS = 500;   // index: hold to select (Battle only)
const unsigned long TOGGLE_HOLD_TIME_MS = 600;   // middle/ring: single hold, meaning depends on state

// KY-016 RGB PWM settings
#define LED_PWM_FREQUENCY  5000
#define LED_PWM_RESOLUTION 8

// Passive buzzer PWM settings
#define BUZZER_PWM_FREQUENCY  1500
#define BUZZER_PWM_RESOLUTION 8

// MPU6050 acceleration values are in m/s^2.
const float ACCEL_THRESHOLD = 5.0;

// -------------------------------------------------
// Global state
// -------------------------------------------------

// ---- Index: 5s hold-to-toggle start/end, 0.5s hold-to-select ----
volatile bool indexIsrFlag = false;
bool indexTouchedState = false;
unsigned long indexTouchStartMillis = 0;
bool programStarted = false;
bool indexSelectFiredThisTouch = false;

// ---- Middle: single hold, meaning depends on currentState ----
volatile bool middleIsrFlag = false;
bool middleTouchedState = false;
unsigned long middleTouchStartMillis = 0;
bool middleHoldConfirmed = false;
bool middleHoldFiredThisTouch = false;   // locks out re-fire until release

// ---- Ring: single hold, meaning depends on currentState ----
volatile bool ringIsrFlag = false;
bool ringTouchedState = false;
unsigned long ringTouchStartMillis = 0;
bool ringHoldConfirmed = false;
bool ringHoldFiredThisTouch = false;

// ---- Vibration motor ----
const unsigned long MOTOR_RUN_TIME_MS = 500;
bool motorRunningMiddle = false;
bool motorRunningRing = false;
bool motorRunningIndex = false;

unsigned long motorStartMillisMiddle = 0;
unsigned long motorStartMillisRing = 0;
unsigned long motorStartMillisIndex = 0;

bool middleMotorTrigger = false;   // one-shot trigger consumed by checkMotorTrigger
bool ringMotorTrigger = false;
bool indexMotorTrigger = false;



unsigned long motorPulseStartMillis = 0;
bool motorPhysicallyOn = false;

// ---- Hall effect sensor ----
volatile int hallState = 1;

// -------------------------------------------------
// Model-facing flags
// -------------------------------------------------
bool isUpPressed = false;
bool isDownPressed = false;
bool isSelectPressed = false;

// -------------------------------------------------
// App state machine
// -------------------------------------------------
enum AppState {
  STATE_EXPLORER,
  STATE_BATTLE,
  STATE_MENU
};

// -------------------------------------------------
// Both Explorer and Battle now share the same 3-value
// sub-mode enum, each with its own independent variable.
// -------------------------------------------------
enum BrowseSubMode {
  BROWSE_NORMAL,
  BROWSE_POKEMON,
  BROWSE_ITEM
};

BrowseSubMode battleSubMode   = BROWSE_NORMAL;   // Battle's own sub-mode
BrowseSubMode explorerSubMode = BROWSE_NORMAL;   // Explorer's own sub-mode - now has a normal mode too

AppState currentState = STATE_EXPLORER;
int menuOptionIndex = 0;
const int MENU_OPTION_COUNT = 3;

int battleMoveIndex = 0;
int battlePokemonIndex = 0;
int battleItemIndex = 0;
int explorerNormalOptionIndex = 0;   // placeholder: whatever "normal Explorer" cycles through

const int MOVE_COUNT = 4;
const int POKEMON_COUNT = 6;
const int ITEM_COUNT = 4;
const int EXPLORER_NORMAL_OPTION_COUNT = 3;   // placeholder count

// -------------------------------------------------
// Touch ISRs
// -------------------------------------------------
void IRAM_ATTR onIndexTouch() {
  indexIsrFlag = true;
}

void IRAM_ATTR onMiddleTouch() {
  middleIsrFlag = true;
}

void IRAM_ATTR onRingTouch() {
  ringIsrFlag = true;
}

// -------------------------------------------------
// Hall Effect sensor interrupt
// -------------------------------------------------
void IRAM_ATTR onHallChange() {
  hallState = digitalRead(hall_digital);
}

// -------------------------------------------------
// RGB LED functions
// KY-016 is common cathode
// -------------------------------------------------
void setColor(uint8_t red, uint8_t green, uint8_t blue) {
  ledcWrite(RED_PIN, red);
  ledcWrite(GREEN_PIN, green);
  ledcWrite(BLUE_PIN, blue);
}

void ledOff() {
  setColor(0, 0, 0);
}

void greenLedOn() {
  setColor(0, 255, 0);
}

void redLedOn() {
  setColor(255, 0, 0);
}

void blueLedOn() {
  setColor(0, 0, 255);
}

// -------------------------------------------------
// Passive buzzer functions
// -------------------------------------------------
void buzzerOn(uint32_t frequency) {
  ledcWriteTone(BUZZER_PIN, frequency);
}

void buzzerOff() {
  ledcWriteTone(BUZZER_PIN, 0);
}

// -------------------------------------------------
// setup / loop
// -------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(1000); // give time to bring up serial monitor

  Serial.println("Touch and hold index finger for 5 seconds to start...");

  touchAttachInterrupt(TOUCH_INDEX, onIndexTouch, TOUCH_THRESHOLD_INDEX);
  touchAttachInterrupt(TOUCH_MIDDLE, onMiddleTouch, TOUCH_THRESHOLD_MIDDLE);
  touchAttachInterrupt(TOUCH_RING, onRingTouch, TOUCH_THRESHOLD_RING);

  pinMode(vibration_motor, OUTPUT);
  digitalWrite(vibration_motor, LOW);
}

void loop() {
  handleIndexHoldToggle();

  if (programStarted) {
    handleMiddleHoldToggle();
    handleRingHoldToggle();

    checkSelectGesture();   // index 0.5s hold, Battle only

    routeGestures();        // middle -> cycle state; ring -> meaning depends on currentState

    checkSimulatedModelResponse();

    // Runs every loop so the motor's internal ON->OFF timer can progress.
    checkMotorTrigger(middleMotorTrigger, motorRunningMiddle, motorStartMillisMiddle, "Middle finger");
    checkMotorTrigger(ringMotorTrigger,   motorRunningRing,   motorStartMillisRing,   "Ring finger");
    checkMotorTrigger(indexMotorTrigger, motorRunningIndex, motorStartMillisIndex, "Index finger");

    runSensorCycle();

    resetDirectionFlags();      // clear for next detection

  } else {
    // Not running: drop any stale flags from middle/ring so they don't
    // fire the instant the program starts.
    middleIsrFlag = false;
    ringIsrFlag = false;
  }
}

// -------------------------------------------------
// Index: 5s hold-to-toggle start/stop
// -------------------------------------------------
void handleIndexHoldToggle() {
  if (indexIsrFlag) {
    indexIsrFlag = false;
    int rawAtIsr = touchRead(TOUCH_INDEX);
    bool touchedNow = (rawAtIsr < TOUCH_THRESHOLD_INDEX);
    unsigned long now = millis();

    if (touchedNow && !indexTouchedState) {
      indexTouchedState = true;
      indexTouchStartMillis = now;
      indexSelectFiredThisTouch = false;

    } else if (!touchedNow && indexTouchedState) {
      indexTouchedState = false;
      indexSelectFiredThisTouch = false;
      Serial.println("Released before 5s - no state change.");
    }
  }

  if (indexTouchedState && (millis() - indexTouchStartMillis >= START_HOLD_TIME_MS)) {
    indexTouchedState = false;
    programStarted = !programStarted;

    if (programStarted) {
      Serial.println("Hold confirmed - starting program");
      initHardware();
    } else {
      Serial.println("Hold confirmed - ending program");
      shutdownHardware();
    }
  }
}

// -------------------------------------------------
// Index 0.5s select. Confirming a Pokemon or item
// selection automatically returns Battle to normal mode.
// -------------------------------------------------
void checkSelectGesture() {
  if (currentState != STATE_BATTLE && currentState != STATE_EXPLORER) {
    indexSelectFiredThisTouch = false;
    return;
  }

  if (indexTouchedState && !indexSelectFiredThisTouch &&
      (millis() - indexTouchStartMillis >= SELECT_HOLD_TIME_MS) &&
      (millis() - indexTouchStartMillis < START_HOLD_TIME_MS)) {

    // Explorer: index EXITS browsing back to normal mode. No select here.
    if (currentState == STATE_EXPLORER) {
      if (explorerSubMode != BROWSE_NORMAL) {
        indexSelectFiredThisTouch = true;
        indexMotorTrigger = true;
        explorerSubMode = BROWSE_NORMAL;
        Serial.println("Explorer: exiting browse -> back to normal mode");
      }
      return;
    }

    // Battle: existing select/confirm behavior.
    if (battleSubMode != BROWSE_NORMAL) {
      indexSelectFiredThisTouch = true;
      isSelectPressed = true;
      indexMotorTrigger = true;

      switch (battleSubMode) {
        case BROWSE_POKEMON:
          Serial.print("SELECT -> Pokemon ");
          Serial.println(battlePokemonIndex);
          battleSubMode = BROWSE_NORMAL;
          Serial.println("Returning to normal battle mode");
          break;

        case BROWSE_ITEM:
          Serial.print("SELECT -> Item ");
          Serial.println(battleItemIndex);
          battleSubMode = BROWSE_NORMAL;
          Serial.println("Returning to normal battle mode");
          break;

        default:
          break;
      }
    }
  }
}


// -------------------------------------------------
// Middle: hold-to-toggle (single 0.6s hold, always cycles state)
// -------------------------------------------------
void handleMiddleHoldToggle() {
  if (middleIsrFlag) {
    middleIsrFlag = false;
    int rawAtIsr = touchRead(TOUCH_MIDDLE);
    bool touchedNow = (rawAtIsr < TOUCH_THRESHOLD_MIDDLE);
    unsigned long now = millis();

    if (touchedNow && !middleTouchedState) {
      middleTouchedState = true;
      middleTouchStartMillis = now;
      middleHoldConfirmed = false;
      middleHoldFiredThisTouch = false;   // fresh touch, allow one fire

    } else if (!touchedNow && middleTouchedState) {
      middleTouchedState = false;
      middleHoldFiredThisTouch = false;   // released, ready for next touch
    }
  }

  // Fires once per continuous touch only.
  if (middleTouchedState && !middleHoldFiredThisTouch &&
      (millis() - middleTouchStartMillis >= TOGGLE_HOLD_TIME_MS)) {
    middleHoldFiredThisTouch = true;
    middleHoldConfirmed = true;
  }
}

// -------------------------------------------------
// Ring: hold-to-toggle (single 0.6s hold, meaning depends on currentState)
// -------------------------------------------------
void handleRingHoldToggle() {
  if (ringIsrFlag) {
    ringIsrFlag = false;
    int rawAtIsr = touchRead(TOUCH_RING);
    bool touchedNow = (rawAtIsr < TOUCH_THRESHOLD_RING);
    unsigned long now = millis();

    if (touchedNow && !ringTouchedState) {
      ringTouchedState = true;
      ringTouchStartMillis = now;
      ringHoldConfirmed = false;
      ringHoldFiredThisTouch = false;

    } else if (!touchedNow && ringTouchedState) {
      ringTouchedState = false;
      ringHoldFiredThisTouch = false;
    }
  }

  if (ringTouchedState && !ringHoldFiredThisTouch &&
      (millis() - ringTouchStartMillis >= TOGGLE_HOLD_TIME_MS)) {
    ringHoldFiredThisTouch = true;
    ringHoldConfirmed = true;
  }
}


// -------------------------------------------------
// Middle: cycle state. BOTH Explorer and Battle reset
// their own sub-mode to normal on entry now.
// -------------------------------------------------
void handleStateToggle() {
  switch (currentState) {
    case STATE_EXPLORER:
      currentState = STATE_BATTLE;
      battleSubMode = BROWSE_NORMAL;
      Serial.println("State: EXPLORER -> BATTLE");
      break;
    case STATE_BATTLE:
      currentState = STATE_MENU;
      Serial.println("State: BATTLE -> MENU");
      break;
    case STATE_MENU:
      currentState = STATE_EXPLORER;
      explorerSubMode = BROWSE_NORMAL;
      Serial.println("State: MENU -> EXPLORER");
      break;
  }
}

// -------------------------------------------------
// Ring: browsing target depends on currentState AND
// that state's own sub-mode.
// -------------------------------------------------
void routeGestures() {
  if (middleHoldConfirmed) {
    middleHoldConfirmed = false;
    middleMotorTrigger = true;
    handleStateToggle();
  }

  if (ringHoldConfirmed) {
    ringHoldConfirmed = false;
    ringMotorTrigger = true;

    if (currentState == STATE_EXPLORER) {
      switch (explorerSubMode) {
        case BROWSE_NORMAL:
          // PLACEHOLDER: define what ring cycles through in
          // Explorer's default/idle mode - e.g. map markers,
          // nearby NPCs, direction facing, etc.
          explorerNormalOptionIndex = (explorerNormalOptionIndex + 1) % EXPLORER_NORMAL_OPTION_COUNT;
          Serial.print("Explorer (normal): option -> ");
          Serial.println(explorerNormalOptionIndex);
          break;
        case BROWSE_POKEMON:
          battlePokemonIndex = (battlePokemonIndex + 1) % POKEMON_COUNT;
          Serial.print("Explorer (browsing Pokemon, no select): -> ");
          Serial.println(battlePokemonIndex);
          break;
        case BROWSE_ITEM:
          battleItemIndex = (battleItemIndex + 1) % ITEM_COUNT;
          Serial.print("Explorer (browsing Item, no select): -> ");
          Serial.println(battleItemIndex);
          break;
      }

    } else if (currentState == STATE_BATTLE) {
      switch (battleSubMode) {
        case BROWSE_NORMAL:
          battleMoveIndex = (battleMoveIndex + 1) % MOVE_COUNT;
          Serial.print("Battle (normal): Move option -> ");
          Serial.println(battleMoveIndex);
          break;
        case BROWSE_POKEMON:
          battlePokemonIndex = (battlePokemonIndex + 1) % POKEMON_COUNT;
          Serial.print("Battle (Pokemon select): option -> ");
          Serial.println(battlePokemonIndex);
          break;

        case BROWSE_ITEM:
          battleItemIndex = (battleItemIndex + 1) % ITEM_COUNT;
          Serial.print("Battle (Item select): option -> ");
          Serial.println(battleItemIndex);
          break;
      }

    } else if (currentState == STATE_MENU) {
      menuOptionIndex = (menuOptionIndex + 1) % MENU_OPTION_COUNT;
      Serial.print("Menu: settings option -> ");
      Serial.println(menuOptionIndex);
    }
  }
}

// -------------------------------------------------
// SIMULATED model response for Battle sub-mode switching.
// Type 'b' + Enter in Serial Monitor to simulate "back pocket
// reach" (switch to Pokemon select), or 'f' + Enter to simulate
// "front pocket reach" (switch to item select).

// Simulated model response now updates whichever
// state's sub-mode is active - Explorer or Battle -
// and 'n' returns either one back to normal.
// -------------------------------------------------
void checkSimulatedModelResponse() {
  if (currentState != STATE_EXPLORER && currentState != STATE_BATTLE) {
    while (Serial.available()) Serial.read();
    return;
  }

  if (Serial.available()) {
    char c = Serial.read();
    BrowseSubMode &activeSubMode = (currentState == STATE_EXPLORER) ? explorerSubMode : battleSubMode;
    const char* stateLabel = (currentState == STATE_EXPLORER) ? "Explorer" : "Battle";

    if (c == 'b' || c == 'B') {
      activeSubMode = BROWSE_POKEMON;
      Serial.print("[SIMULATED MODEL] back pocket reach -> ");
      Serial.print(stateLabel);
      Serial.println(": Pokemon mode");
    } else if (c == 'f' || c == 'F') {
      activeSubMode = BROWSE_ITEM;
      Serial.print("[SIMULATED MODEL] front pocket reach -> ");
      Serial.print(stateLabel);
      Serial.println(": Item mode");
    } else if (c == 'n' || c == 'N') {
      activeSubMode = BROWSE_NORMAL;
      Serial.print("[SIMULATED MODEL] returning to normal -> ");
      Serial.println(stateLabel);
    }
  }
}

// -------------------------------------------------
// Shared motor-pulse handler for any finger.
// -------------------------------------------------
void checkMotorTrigger(bool &holdConfirmed, bool &running, unsigned long &startMillis, const char* label) {
  if (holdConfirmed && !running) {
    holdConfirmed = false;    // consume the trigger, fires once
    running = true;
    startMillis = millis();

    if (!motorPhysicallyOn) {
      motorPhysicallyOn = true;
      motorPulseStartMillis = millis();
    }

    digitalWrite(vibration_motor, HIGH);
    Serial.print("Vibration motor ON (");
    Serial.print(label);
    Serial.println(")");
  }

  if (running && (millis() - startMillis >= MOTOR_RUN_TIME_MS)) {
    running = false;

    Serial.print("Vibration motor OFF (");
    Serial.print(label);
    Serial.println(")");
    // Only physically drop the pin if the OTHER finger's pulse
    // isn't still active, otherwise this cuts it short.
    if (!motorRunningMiddle && !motorRunningRing && !motorRunningIndex) {
      digitalWrite(vibration_motor, LOW);
      motorPhysicallyOn = false;

      unsigned long totalBuzzDuration = millis() - motorPulseStartMillis;
      Serial.print("Motor fully OFF - continuous buzz lasted ");
      Serial.print(totalBuzzDuration);
      Serial.println(" ms");
    }
  }
}

// -------------------------------------------------
// Reset model-facing flags after they've been transmitted/used
// -------------------------------------------------
void resetDirectionFlags() {
  isUpPressed = false;
  isDownPressed = false;
  isSelectPressed = false;
}

// -------------------------------------------------
// Print states
// -------------------------------------------------
void printCurrentStates(AppState currentState) {
  switch(currentState) {
    case STATE_EXPLORER:    Serial.println("EXPLORER"); break;
    case STATE_BATTLE: Serial.println("BATTLE"); break;
    case STATE_MENU:  Serial.println("MENU"); break;
  }
}

void printSubModeStates(BrowseSubMode subModeState) {
  switch(subModeState) {
    case BROWSE_NORMAL:    Serial.println("NORMAL"); break;
    case BROWSE_POKEMON: Serial.println("BROWSE POKEMON"); break;
    case BROWSE_ITEM:  Serial.println("BROWSE ITEM"); break;
  }
}


// -------------------------------------------------
// Main sensing cycle: MPU6050 motion + hall sensor
// Runs every loop() while programStarted == true.
// -------------------------------------------------
void runSensorCycle() {
  static unsigned long lastSensorRead = 0;
  const unsigned long SENSOR_INTERVAL_MS = 500;

  unsigned long now = millis();
  if (now - lastSensorRead < SENSOR_INTERVAL_MS) {
    return;  // non-blocking pacing, no delay() here
  }
  lastSensorRead = now;

  // Get current MPU6050 sensor readings.
  sensors_event_t a, g, temp;
  mpu.getEvent(&a, &g, &temp);

  Serial.print("Acceleration X: ");
  Serial.print(a.acceleration.x, 2);
  Serial.print(", Y: ");
  Serial.print(a.acceleration.y, 2);
  Serial.print(", Z: ");
  Serial.print(a.acceleration.z, 2);
  Serial.println(" m/s^2");

  Serial.print("Rotation X: ");
  Serial.print(g.gyro.x, 2);
  Serial.print(", Y: ");
  Serial.print(g.gyro.y, 2);
  Serial.print(", Z: ");
  Serial.print(g.gyro.z, 2);
  Serial.println(" rad/s");

  // -------------------------------------------------
  // Motion condition
  // -------------------------------------------------
  float selectedAcceleration = a.acceleration.z;
  bool aboveThreshold = (selectedAcceleration > ACCEL_THRESHOLD);

  if (aboveThreshold) {
    buzzerOn(BUZZER_PWM_FREQUENCY);
    greenLedOn();
    Serial.println("STATUS: TRIGGERED - Buzzer ON, LED GREEN");
  } else {
    buzzerOff();
    redLedOn();
    Serial.println("STATUS: NORMAL - Buzzer OFF, LED RED");
  }

  Serial.println("----------------------------------------------------------------");
  checkHallSensor();
  Serial.println("----------------------------------------------------------------");
  Serial.print("Current State :");
  printCurrentStates(currentState);
  Serial.print("Battle sub mode :");
  printSubModeStates(battleSubMode);
  if (battleSubMode == BROWSE_NORMAL) {
    Serial.print("Battle move index:");
    Serial.println(battleMoveIndex);
  } 
  Serial.print("Explorer sub mode :");
  printSubModeStates(explorerSubMode);
  if (explorerSubMode == BROWSE_NORMAL) {
    Serial.print("Explorer normal browsing index:");
    Serial.println(explorerNormalOptionIndex);
  } 
  Serial.print("Pokemon browsing index:");
  Serial.println(battlePokemonIndex);
  Serial.print("Item browsing index:");
  Serial.println(battleItemIndex);
  Serial.print("Menu browsing index:");
  Serial.println(menuOptionIndex);

  Serial.println("----------------------------------------------------------------");
}

void checkHallSensor() {
  int liveDigital = digitalRead(hall_digital);
  Serial.print("Live digital: ");
  Serial.print(liveDigital);
  Serial.print(" | hallState (ISR): ");
  Serial.println(hallState);

  if (hallState == 0) {
    Serial.println("Magnet NEAR");
  } else {
    Serial.println("Magnet AWAY");
  }
}

// -------------------------------------------------
// Hardware init / shutdown, called on index 5s toggle
// -------------------------------------------------
void initHardware() {
  // -------------------------------------------------
  // Set up PWM for RGB LED and passive buzzer
  // -------------------------------------------------
  bool redAttached    = ledcAttach(RED_PIN,    LED_PWM_FREQUENCY, LED_PWM_RESOLUTION);
  bool greenAttached  = ledcAttach(GREEN_PIN,  LED_PWM_FREQUENCY, LED_PWM_RESOLUTION);
  bool blueAttached   = ledcAttach(BLUE_PIN,   LED_PWM_FREQUENCY, LED_PWM_RESOLUTION);
  bool buzzerAttached = ledcAttach(BUZZER_PIN, BUZZER_PWM_FREQUENCY, BUZZER_PWM_RESOLUTION);

  Serial.print("Red PWM: ");    Serial.println(redAttached    ? "OK" : "FAILED");
  Serial.print("Green PWM: ");  Serial.println(greenAttached  ? "OK" : "FAILED");
  Serial.print("Blue PWM: ");   Serial.println(blueAttached   ? "OK" : "FAILED");
  Serial.print("Buzzer PWM: "); Serial.println(buzzerAttached ? "OK" : "FAILED");

  // Initial output state.
  redLedOn();
  buzzerOff();

  // Vibration motor setup
  pinMode(vibration_motor, OUTPUT);
  digitalWrite(vibration_motor, LOW);
  motorRunningMiddle = false;
  motorRunningRing = false;
  motorRunningIndex = false;

  // Hall effect sensor setup
  pinMode(hall_digital, INPUT);
  pinMode(hall_analog, INPUT);
  attachInterrupt(digitalPinToInterrupt(hall_digital), onHallChange, CHANGE);

  // -------------------------------------------------
  // Initialise MPU6050
  // -------------------------------------------------
  if (!mpu.begin()) {
    Serial.println("Failed to find MPU6050 chip");
    Serial.println("Check VCC, GND, SDA, SCL, and I2C address.");
    // Error indication: red LED, buzzer off.
    setColor(255, 0, 0);
    buzzerOff();
  } else {
    Serial.println("MPU6050 Found!");
  }

  // -------------------------------------------------
  // MPU6050 configuration
  // -------------------------------------------------
  mpu.setAccelerometerRange(MPU6050_RANGE_8_G);
  Serial.print("Accelerometer range set to: ");
  switch (mpu.getAccelerometerRange()) {
    case MPU6050_RANGE_2_G:  Serial.println("+-2G");  break;
    case MPU6050_RANGE_4_G:  Serial.println("+-4G");  break;
    case MPU6050_RANGE_8_G:  Serial.println("+-8G");  break;
    case MPU6050_RANGE_16_G: Serial.println("+-16G"); break;
  }

  mpu.setGyroRange(MPU6050_RANGE_500_DEG);
  Serial.print("Gyro range set to: ");
  switch (mpu.getGyroRange()) {
    case MPU6050_RANGE_250_DEG:  Serial.println("+-250 deg/s");  break;
    case MPU6050_RANGE_500_DEG:  Serial.println("+-500 deg/s");  break;
    case MPU6050_RANGE_1000_DEG: Serial.println("+-1000 deg/s"); break;
    case MPU6050_RANGE_2000_DEG: Serial.println("+-2000 deg/s"); break;
  }

  mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);
  Serial.print("Filter bandwidth set to: ");
  switch (mpu.getFilterBandwidth()) {
    case MPU6050_BAND_260_HZ: Serial.println("260 Hz"); break;
    case MPU6050_BAND_184_HZ: Serial.println("184 Hz"); break;
    case MPU6050_BAND_94_HZ:  Serial.println("94 Hz");  break;
    case MPU6050_BAND_44_HZ:  Serial.println("44 Hz");  break;
    case MPU6050_BAND_21_HZ:  Serial.println("21 Hz");  break;
    case MPU6050_BAND_10_HZ:  Serial.println("10 Hz");  break;
    case MPU6050_BAND_5_HZ:   Serial.println("5 Hz");   break;
  }

  Serial.println("Program has started!");
}

// -------------------------------------------------
// Hardware shutdown - resets ALL stateful globals back
// to their initial values, so restarting the program
// (via index 5s hold) always begins fresh in Explorer/
// normal mode, with no stale data carried over.
// -------------------------------------------------
void shutdownHardware() {
  // Stop motor, clear all pulse-tracking state
  motorRunningMiddle = false;
  motorRunningRing = false;
  motorRunningIndex = false;
  digitalWrite(vibration_motor, LOW);
  motorPhysicallyOn = false;
  motorPulseStartMillis = 0;
  motorStartMillisMiddle = 0;
  motorStartMillisRing = 0;
  motorStartMillisIndex = 0;
  middleMotorTrigger = false;
  ringMotorTrigger = false;
  indexMotorTrigger = false;

  // Turn off LEDs and buzzer
  ledOff();
  buzzerOff();

  // Detach hall interrupt
  detachInterrupt(digitalPinToInterrupt(hall_digital));

  // Reset middle/ring touch + hold state
  middleTouchedState = false;
  middleHoldConfirmed = false;
  middleHoldFiredThisTouch = false;
  ringTouchedState = false;
  ringHoldConfirmed = false;
  ringHoldFiredThisTouch = false;

  // Reset index touch + select state
  indexTouchedState = false;
  indexSelectFiredThisTouch = false;

  // Reset the app state machine back to its initial condition
  currentState = STATE_EXPLORER;
  battleSubMode = BROWSE_NORMAL;
  explorerSubMode = BROWSE_NORMAL;

  // Reset all browse/cycle indices back to their starting positions
  battleMoveIndex = 0;
  battlePokemonIndex = 0;
  battleItemIndex = 0;
  explorerNormalOptionIndex = 0;
  menuOptionIndex = 0;

  // Reset model-facing flags so nothing stale gets sent on next start
  isUpPressed = false;
  isDownPressed = false;
  isSelectPressed = false;

  Serial.println("Program stopped. Hardware shut down. All state reset to initial.");
}
