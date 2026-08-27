#include <Arduino.h>

void TaskNetwork(void *pvParameters) {
    for (;;) {
        // FreeRTOS network task logic here
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

void setup() {
    Serial.begin(115200);

    // Pin task to Core 0 (leaving Core 1 free for standard loops)
    xTaskCreatePinnedToCore(
        TaskNetwork, "NetworkTask", 4096, NULL, 1, NULL, 0
    );
}

void loop() {
    // Standard Arduino loop (runs on Core 1 by default)
    vTaskDelay(pdMS_TO_TICKS(10));
}

