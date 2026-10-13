#include "sensor_hardware.h"
#include <Wire.h>

namespace {
// MPU6050 register layout: accel XYZ, temperature, gyro XYZ; big-endian words.
enum MotionWord : size_t { ACCEL_X, ACCEL_Y, ACCEL_Z, TEMPERATURE, GYRO_X, GYRO_Y, GYRO_Z, WORD_COUNT };
constexpr size_t WORD_BYTES = sizeof(int16_t);
constexpr size_t SAMPLE_BYTES = WORD_COUNT * WORD_BYTES;
constexpr uint8_t BITS_PER_BYTE = 8;
}

bool SensorHardware::begin() {
    if (!Wire.begin(hardware::I2C_SDA_PIN, hardware::I2C_SCL_PIN, hardware::I2C_CLOCK_HZ)) return false;
    Wire.setTimeOut(hardware::I2C_TIMEOUT_MS);
    if (!motion.begin(hardware::IMU_ADDRESS, &Wire)) return false;

    motion.setAccelerometerRange(hardware::ACCEL_RANGE);
    motion.setGyroRange(hardware::GYRO_RANGE);
    motion.setFilterBandwidth(hardware::FILTER_BANDWIDTH);
    motion.setSampleRateDivisor(hardware::IMU_SAMPLE_DIVIDER);
    if (motion.getAccelerometerRange() != hardware::ACCEL_RANGE ||
        motion.getGyroRange() != hardware::GYRO_RANGE ||
        motion.getFilterBandwidth() != hardware::FILTER_BANDWIDTH ||
        motion.getSampleRateDivisor() != hardware::IMU_SAMPLE_DIVIDER) return false;

    // Initialise pads before the first scheduled read.
    touchRead(hardware::TOUCH_INDEX_PIN);
    touchRead(hardware::TOUCH_MIDDLE_PIN);
    touchRead(hardware::TOUCH_RING_PIN);
    return true;
}

bool SensorHardware::read(TelemetryPacket& packet) {
    // Native int16 counts fit the existing packet. getEvent() returns SI floats
    // and does not propagate failed register reads, so read the burst directly.
    Wire.beginTransmission(hardware::IMU_ADDRESS);
    Wire.write(MPU6050_ACCEL_OUT);
    if (Wire.endTransmission(false) != 0) return false;
    if (Wire.requestFrom(hardware::IMU_ADDRESS, SAMPLE_BYTES, true) != SAMPLE_BYTES) {
        while (Wire.available()) Wire.read();
        return false;
    }
    uint8_t bytes[SAMPLE_BYTES];
    for (size_t i = 0; i < SAMPLE_BYTES; ++i) bytes[i] = Wire.read();
    auto axis = [&bytes](MotionWord word) -> int16_t {
        const size_t offset = word * WORD_BYTES;
        return static_cast<int16_t>((uint16_t(bytes[offset]) << BITS_PER_BYTE) | bytes[offset + 1]);
    };
    packet.accel_x = axis(ACCEL_X);
    packet.accel_y = axis(ACCEL_Y);
    packet.accel_z = axis(ACCEL_Z);
    packet.gyro_x = axis(GYRO_X);
    packet.gyro_y = axis(GYRO_Y);
    packet.gyro_z = axis(GYRO_Z);

    // Poll both presses and releases; below-threshold interrupts may not fire
    // when a finger lifts. Encode each finger as a separate bit.
    packet.touch_mask =
        (touchRead(hardware::TOUCH_INDEX_PIN) < hardware::TOUCH_INDEX_THRESHOLD ? TELEMETRY_TOUCH_INDEX : 0) |
        (touchRead(hardware::TOUCH_MIDDLE_PIN) < hardware::TOUCH_MIDDLE_THRESHOLD ? TELEMETRY_TOUCH_MIDDLE : 0) |
        (touchRead(hardware::TOUCH_RING_PIN) < hardware::TOUCH_RING_THRESHOLD ? TELEMETRY_TOUCH_RING : 0);
    packet.flags = packet.touch_mask ? TELEMETRY_ANY_TOUCH : 0;
    return true;
}
