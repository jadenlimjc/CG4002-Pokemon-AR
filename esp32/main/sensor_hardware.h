#pragma once

#include "hardware_config.h"
#include "telemetry_packet.h"

// SensorSampleTask is the sole owner. Inputs have no gesture/application state.
class SensorHardware {
public:
    bool begin();
    // False on a failed/short I2C read; packet remains untouched on failure.
    bool read(TelemetryPacket& packet);

private:
    Adafruit_MPU6050 motion;
};
