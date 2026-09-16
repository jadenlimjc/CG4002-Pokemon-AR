#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>

#include "esp_eap_client.h"
#include "esp_wifi.h"
#include "esp_system.h"

#include "libssh_esp32.h"
#include "ssh_client.h"
#include "secrets.h"
#include "telemetry_packet.h"

// ==========================================
// CONFIGURATION
// ==========================================

// Stable per-board identity. All boards run the same firmware.
char model_id[13];
char mqtt_client_id[24];
char topic_telemetry[64];
char topic_status[64];
char topic_ping[64];
char topic_pong[64];
char topic_config[64];
char topic_haptic[64];

void initialiseMqttIdentity() {
    snprintf(model_id, sizeof(model_id), "%012llx",
             static_cast<unsigned long long>(ESP.getEfuseMac()));
    snprintf(mqtt_client_id, sizeof(mqtt_client_id), "firebeetle-%s", model_id);
    snprintf(topic_telemetry, sizeof(topic_telemetry), "esp32/%s/telemetry", model_id);
    snprintf(topic_status, sizeof(topic_status), "esp32/%s/status", model_id);
    snprintf(topic_ping, sizeof(topic_ping), "esp32/%s/ping", model_id);
    snprintf(topic_pong, sizeof(topic_pong), "esp32/%s/pong", model_id);
    snprintf(topic_config, sizeof(topic_config), "esp32/%s/config", model_id);
    snprintf(topic_haptic, sizeof(topic_haptic), "esp32/%s/haptic/cmd", model_id);
    Serial.printf("[BOOT] Model ID: %s | MQTT client: %s\n", model_id, mqtt_client_id);
}

// MQTT / SSH forwarding destination
char mqtt_server[128] = "makerslab-fpga-38.ddns.comp.nus.edu.sg";
uint16_t mqtt_port = 1883;
// Broker inactivity timeout is 1.5x this interval (~4.5 s).
// Measured from its last received MQTT packet, not from physical power loss.
constexpr uint16_t MQTT_KEEPALIVE_SECONDS = 3;

// ==========================================
// Global state
// ==========================================

uint8_t mqtt_connection_failures = 0;
char last_failed_server[128] = "";
uint16_t last_failed_port = 0;

// ==========================================
// Queue & Task Handles
// ==========================================

QueueHandle_t telemetryQueue = NULL;
const uint8_t QUEUE_MAX_SIZE = 20;

// ==========================================
// MQTT / SSH client
// ==========================================

SSHForwardClient sshClient;
PubSubClient client(sshClient);

// ==========================================
// Forward declarations
// ==========================================

void connectWiFi();
void connectMQTT();

void SensorSampleTask(void* pvParameters);
void NetworkTask(void* pvParameters);

void mqttCallback(char* topic, byte* payload, unsigned int length);

// ==========================================
// SETUP
// ==========================================

void setup() {
    Serial.begin(115200);

    // Give serial monitor time to attach.
    delay(1000);

    Serial.println();
    Serial.println("==========================================");
    Serial.println("             ESP32 TELEMETRY");
    Serial.println("==========================================");

    // Print reset information immediately after boot.
    esp_reset_reason_t reason = esp_reset_reason();
    Serial.printf("[BOOT] Reset reason: %d\n", reason);
    Serial.printf("[BOOT] Free heap: %u bytes\n", ESP.getFreeHeap());

    // --------------------------------------
    // Initialise libssh
    // --------------------------------------

    libssh_begin();
    Serial.println("[BOOT] libssh initialized.");

    // --------------------------------------
    // Create telemetry queue
    // --------------------------------------

    telemetryQueue = xQueueCreate(QUEUE_MAX_SIZE, sizeof(TelemetryPacket));

    if (telemetryQueue == NULL) {
        Serial.println("[ERROR] Failed to create telemetry queue!");

        while (true) {
            delay(1000);
        }
    }

    Serial.println("[BOOT] Telemetry queue created.");

    // --------------------------------------
    // Initialise MQTT client
    // --------------------------------------

    initialiseMqttIdentity();
    // Includes MQTT headers/topics and incoming configuration commands.
    if (!client.setBufferSize(1024)) {
        Serial.println("[ERROR] Failed to allocate MQTT packet buffer!");
        while (true) {
            delay(1000);
        }
    }
    client.setServer(mqtt_server, mqtt_port);
    client.setKeepAlive(MQTT_KEEPALIVE_SECONDS);

    Serial.printf("[BOOT] MQTT destination: %s:%u\n", mqtt_server, mqtt_port);

    // --------------------------------------
    // Sensor task
    // --------------------------------------

    BaseType_t sensor_result = xTaskCreatePinnedToCore(
        SensorSampleTask,
        "SensorSample",
        4096,
        NULL,
        3,
        NULL,
        0
    );

    if (sensor_result != pdPASS) {
        Serial.println("[ERROR] Failed to create SensorSample task!");
    }

    // --------------------------------------
    // Network task
    // --------------------------------------

    BaseType_t network_result = xTaskCreate(
        NetworkTask,
        "NetworkTask",
        16384,
        NULL,
        2,
        NULL
    );

    if (network_result != pdPASS) {
        Serial.println("[ERROR] Failed to create NetworkTask!");
    }

    Serial.println("[BOOT] Tasks started.");
}

// ==========================================
// LOOP
// ==========================================

void loop() {
    // All useful work is handled by FreeRTOS tasks.
    vTaskDelay(pdMS_TO_TICKS(1000));
}

// ==========================================
// SENSOR SAMPLING TASK
// CORE 0
// ==========================================

void SensorSampleTask(void* pvParameters) {
    TickType_t xLastWakeTime = xTaskGetTickCount();

    const TickType_t xFrequency = pdMS_TO_TICKS(10); // 100 Hz

    uint32_t current_index = 0;

    Serial.println("[SensorSample] Task started on Core 0.");

    for (;;) {
        // Maintain 100 Hz sampling period.
        vTaskDelayUntil(&xLastWakeTime, xFrequency);

        TelemetryPacket packet;

        packet.sample_index = current_index++;
        packet.timestamp_ms = millis();

        // TODO:
        // Replace these mock values with actual
        // I2C / ADC sensor reads.

        packet.accel_x = random(-32768, 32767);
        packet.accel_y = random(-32768, 32767);
        packet.accel_z = random(-32768, 32767);
        packet.gyro_x = random(-32768, 32767);
        packet.gyro_y = random(-32768, 32767);
        packet.gyro_z = random(-32768, 32767);
        packet.hall_raw = random(0, 4095);

        // Bit 0 = local hall trigger.
        uint8_t local_haptic_trigger = (packet.hall_raw > 2500) ? 1 : 0;
        packet.flags = local_haptic_trigger & 0x01;
        packet.crc32 = telemetryCrc32(
            reinterpret_cast<const uint8_t*>(&packet), offsetof(TelemetryPacket, crc32)
        );

        // ----------------------------------
        // Push into queue
        // ----------------------------------
        //
        // If full, discard the oldest sample
        // and insert the newest one.
        //

        if (xQueueSend(telemetryQueue, &packet, 0) == errQUEUE_FULL) {
            TelemetryPacket discarded;

            if (xQueueReceive(telemetryQueue, &discarded, 0) == pdTRUE) {
                xQueueSend(telemetryQueue, &packet, 0);
            }
        }
    }
}

// ==========================================
// NETWORK TASK
// CORE 1
// ==========================================

void NetworkTask(void* pvParameters) {
    Serial.println("[NetworkTask] Task started on Core 1.");
    Serial.printf("[NetworkTask] Free heap before Wi-Fi: %u bytes\n", ESP.getFreeHeap());

    TelemetryPacket packet;

    // --------------------------------------
    // Initial Wi-Fi connection
    // --------------------------------------

    connectWiFi();

    // --------------------------------------
    // SSH TEST CONNECTION
    // --------------------------------------

    if (WiFi.status() == WL_CONNECTED) {
        Serial.println("[NetworkTask] Opening SSH forwarding connection...");

        if (sshClient.connect(mqtt_server, mqtt_port)) {
            Serial.println("[NetworkTask] SSH forwarding connection established!");
            Serial.printf("[NetworkTask] Connected to %s:%u\n", mqtt_server, mqtt_port);
        } else {
            Serial.println("[NetworkTask] SSH forwarding connection failed.");
        }
    }

    // --------------------------------------
    // Main network loop
    // --------------------------------------

    for (;;) {
        // ----------------------------------
        // Wi-Fi
        // ----------------------------------

        if (WiFi.status() != WL_CONNECTED) {
            Serial.println("[NetworkTask] Wi-Fi disconnected.");
            connectWiFi();
        }

        // ----------------------------------
        // MQTT
        // ----------------------------------

        if (WiFi.status() == WL_CONNECTED && !client.connected()) {
            connectMQTT();
        }

        client.loop();

        // ----------------------------------
        // MQTT telemetry
        // ----------------------------------

        if (xQueueReceive(telemetryQueue, &packet, pdMS_TO_TICKS(5)) == pdTRUE) {
            if (WiFi.status() == WL_CONNECTED && client.connected()) {
                const uint8_t* payload = reinterpret_cast<const uint8_t*>(&packet);
                bool success = client.publish(topic_telemetry, payload, sizeof(TelemetryPacket));

                if (!success) {
                    Serial.println("[NetworkTask] MQTT publish failed.");
                }
            }
        }

        // ----------------------------------
        // SERIAL -> SSH
        // ----------------------------------

        // if (sshClient.connected() && Serial.available() > 0) {
        //     char message[256];
        //     size_t length = Serial.readBytesUntil('\n', message, sizeof(message) - 1);
        //     message[length] = '\0';

        //     // Remove trailing carriage return
        //     // when using CRLF line endings.
        //     if (length > 0 && message[length - 1] == '\r') {
        //         message[length - 1] = '\0';
        //         length--;
        //     }

        //     if (length > 0) {
        //         Serial.printf("[TEST] Sending: %s\n", message);
        //         sshClient.write(reinterpret_cast<const uint8_t*>( message), length);

        //         // Send newline too, so nc can
        //         // process the line immediately.
        //         const uint8_t newline = '\n';
        //         sshClient.write(&newline, 1);
        //     }
        // }

        // ----------------------------------
        // SSH -> SERIAL
        // ----------------------------------

        // if (sshClient.connected() && sshClient.available() > 0) {
        //     uint8_t buffer[256];
        //     int length = sshClient.read( buffer, sizeof(buffer) - 1);

        //     if (length > 0) {
        //         buffer[length] = '\0';
        //         Serial.printf("[TEST] Received: %s", reinterpret_cast<char*>(buffer));
        //     }
        // }

        // ----------------------------------
        // Yield
        // ----------------------------------

        vTaskDelay(
            pdMS_TO_TICKS(1)
        );
    }
}

// ==========================================
// WI-FI CONNECTION
// ==========================================

void connectWiFi() {
    Serial.println();
    Serial.println("[NetworkTask] ===============================");
    Serial.printf("[NetworkTask] Connecting to Wi-Fi SSID: %s\n", WIFI_SSID);
    Serial.printf("[NetworkTask] Free heap: %u bytes\n", ESP.getFreeHeap());

    // --------------------------------------
    // Reset existing Wi-Fi state
    // --------------------------------------

    WiFi.disconnect(true);
    vTaskDelay(pdMS_TO_TICKS(100));
    WiFi.mode(WIFI_STA);

    // --------------------------------------
    // Configure WPA2 Enterprise
    // --------------------------------------

    Serial.println("[NetworkTask] Configuring WPA2-Enterprise...");

    esp_err_t err;
    err = esp_eap_client_set_identity(
        (uint8_t*)WIFI_USER,
        strlen(WIFI_USER)
    );

    Serial.printf("[NetworkTask] EAP identity: 0x%x\n", err);

    err = esp_eap_client_set_username(
        (uint8_t*)WIFI_USER,
        strlen(WIFI_USER)
    );

    Serial.printf("[NetworkTask] EAP username: 0x%x\n", err);

    err = esp_eap_client_set_password(
        (uint8_t*)WIFI_PASSWORD,
        strlen(WIFI_PASSWORD)
    );

    Serial.printf("[NetworkTask] EAP password: 0x%x\n", err);

    err = esp_wifi_sta_enterprise_enable();

    Serial.printf("[NetworkTask] EAP enterprise enable: 0x%x\n", err);

    // --------------------------------------
    // Start connection
    // --------------------------------------

    Serial.println("[NetworkTask] Calling WiFi.begin()...");

    WiFi.begin(WIFI_SSID);

    uint8_t retries = 0;

    // --------------------------------------
    // Wait for connection
    // --------------------------------------

    while (WiFi.status() != WL_CONNECTED && retries < 20) {
        vTaskDelay(pdMS_TO_TICKS(500));
        Serial.printf("[NetworkTask] Wi-Fi status: %d | attempt %u/20\n", WiFi.status(), retries + 1);
        retries++;
    }

    // --------------------------------------
    // Result
    // --------------------------------------

    if (WiFi.status() == WL_CONNECTED) {
        Serial.println();
        Serial.println("[NetworkTask] *** Wi-Fi Connected ***");
        Serial.printf("[NetworkTask] IP: %s\n", WiFi.localIP().toString().c_str());
        Serial.printf("[NetworkTask] RSSI: %d dBm\n", WiFi.RSSI());
        Serial.printf("[NetworkTask] Free heap: %u bytes\n", ESP.getFreeHeap());
    } else {
        Serial.println();
        Serial.println("[NetworkTask] Wi-Fi connection timed out.");
        Serial.printf("[NetworkTask] Final Wi-Fi status: %d\n", WiFi.status());
        Serial.println("[NetworkTask] Will retry.");
    }
}

// ==========================================
// MQTT CONNECTION
// ==========================================

void connectMQTT() {
    uint8_t retries = 0;

    while (!client.connected() && retries < 3) {
        Serial.printf("[NetworkTask] Connecting to broker at %s:%u...\n", mqtt_server, mqtt_port);

        // ----------------------------------
        // Last Will
        // ----------------------------------

        const char* lwt_payload = "{\"state\":\"offline\"}";
        uint8_t lwt_qos = 1;
        bool lwt_retain = true;

        // ----------------------------------
        // MQTT connection
        // ----------------------------------

        if (client.connect(mqtt_client_id, MQTT_USER, MQTT_PASSWORD, topic_status, lwt_qos, lwt_retain, lwt_payload)) {
            Serial.println("[NetworkTask] Connected to MQTT broker successfully!");

            client.setCallback(mqttCallback);

            // --------------------------------
            // Online status
            // --------------------------------

            String online_payload = "{\"state\":\"online\",\"rssi\":" + String(WiFi.RSSI()) + "}";
            client.publish(topic_status, online_payload.c_str(), true);
            mqtt_connection_failures = 0;

            client.subscribe(topic_ping);
            client.subscribe(topic_config);
            client.subscribe(topic_haptic);
            // Inference results are consumed by downstream applications.
        } else {
            Serial.printf("[NetworkTask] MQTT connection failed. " "RC state: %d\n", client.state());
            Serial.println("[NetworkTask] Retrying in 1.5 seconds...");

            vTaskDelay(pdMS_TO_TICKS(1500));

            retries++;
            mqtt_connection_failures++;
        }
    }
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
    if (strcmp(topic, topic_ping) == 0) {
        uint32_t current_time = millis();
        // Send the 4-byte time back immediately
        client.publish(topic_pong, (uint8_t*)&current_time, sizeof(current_time));
        return;
    }

    char message[length + 1];
    memcpy(message, payload, length);
    message[length] = '\0';

    if (strcmp(topic, topic_config) == 0) {
        Serial.printf("[MQTT Rx] Topic: %s | Config Payload: %s\n", topic, message);
    }
    else if (strcmp(topic, topic_haptic) == 0) {
        Serial.printf("[MQTT Rx] Topic: %s | Haptic Command Received: %s (Simulating motor trigger)\n", topic, message);
    }
    else {
        Serial.printf("[MQTT Rx] Topic: %s | Raw Payload: %s\n", topic, message);
    }
}
