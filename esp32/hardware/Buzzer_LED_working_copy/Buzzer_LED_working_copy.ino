// =================================================
// FireBeetle ESP32 + MPU6050 + KY-016 + Passive Buzzer
// Arduino-ESP32 3.x LEDC PWM API
// KY-016 is common cathode
// No interrupt: MPU6050 is read by polling in loop()
// =================================================

#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <Wire.h>

Adafruit_MPU6050 mpu;

// -------------------------------------------------
// KY-016 RGB LED pins
// -------------------------------------------------
#define RED_PIN   D2
#define GREEN_PIN D3
#define BLUE_PIN  D4

// -------------------------------------------------
// Passive buzzer pin
// -------------------------------------------------
#define BUZZER_PIN D7

// -------------------------------------------------
// PWM settings
// -------------------------------------------------

// KY-016 RGB PWM settings
#define LED_PWM_FREQUENCY 5000
#define LED_PWM_RESOLUTION 8

// Passive buzzer PWM settings
#define BUZZER_PWM_FREQUENCY 2000
#define BUZZER_PWM_RESOLUTION 8

// -------------------------------------------------
// MPU6050 threshold
// -------------------------------------------------

// MPU6050 acceleration values are in m/s^2.
// Change this after looking at Serial Monitor values.
const float ACCEL_THRESHOLD = 5.0;

// -------------------------------------------------
// RGB LED function
// KY-016 is common cathode:
// 0 = channel off
// 255 = full brightness
// -------------------------------------------------
void setColor(uint8_t red, uint8_t green, uint8_t blue) {
  ledcWrite(RED_PIN, red);
  ledcWrite(GREEN_PIN, green);
  ledcWrite(BLUE_PIN, blue);
}

void ledOff() {
  setColor(0, 0, 0);
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
// Setup
// -------------------------------------------------
void setup(void) {
  Serial.begin(115200);

  // Optional on some boards, but safe for Serial Monitor startup.
  while (!Serial) {
    delay(10);
  }

  Serial.println("FireBeetle ESP32 + MPU6050 + KY-016 + Buzzer");

  // -------------------------------------------------
  // Set up PWM for RGB LED and passive buzzer
  // -------------------------------------------------

  bool redAttached = ledcAttach(
    RED_PIN,
    LED_PWM_FREQUENCY,
    LED_PWM_RESOLUTION
  );

  bool greenAttached = ledcAttach(
    GREEN_PIN,
    LED_PWM_FREQUENCY,
    LED_PWM_RESOLUTION
  );

  bool blueAttached = ledcAttach(
    BLUE_PIN,
    LED_PWM_FREQUENCY,
    LED_PWM_RESOLUTION
  );

  bool buzzerAttached = ledcAttach(
    BUZZER_PIN,
    BUZZER_PWM_FREQUENCY,
    BUZZER_PWM_RESOLUTION
  );

  Serial.print("Red PWM: ");
  Serial.println(redAttached ? "OK" : "FAILED");

  Serial.print("Green PWM: ");
  Serial.println(greenAttached ? "OK" : "FAILED");

  Serial.print("Blue PWM: ");
  Serial.println(blueAttached ? "OK" : "FAILED");

  Serial.print("Buzzer PWM: ");
  Serial.println(buzzerAttached ? "OK" : "FAILED");

  // Initial output state.
  blueLedOn();
  buzzerOff();

  // -------------------------------------------------
  // Initialise MPU6050
  // -------------------------------------------------

  if (!mpu.begin()) {
    Serial.println("Failed to find MPU6050 chip");
    Serial.println("Check VCC, GND, SDA, SCL, and I2C address.");

    // Error indication: red LED, buzzer off.
    setColor(255, 0, 0);
    buzzerOff();

    
  }

  Serial.println("MPU6050 Found!");

  // -------------------------------------------------
  // MPU6050 configuration
  // -------------------------------------------------

  mpu.setAccelerometerRange(MPU6050_RANGE_8_G);

  Serial.print("Accelerometer range set to: ");
  switch (mpu.getAccelerometerRange()) {
    case MPU6050_RANGE_2_G:
      Serial.println("+-2G");
      break;

    case MPU6050_RANGE_4_G:
      Serial.println("+-4G");
      break;

    case MPU6050_RANGE_8_G:
      Serial.println("+-8G");
      break;

    case MPU6050_RANGE_16_G:
      Serial.println("+-16G");
      break;
  }

  mpu.setGyroRange(MPU6050_RANGE_500_DEG);

  Serial.print("Gyro range set to: ");
  switch (mpu.getGyroRange()) {
    case MPU6050_RANGE_250_DEG:
      Serial.println("+-250 deg/s");
      break;

    case MPU6050_RANGE_500_DEG:
      Serial.println("+-500 deg/s");
      break;

    case MPU6050_RANGE_1000_DEG:
      Serial.println("+-1000 deg/s");
      break;

    case MPU6050_RANGE_2000_DEG:
      Serial.println("+-2000 deg/s");
      break;
  }

  mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);

  Serial.print("Filter bandwidth set to: ");
  switch (mpu.getFilterBandwidth()) {
    case MPU6050_BAND_260_HZ:
      Serial.println("260 Hz");
      break;

    case MPU6050_BAND_184_HZ:
      Serial.println("184 Hz");
      break;

    case MPU6050_BAND_94_HZ:
      Serial.println("94 Hz");
      break;

    case MPU6050_BAND_44_HZ:
      Serial.println("44 Hz");
      break;

    case MPU6050_BAND_21_HZ:
      Serial.println("21 Hz");
      break;

    case MPU6050_BAND_10_HZ:
      Serial.println("10 Hz");
      break;

    case MPU6050_BAND_5_HZ:
      Serial.println("5 Hz");
      break;
  }

  Serial.println("");
  delay(100);
}

// -------------------------------------------------
// Main loop: polling only, no interrupt
// -------------------------------------------------
void loop() {
  // Get current MPU6050 sensor readings.
  sensors_event_t a, g, temp;
  mpu.getEvent(&a, &g, &temp);

  // Print acceleration.
  Serial.print("Acceleration X: ");
  Serial.print(a.acceleration.x, 2);

  Serial.print(", Y: ");
  Serial.print(a.acceleration.y, 2);

  Serial.print(", Z: ");
  Serial.print(a.acceleration.z, 2);

  Serial.println(" m/s^2");

  // Print gyro rotation.
  Serial.print("Rotation X: ");
  Serial.print(g.gyro.x, 2);

  Serial.print(", Y: ");
  Serial.print(g.gyro.y, 2);

  Serial.print(", Z: ");
  Serial.print(g.gyro.z, 2);

  Serial.println(" rad/s");

  // Print temperature.
  Serial.print("Temperature: ");
  Serial.print(temp.temperature, 2);
  Serial.println(" degC");

  // -------------------------------------------------
  // Motion condition
  // -------------------------------------------------

  // Change .z to .x or .y if your desired gesture
  // moves a different MPU6050 axis.
  float selectedAcceleration = a.acceleration.z;

  bool aboveThreshold = (selectedAcceleration > ACCEL_THRESHOLD);

  if (aboveThreshold) {
    // Triggered: buzzer sounds, RGB LED fully off.
    ledOff();
    buzzerOn(BUZZER_PWM_FREQUENCY);

    Serial.println("STATUS: TRIGGERED - Buzzer ON, LED OFF");
  } else {
    // Normal: buzzer silent, blue LED on.
    buzzerOff();
    blueLedOn();

    Serial.println("STATUS: NORMAL - Buzzer OFF, Blue LED ON");
  }

  Serial.println("");
  delay(500);
}