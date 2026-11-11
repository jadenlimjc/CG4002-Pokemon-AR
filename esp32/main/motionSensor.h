#ifndef MOTION_SENSOR_H
#define MOTION_SENSOR_H

#include <Arduino.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>

class MotionSensor {
  public:
    bool begin();
    void read(sensors_event_t &a, sensors_event_t &g, sensors_event_t &temp);

  private:
    Adafruit_MPU6050 mpu_;
};

#endif
