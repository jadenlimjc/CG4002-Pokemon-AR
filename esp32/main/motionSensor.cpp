#include "motionSensor.h"

bool MotionSensor::begin() {
  if (!mpu_.begin()) {
    Serial.println("Failed to find MPU6050 chip");
    Serial.println("Check VCC, GND, SDA, SCL, and I2C address.");
    return false;
  }
  Serial.println("MPU6050 Found!");

  mpu_.setAccelerometerRange(MPU6050_RANGE_8_G);
  mpu_.setGyroRange(MPU6050_RANGE_500_DEG);
  mpu_.setFilterBandwidth(MPU6050_BAND_21_HZ);

  return true;
}

void MotionSensor::read(sensors_event_t &a, sensors_event_t &g, sensors_event_t &temp) {
  mpu_.getEvent(&a, &g, &temp);
}
