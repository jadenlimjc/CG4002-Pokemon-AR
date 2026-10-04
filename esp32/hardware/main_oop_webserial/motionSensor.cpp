#include "motionSensor.h"
#include "DualPrint.h"

bool MotionSensor::begin() {
  if (!mpu_.begin()) {
    dbg.println("Failed to find MPU6050 chip");
    dbg.println("Check VCC, GND, SDA, SCL, and I2C address.");
    return false;
  }
  dbg.println("MPU6050 Found!");

  mpu_.setAccelerometerRange(MPU6050_RANGE_8_G);
  mpu_.setGyroRange(MPU6050_RANGE_500_DEG);
  mpu_.setFilterBandwidth(MPU6050_BAND_21_HZ);

  head_ = 0;
  count_ = 0;
  hasTransmittedOnce_ = false;
  significantChange_ = false;

  return true;
}

void MotionSensor::read(sensors_event_t &a, sensors_event_t &g, sensors_event_t &temp) {
  mpu_.getEvent(&a, &g, &temp);

  ImuSample sample = {
    a.acceleration.x, a.acceleration.y, a.acceleration.z,
    g.gyro.x, g.gyro.y, g.gyro.z,
    millis()
  };

  pushSample(sample);

  if (!hasTransmittedOnce_) {
    significantChange_ = true;
  } else {
    significantChange_ = isSignificantChange(sample, lastTransmitted_);
  }

}

bool MotionSensor::hasSignificantChange() const {
  return significantChange_;
}

void MotionSensor::markTransmitted() {
  if (count_ == 0) return;
  lastTransmitted_ = latest();
  hasTransmittedOnce_ = true;
  significantChange_ = false;
}

void MotionSensor::pushSample(const ImuSample &s) {
  buffer_[head_] = s;
  head_ = (head_ + 1) % IMU_BUFFER_SIZE;
  if (count_ < IMU_BUFFER_SIZE) {
    count_++;
  }
}

void MotionSensor::reset() {
  head_ = 0;
  count_ = 0;
  hasTransmittedOnce_ = false;
  significantChange_ = false;
}

bool MotionSensor::isSignificantChange(const ImuSample &current, const ImuSample &prev) const {
  float dax = fabs(current.ax - prev.ax);
  float day = fabs(current.ay - prev.ay);
  float daz = fabs(current.az - prev.az);
  float dgx = fabs(current.gx - prev.gx);
  float dgy = fabs(current.gy - prev.gy);
  float dgz = fabs(current.gz - prev.gz);

  return (dax > IMU_ACCEL_DELTA_THRESHOLD || day > IMU_ACCEL_DELTA_THRESHOLD || daz > IMU_ACCEL_DELTA_THRESHOLD ||
          dgx > IMU_GYRO_DELTA_THRESHOLD  || dgy > IMU_GYRO_DELTA_THRESHOLD  || dgz > IMU_GYRO_DELTA_THRESHOLD);
}

const ImuSample& MotionSensor::latest() const {
  int lastIndex = (head_ - 1 + IMU_BUFFER_SIZE) % IMU_BUFFER_SIZE;
  return buffer_[lastIndex];
}

const ImuSample& MotionSensor::bufferAt(int indexFromOldest) const {
  int oldestIndex = (count_ < IMU_BUFFER_SIZE) ? 0 : head_;
  int realIndex = (oldestIndex + indexFromOldest) % IMU_BUFFER_SIZE;
  return buffer_[realIndex];
}

void MotionSensor::printLatest() const {
  const ImuSample &s = latest();

  dbg.print("Acceleration X: "); dbg.print(s.ax, 2);
  dbg.print(", Y: "); dbg.print(s.ay, 2);
  dbg.print(", Z: "); dbg.print(s.az, 2);
  dbg.println(" m/s^2");

  dbg.print("Rotation X: "); dbg.print(s.gx, 2);
  dbg.print(", Y: "); dbg.print(s.gy, 2);
  dbg.print(", Z: "); dbg.print(s.gz, 2);
  dbg.println(" rad/s");
}