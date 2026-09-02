#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "secrets.h"

// ==========================================
// CONFIGURATION
// ==========================================
// Shared topics
const char* TOPIC_TELEMETRY = "esp32/telemetry";
// TODO: add haptic topic

const char* KVDB_URL = "http://kvdb.io/" KVDB_BUCKET "/boostrap";
// Mutable, because they will be bootstrapped
char mqtt_server[64] = "0.tcp.ngrok.io";
uint16_t mqtt_port = 1883;

// Self-healing / Stale coordinate tracking variables
char last_failed_server[64] = "";
uint16_t last_failed_port = 0;

// Track consecutive connection failures to trigger re-bootstrapping
uint8_t mqtt_connection_failures = 0;


// ==========================================
// Packet format
// ==========================================
struct __attribute__((packed)) TelemetryPacket {
    uint32_t sample_index; // 4 bytes (Running index of samples)
    int16_t accel_x;       // 2 bytes (Raw IMU register value)
    int16_t accel_y;       // 2 bytes
    int16_t accel_z;       // 2 bytes
    int16_t gyro_x;        // 2 bytes (Raw IMU register value)
    int16_t gyro_y;        // 2 bytes
    int16_t gyro_z;        // 2 bytes
    uint16_t hall_raw;     // 2 bytes (Raw 12-bit ADC reading)
    uint8_t flags;         // 1 byte  (Bit 0 = hall_trigger_digital)
};

// ==========================================
// FREERTOS QUEUE & TASK HANDLES
// ==========================================
QueueHandle_t telemetryQueue = NULL;
const uint8_t QUEUE_MAX_SIZE = 20;

WiFiClient espClient;
PubSubClient client(espClient);

// Forward declarations
void connectWiFi();
void connectMQTT();
bool bootstrapMQTTServer();
void SensorSampleTask(void* pvParameters);
void NetworkTask(void* pvParameters);

// ==========================================
// SETUP & LOOP (ARDUINO CORE 1 ENTRY)
// ==========================================
void setup() {
    Serial.begin(115200);
    delay(1000);
    Serial.println("\n[FireBeetle] Initializing hardware & OS threads...");

    // Create thread-safe FreeRTOS Queue
    telemetryQueue = xQueueCreate(QUEUE_MAX_SIZE, sizeof(TelemetryPacket));
    if (telemetryQueue == NULL) {
        Serial.println("[ERROR] Failed to create telemetry queue!");
        while (1) delay(1000);
    }

    // Initialize PubSubClient
    client.setServer(mqtt_server, mqtt_port);

    // Spawn Core 0 Task: Sensor Sampling (High Priority)
    // Runs at 100 Hz (10 ms period) to record IMU and Hall readings
    xTaskCreatePinnedToCore(
        SensorSampleTask,
        "SensorSample",
        4096,             // Stack size (bytes)
        NULL,             // Parameters
        3,                // High Priority
        NULL,             // Task handle
        0                 // Run on Core 0
    );

    // Spawn Core 1 Task: Network Thread (Medium Priority)
    // Manages connections, drains queue, and publishes data
    xTaskCreatePinnedToCore(
        NetworkTask,
        "NetworkTask",
        4096,             // Stack size (bytes)
        NULL,             // Parameters
        2,                // Medium Priority
        NULL,             // Task handle
        1                 // Run on Core 1
    );
}

void loop() {
    // The standard loop runs on Core 1 by default, but our tasks are pinned and 
    // self-scheduling. We put this thread to sleep to prevent watchdog triggers.
    vTaskDelay(pdMS_TO_TICKS(1000));
}

// ==========================================
// HIGH-PRIORITY SENSOR SAMPLING (CORE 0)
// ==========================================
void SensorSampleTask(void* pvParameters) {
    TickType_t xLastWakeTime = xTaskGetTickCount();
    const TickType_t xFrequency = pdMS_TO_TICKS(10); // 10ms = 100Hz
    uint32_t current_index = 0;

    Serial.println("[SensorSample] Task started on Core 0.");

    for (;;) {
        // Enforce strict 10ms period
        vTaskDelayUntil(&xLastWakeTime, xFrequency);

        // Populate raw telemetry data
        TelemetryPacket packet;
        packet.sample_index = current_index++;

        // TODO: Replace these placeholder mock values with actual I2C / ADC sensor reads:
        packet.accel_x = random(-32768, 32767);
        packet.accel_y = random(-32768, 32767);
        packet.accel_z = random(-32768, 32767);
        packet.gyro_x = random(-32768, 32767);
        packet.gyro_y = random(-32768, 32767);
        packet.gyro_z = random(-32768, 32767);
        packet.hall_raw = random(0, 4095); // 12-bit ADC reading

        // Simple threshold check for digital haptic click indicator flag (bit 0)
        uint8_t local_haptic_trigger = (packet.hall_raw > 2500) ? 1 : 0;
        packet.flags = (local_haptic_trigger & 0x01);

        // Push to queue. If queue is full, drop the oldest sample to avoid backlog
        // and maintain real-time responsiveness
        if (xQueueSend(telemetryQueue, &packet, 0) == errQUEUE_FULL) {
            TelemetryPacket discarded;
            // Drain the oldest packet from the front of the queue
            if (xQueueReceive(telemetryQueue, &discarded, 0) == pdTRUE) {
                // Successfully cleared slot; push fresh real-time sample
                xQueueSend(telemetryQueue, &packet, 0);
            }
        }
    }
}

// ==========================================
// MEDIUM-PRIORITY NETWORK THREAD (CORE 1)
// ==========================================
void NetworkTask(void* pvParameters) {
    TelemetryPacket packet;
    Serial.println("[NetworkTask] Task started on Core 1.");

    // Initial WiFi connection
    connectWiFi();

    // Loop until we successfully resolve dynamic, non-stale MQTT coordinates from KVDB
    bool bootstrapped = false;
    while (!bootstrapped) {
        if (WiFi.status() == WL_CONNECTED) {
            bootstrapped = bootstrapMQTTServer();
        }
        if (!bootstrapped) {
            Serial.println("[NetworkTask] Bootstrapping pending. Retrying in 5 seconds...");
            vTaskDelay(pdMS_TO_TICKS(5000)); // Poll KVDB every 5 seconds until coordinates are published
        }
    }

    // Set dynamic client target server config
    client.setServer(mqtt_server, mqtt_port);

    for (;;) {
        // Maintain WiFi Connection
        if (WiFi.status() != WL_CONNECTED) {
            connectWiFi();
        }

        // Maintain MQTT Connection
        if (WiFi.status() == WL_CONNECTED && !client.connected()) {
            // If connection fails repeatedly, re-bootstrap in case the laptop initiated a new ngrok session
            if (mqtt_connection_failures >= 3) {
                Serial.printf("[NetworkTask] Connection failed to %s:%d. Marking as dead...\n", mqtt_server, mqtt_port);

                // Store dead coordinates to prevent re-acquiring the same stale pair
                strncpy(last_failed_server, mqtt_server, sizeof(last_failed_server) - 1);
                last_failed_server[sizeof(last_failed_server) - 1] = '\0';
                last_failed_port = mqtt_port;

                mqtt_connection_failures = 0; // Reset counter

                // Drop client configuration to force dynamic resolution loop
                Serial.println("[NetworkTask] Re-entering bootstrapping state to poll KVDB for a fresh session...");
                bool re_resolved = false;
                while (!re_resolved) {
                    if (WiFi.status() == WL_CONNECTED) {
                        re_resolved = bootstrapMQTTServer();
                    }
                    if (!re_resolved) {
                        vTaskDelay(pdMS_TO_TICKS(5000)); // Poll KVDB every 5 seconds
                    }
                }

                // Update server config with the fresh resolved endpoints
                client.setServer(mqtt_server, mqtt_port);
            }
            connectMQTT();
        }

        // Keep MQTT Client Loop active for Ping/Pong and subscriptions
        client.loop();

        // Drain Telemetry Queue and Publish over MQTT
        // Block for up to 5ms checking the queue to prevent CPU spinning
        if (xQueueReceive(telemetryQueue, &packet, pdMS_TO_TICKS(5)) == pdTRUE) {
            if (WiFi.status() == WL_CONNECTED && client.connected()) {
                // Cast the struct directly to a raw byte array for zero-overhead binary delivery
                const uint8_t* payload = reinterpret_cast<const uint8_t*>(&packet);
                
                // Publish QoS 0 binary message
                bool success = client.publish(TOPIC_TELEMETRY, payload, sizeof(TelemetryPacket));
                
                if (!success) {
                    Serial.println("[NetworkTask] MQTT publish failed.");
                }
            }
        }

        // yield briefly to let IDLE tasks run and feed watchdogs
        vTaskDelay(pdMS_TO_TICKS(1));
    }
}

// ==========================================
// HELPER FUNCTIONS (WIFI & MQTT MANAGERS)
// ==========================================
void connectWiFi() {
    Serial.printf("[NetworkTask] Connecting to Wi-Fi SSID: %s\n", WIFI_SSID);
    WiFi.disconnect(true); // Reset state
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    uint8_t retries = 0;
    // Attempt connection, timing out after 10 seconds to avoid blocking the thread infinitely
    while (WiFi.status() != WL_CONNECTED && retries < 20) {
        vTaskDelay(pdMS_TO_TICKS(500));
        Serial.print(".");
        retries++;
    }

    if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("\n[NetworkTask] Wi-Fi Connected. IP: %s\n", WiFi.localIP().toString().c_str());
    } else {
        Serial.println("\n[NetworkTask] Wi-Fi connection timed out. Will retry...");
    }
}

bool bootstrapMQTTServer() {
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[Bootstrap] Cannot bootstrap: Wi-Fi not connected.");
        return false;
    }

    WiFiClient httpSecureClient; // Using non-secure WiFiClient for plain HTTP request (very fast, low overhead)
    HTTPClient http;
    
    Serial.print("[Bootstrap] Fetching dynamic ngrok coordinates from KVDB...");
    http.begin(httpSecureClient, KVDB_URL);
    int httpCode = http.GET();

    bool success = false;
    if (httpCode == HTTP_CODE_OK) {
        String payload = http.getString();
        Serial.println(" Success!");
        Serial.printf("[Bootstrap] Received payload: %s\n", payload.c_str());

        // Parse JSON config
        StaticJsonDocument<256> doc;
        DeserializationError error = deserializeJson(doc, payload);

        if (!error) {
            const char* host = doc["host"] | "";
            uint16_t port = doc["port"] | 0;

            // 1. Validate parsed keys
            if (strlen(host) == 0 || port == 0) {
                Serial.println("[Bootstrap] Received empty or offline coordinates. Waiting...");
                success = false;
            }
            // 2. Self-healing stale validation:
            // Check if the coordinates retrieved match the ones that just failed.
            else if (strcmp(host, last_failed_server) == 0 && port == last_failed_port) {
                Serial.printf("[Bootstrap] Warn: Resolved endpoint (%s:%d) matches known dead coordinates. Treating as stale. Polling...\n", host, port);
                success = false;
            } 
            else {
                // Safe copy of validated variables
                strncpy(mqtt_server, host, sizeof(mqtt_server) - 1);
                mqtt_server[sizeof(mqtt_server) - 1] = '\0';
                mqtt_port = port;

                Serial.printf("[Bootstrap] Target broker successfully resolved to a fresh endpoint: %s:%d\n", mqtt_server, mqtt_port);
                success = true;
            }
        } else {
            Serial.printf("[Bootstrap] JSON Deserialization failed: %s\n", error.c_str());
        }
    } else if (httpCode == HTTP_CODE_NOT_FOUND) {
        // HTTP 404 is returned if the key has been cleanly deleted on laptop exit.
        Serial.println(" Offline! (KVDB key does not exist - 404).");
    } else {
        Serial.printf(" Failed. HTTP Code: %d (Error: %s)\n", httpCode, http.errorToString(httpCode).c_str());
    }
    http.end();
    return success;
}

void connectMQTT() {
    uint8_t retries = 0;
    while (!client.connected() && retries < 3) {
        Serial.printf("[NetworkTask] Connecting to broker at %s:%d...\n", MQTT_SERVER, MQTT_PORT);
        
        // Set a unique Client ID to avoid disconnect loops
        // String client_id = "ESP32_Glove_" + String(WiFi.macAddress());
        String client_id = "ESP32";

        // Connect with credentials. Keep-alive is 15 seconds
        // Set up Last Will and Testament (LWT) for automatic offline state tracking
        const char* lwt_topic = "glove/status";
        const char* lwt_payload = "{\"state\":\"offline\"}";
        uint8_t lwt_qos = 1;
        bool lwt_retain = true;

        if (client.connect(client_id.c_str(), MQTT_USER, MQTT_PASSWORD, lwt_topic, lwt_qos, lwt_retain, lwt_payload)) {
            Serial.println("[NetworkTask] Connected to MQTT broker successfully!");
            
            // Overwrite LWT with explicit online state
            String online_payload = "{\"state\":\"online\",\"rssi\":" + String(WiFi.RSSI()) + "}";
            client.publish("glove/status", online_payload.c_str(), true);

            // Reset connection failure counter and clean dead coordinates tracking upon successful login
            mqtt_connection_failures = 0;
            last_failed_server[0] = '\0';
            last_failed_port = 0;

            // Subscribe to configuration/haptic topics if needed in the future
            client.subscribe("glove/config");
            client.subscribe("glove/haptic/cmd");
        } else {
            Serial.printf("[NetworkTask] Connection failed. RC state: %d. Retrying in 1.5 seconds...\n", client.state());
            vTaskDelay(pdMS_TO_TICKS(1500));
            retries++;
            mqtt_connection_failures++;
        }
    }
}
