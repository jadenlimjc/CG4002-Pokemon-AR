#ifndef MOTION_SENSOR_H
#define MOTION_SENSOR_H

#include <Arduino.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>

// =====================================================
// Tunable thresholds 
// =====================================================
#define IMU_BUFFER_SIZE          20      // ~10s of history at 500ms/sample
#define IMU_ACCEL_DELTA_THRESHOLD 1.5f   // m/s^2
#define IMU_GYRO_DELTA_THRESHOLD  0.5f   // rad/s

struct ImuSample {
  float ax, ay, az;
  float gx, gy, gz;
  unsigned long timestamp;
};

class MotionSensor {
  public:
    bool begin();

    // Reads raw sensor event AND pushes a snapshot into the ring buffer.
    // &  updates the internal "significant change" flag.
    void read(sensors_event_t &a, sensors_event_t &g, sensors_event_t &temp);

    // True if the most recently read() sample differs from the
    // last-transmitted sample by more than the configured thresholds.
    bool hasSignificantChange() const;

    // Call after a sample is transmitted/used so future
    // comparisons are measured against this new baseline.
    void markTransmitted();

    // Access to the ring buffer,
    const ImuSample& bufferAt(int indexFromOldest) const;
    int bufferCount() const { return count_; }
    const ImuSample& latest() const;

    void printLatest() const;
    void reset();


  private:
    Adafruit_MPU6050 mpu_;

    ImuSample buffer_[IMU_BUFFER_SIZE];
    int head_ = 0;
    int count_ = 0;

    ImuSample lastTransmitted_ = {0, 0, 0, 0, 0, 0, 0};
    bool hasTransmittedOnce_ = false;
    bool significantChange_ = false;

    void pushSample(const ImuSample &s);
    bool isSignificantChange(const ImuSample &current, const ImuSample &prev) const;
};

#endif