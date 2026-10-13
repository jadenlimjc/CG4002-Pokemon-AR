#pragma once

#include <Arduino.h>
#include <Adafruit_MPU6050.h>

namespace hardware {
// Change this one value to set BOTH the task cadence and MPU6050 output rate.
// Examples: 50 Hz -> 20 ms / divider 19; 100 Hz -> 10 ms / divider 9.
constexpr uint16_t SAMPLE_RATE_HZ = 100;

constexpr uint8_t I2C_SDA_PIN = SDA; // FireBeetle GPIO21
constexpr uint8_t I2C_SCL_PIN = SCL; // FireBeetle GPIO22
constexpr uint8_t IMU_ADDRESS = MPU6050_I2CADDR_DEFAULT;
constexpr uint32_t I2C_CLOCK_HZ = 400000;
constexpr uint16_t I2C_TIMEOUT_MS = 5;
constexpr uint32_t SENSOR_RETRY_MS = 1000;

// Match hardware/main_oop/motionSensor.cpp. Range changes must also be reflected
// in Ultra96's ACCEL_RANGE_G/GYRO_RANGE_DPS (the wire packet has no range field).
constexpr mpu6050_accel_range_t ACCEL_RANGE = MPU6050_RANGE_8_G;
constexpr mpu6050_gyro_range_t GYRO_RANGE = MPU6050_RANGE_500_DEG;
constexpr mpu6050_bandwidth_t FILTER_BANDWIDTH = MPU6050_BAND_21_HZ;

constexpr uint8_t TOUCH_INDEX_PIN = T3;  // GPIO15
constexpr uint8_t TOUCH_MIDDLE_PIN = T5; // GPIO12
constexpr uint8_t TOUCH_RING_PIN = T6;   // GPIO14
// TOUCH_V1: touched when the reading falls BELOW the threshold.
constexpr uint16_t TOUCH_INDEX_THRESHOLD = 350;
constexpr uint16_t TOUCH_MIDDLE_THRESHOLD = 350;
constexpr uint16_t TOUCH_RING_THRESHOLD = 350;

constexpr uint8_t BUZZER_PIN = D7; // GPIO13, passive buzzer
constexpr uint32_t BUZZER_PWM_FREQUENCY_HZ = 1500;
constexpr uint8_t BUZZER_PWM_RESOLUTION_BITS = 8;
constexpr uint16_t BEEP_FREQUENCY_HZ = 1500;
constexpr uint16_t BEEP_DURATION_MS = 200;
constexpr uint16_t BUZZER_SERVICE_INTERVAL_MS = 10;

constexpr uint32_t SENSOR_TASK_STACK_BYTES = 4096;
constexpr UBaseType_t SENSOR_TASK_PRIORITY = 3;
constexpr BaseType_t SENSOR_TASK_CORE = 0;

// Device/protocol constraints, not tuning knobs. DLPF settings 1..6 use a
// 1 kHz source clock; SMPLRT_DIV is an unsigned eight-bit register.
constexpr uint16_t IMU_FILTERED_CLOCK_HZ = 1000;
constexpr uint16_t IMU_MAX_DIVIDER = UINT8_MAX;
constexpr uint16_t MILLISECONDS_PER_SECOND = 1000;
static_assert(FILTER_BANDWIDTH >= MPU6050_BAND_184_HZ &&
              FILTER_BANDWIDTH <= MPU6050_BAND_5_HZ,
              "Choose a 5..184 Hz MPU6050 filter for the 1 kHz divider clock");
static_assert(SAMPLE_RATE_HZ > 0 && SAMPLE_RATE_HZ <= IMU_FILTERED_CLOCK_HZ,
              "Sample rate must be positive and at most the MPU6050 clock");
static_assert(SAMPLE_RATE_HZ && IMU_FILTERED_CLOCK_HZ % SAMPLE_RATE_HZ == 0,
              "Sample rate must divide the MPU6050 1 kHz clock exactly");
static_assert(SAMPLE_RATE_HZ && configTICK_RATE_HZ % SAMPLE_RATE_HZ == 0,
              "Sample rate must divide the FreeRTOS tick rate exactly");
constexpr uint16_t IMU_SAMPLE_DIVIDER = SAMPLE_RATE_HZ ?
    IMU_FILTERED_CLOCK_HZ / SAMPLE_RATE_HZ - 1 : 0;
static_assert(IMU_SAMPLE_DIVIDER <= IMU_MAX_DIVIDER, "MPU6050 divider exceeds eight bits");
constexpr TickType_t SAMPLE_PERIOD_TICKS = SAMPLE_RATE_HZ ? configTICK_RATE_HZ / SAMPLE_RATE_HZ : 0;
constexpr uint16_t SAMPLE_PERIOD_MS = SAMPLE_RATE_HZ ? MILLISECONDS_PER_SECOND / SAMPLE_RATE_HZ : 0;
constexpr TickType_t BUZZER_SERVICE_TICKS = pdMS_TO_TICKS(BUZZER_SERVICE_INTERVAL_MS);
static_assert(BUZZER_SERVICE_TICKS > 0, "Buzzer service interval must be at least one tick");
} // namespace hardware
