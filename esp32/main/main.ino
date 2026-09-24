#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <atomic>

#include "esp_eap_client.h"
#include "esp_wifi.h"
#include "esp_system.h"
#include "esp_timer.h"

#include "libssh_esp32.h"
#include "ssh_client.h"
#include "secrets.h"
#include "telemetry_packet.h"
#include "demo_protocol.h"

// ==========================================
// CONFIGURATION
// ==========================================

// Stable per-board identity. All boards run the same firmware.
char model_id[13];
char mqtt_client_id[24];
char topic_telemetry[64];
char topic_status[64];
char topic_ack[64];
char topic_rtt[64];
char topic_config[64];
char topic_haptic[64];
char topic_mode[64], topic_demo_in[64], topic_demo_out[64];
enum DemoMode { AUTO, FILE_MODE, PIPELINE_MODE };
std::atomic<DemoMode> demoMode{AUTO};
const char* modeNames[] = {"auto", "file", "pipeline"};
demo::Receiver demoReceiver; // File storage allocated on demand; NetworkTask owns it.

void initialiseMqttIdentity() {
    snprintf(model_id, sizeof(model_id), "%012llx",
             static_cast<unsigned long long>(ESP.getEfuseMac()));
    snprintf(mqtt_client_id, sizeof(mqtt_client_id), "firebeetle-%s", model_id);
    snprintf(topic_telemetry, sizeof(topic_telemetry), "esp32/%s/telemetry", model_id);
    snprintf(topic_status, sizeof(topic_status), "esp32/%s/status", model_id);
    snprintf(topic_ack, sizeof(topic_ack), "esp32/%s/telemetry_ack", model_id);
    snprintf(topic_rtt, sizeof(topic_rtt), "esp32/%s/rtt", model_id);
    snprintf(topic_config, sizeof(topic_config), "esp32/%s/config", model_id);
    snprintf(topic_haptic, sizeof(topic_haptic), "esp32/%s/haptic/cmd", model_id);
    snprintf(topic_mode, sizeof(topic_mode), "esp32/%s/mode", model_id);
    snprintf(topic_demo_in, sizeof(topic_demo_in), "esp32/%s/demo_in", model_id);
    snprintf(topic_demo_out, sizeof(topic_demo_out), "esp32/%s/demo_out", model_id);
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

// NetworkTask owns all RTT state. No new task, per-packet ACK, or blocking wait.
class TelemetryRtt {
    static constexpr uint64_t SAMPLE_INTERVAL_US = 2000000;
    static constexpr uint64_t ACK_TIMEOUT_US = 15000000;
    static constexpr uint64_t REPORT_INTERVAL_US = 10000000;
    RttReport statistics = {};
    TelemetryAck expected = {};
    uint64_t sentUs = 0, nextSampleUs = 0, lastReportUs = 0;
    bool waiting = false;

public:
    void begin() {
        memset(&statistics, 0, sizeof(statistics));
        memcpy(statistics.magic, "RTT1", 4);
        statistics.session = esp_random();
        waiting = false;
        lastReportUs = esp_timer_get_time();
        nextSampleUs = lastReportUs + SAMPLE_INTERVAL_US;
    }

    uint32_t session() const { return statistics.session; }

    bool prepare(TelemetryPacket& packet) {
        if (waiting || static_cast<uint64_t>(esp_timer_get_time()) < nextSampleUs) return false;
        packet.flags |= TELEMETRY_RTT_REQUEST;
        packet.crc32 = telemetryCrc32(reinterpret_cast<const uint8_t*>(&packet), offsetof(TelemetryPacket, crc32));
        expected = {packet.sample_index, packet.timestamp_ms, packet.crc32};
        // Start immediately before MQTT publish. This measures application RTT,
        // including both transports and U96's ACK callback, not sensor queue time.
        sentUs = esp_timer_get_time();
        nextSampleUs = sentUs + SAMPLE_INTERVAL_US;
        waiting = true;
        return true;
    }

    void publishFailed() {
        waiting = false;
        ++statistics.publish_failures;
    }

    void cancel() {
        if (waiting) ++statistics.cancelled;
        waiting = false;
        nextSampleUs = static_cast<uint64_t>(esp_timer_get_time()) + SAMPLE_INTERVAL_US;
    }

    void acknowledge(const uint8_t* payload, unsigned int length) {
        if (length != sizeof(TelemetryAck)) return;
        TelemetryAck ack;
        memcpy(&ack, payload, sizeof(ack));
        if (!waiting || ack.sample_index != expected.sample_index ||
            ack.timestamp_ms != expected.timestamp_ms || ack.packet_crc32 != expected.packet_crc32) {
            ++statistics.late_acks;
            return;
        }
        const uint64_t elapsed = static_cast<uint64_t>(esp_timer_get_time()) - sentUs;
        waiting = false;
        if (elapsed >= ACK_TIMEOUT_US) {
            ++statistics.timeouts;
            ++statistics.late_acks;
            nextSampleUs = static_cast<uint64_t>(esp_timer_get_time()) + SAMPLE_INTERVAL_US;
            return;
        }
        const uint32_t measured = static_cast<uint32_t>(elapsed);
        ++statistics.samples;
        statistics.total_us += measured;
        if (statistics.samples == 1 || measured < statistics.minimum_us) statistics.minimum_us = measured;
        if (measured > statistics.maximum_us) statistics.maximum_us = measured;
    }

    void tick() {
        const uint64_t now = esp_timer_get_time();
        if (waiting && now - sentUs >= ACK_TIMEOUT_US) {
            waiting = false;
            ++statistics.timeouts;
            nextSampleUs = now + SAMPLE_INTERVAL_US;
        }
        if (now - lastReportUs < REPORT_INTERVAL_US || !client.connected()) return;
        lastReportUs = now; // Even a failed report waits before retrying.
        ++statistics.report_index;
        statistics.pending = waiting ? 1 : 0;
        statistics.crc32 = telemetryCrc32(reinterpret_cast<const uint8_t*>(&statistics), offsetof(RttReport, crc32));
        client.publish(topic_rtt, reinterpret_cast<const uint8_t*>(&statistics), sizeof(statistics));
    }
};
TelemetryRtt telemetryRtt;


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

        if (demoMode.load() != AUTO) continue;

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
        telemetryRtt.tick();

        // ----------------------------------
        // MQTT telemetry
        // ----------------------------------

        if (xQueueReceive(telemetryQueue, &packet, pdMS_TO_TICKS(5)) == pdTRUE) {
            if (demoMode.load() == AUTO && WiFi.status() == WL_CONNECTED && client.connected()) {
                const bool measured = telemetryRtt.prepare(packet);
                const uint8_t* payload = reinterpret_cast<const uint8_t*>(&packet);
                bool success = client.publish(topic_telemetry, payload, sizeof(TelemetryPacket));

                if (!success) {
                    if (measured) telemetryRtt.publishFailed();
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

            telemetryRtt.begin();
            String online_payload = "{\"state\":\"online\",\"rssi\":" + String(WiFi.RSSI()) +
                                    ",\"rtt_session\":" + String(telemetryRtt.session()) + "}";
            client.publish(topic_status, online_payload.c_str(), true);
            mqtt_connection_failures = 0;

            client.subscribe(topic_ack);
            client.subscribe(topic_config);
            client.subscribe(topic_haptic);
            client.subscribe(topic_demo_in);
            demoReceiver.reset();
            client.publish(topic_mode, modeNames[demoMode.load()]);
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

// Manual demonstrations only: keep automatic 100 Hz telemetry off Serial.
void printGesturePacket(const char* direction, const TelemetryPacket& p) {
    Serial.printf("  %s seq=%lu device_ms=%lu CRC=OK (%08lx)\n",
                  direction, (unsigned long)p.sample_index,
                  (unsigned long)p.timestamp_ms, (unsigned long)p.crc32);
    Serial.printf("  accel=(%d,%d,%d) gyro=(%d,%d,%d) hall=%u flags=0x%02x\n",
                  p.accel_x, p.accel_y, p.accel_z, p.gyro_x, p.gyro_y,
                  p.gyro_z, p.hall_raw, p.flags);
}

void printDemoReceipt(const uint8_t* request, const uint8_t* response) {
    demo::Header h;
    memcpy(&h, response, sizeof(h));
    const uint8_t* data = response + sizeof(h);
    if (h.kind == demo::FILE_ECHO) {
        Serial.printf("[FILE RX] board=%s id=%08lx stored=%lu/%lu offset=%lu CRC=OK\n",
                      model_id, (unsigned long)h.id, (unsigned long)(h.offset + h.length),
                      (unsigned long)h.total, (unsigned long)h.offset);
        Serial.println("--- stored chunk contents (non-text bytes escaped as \\xNN) ---");
        for (uint16_t i = 0; i < h.length; ++i) {
            uint8_t value = data[i];
            if (value == '\n' || (value >= 32 && value <= 126 && value != '\\')) {
                Serial.write(value);
            } else if (value == '\\') {
                Serial.print("\\\\");
            } else {
                Serial.printf("\\x%02x", value);
            }
        }
        Serial.println("\n--- end stored chunk ---");
    } else if (h.kind == demo::FILE_RECEIPT) {
        uint32_t crc;
        memcpy(&crc, data, sizeof(crc));
        Serial.printf("[FILE COMPLETE] board=%s id=%08lx bytes=%lu full-file CRC32=%08lx\n",
                      model_id, (unsigned long)h.id, (unsigned long)h.total, (unsigned long)crc);
    } else if (h.kind == demo::PIPELINE_REPLY) {
        TelemetryPacket before, after;
        memcpy(&before, request + sizeof(h), sizeof(before));
        memcpy(&after, data, sizeof(after));
        Serial.printf("[GESTURE RX] board=%s id=%08lx valid telemetry packet received\n",
                      model_id, (unsigned long)h.id);
        printGesturePacket("U96 -> FB", before);
        printGesturePacket("FB -> U96 (modified)", after);
    } else if (h.kind == demo::TRANSFER_ERROR) {
        Serial.printf("[FILE REJECTED] id=%08lx requested=%lu bytes; insufficient heap\n",
                      (unsigned long)h.id, (unsigned long)h.total);
    }
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
    if (strcmp(topic, topic_ack) == 0) {
        telemetryRtt.acknowledge(payload, length);
        return;
    }

    if (strcmp(topic, topic_demo_in) == 0) {
        uint8_t reply[sizeof(demo::Header) + demo::CHUNK + 4];
        DemoMode mode = demoMode.load();
        size_t size = demoReceiver.handle(payload, length, mode == FILE_MODE,
                                          mode == PIPELINE_MODE, reply, millis());
        if (size) {
            // Trace only validated packets. File bytes come from the receiver's
            // stored-byte readback, not a separate canned serial message.
            printDemoReceipt(payload, reply);
            if (!client.publish(topic_demo_out, reply, size)) {
                Serial.println("[DEMO] Reply publish failed; waiting for sender retry");
            }
        } else {
            Serial.println("[DEMO] Rejected packet (mode, CRC, length or transfer state)");
        }
        return;
    }

    if (strcmp(topic, topic_config) == 0) {
        DemoMode selected = demoMode.load();
        bool valid = false;
        for (int i = 0; i < 3; ++i) {
            char command[24];
            snprintf(command, sizeof(command), "mode:%s", modeNames[i]);
            if (length == strlen(command) && memcmp(payload, command, length) == 0) {
                selected = static_cast<DemoMode>(i); valid = true;
            }
        }
        // The unchanged Android Config button sends this legacy command.
        const char* androidConfig = "{\"sample_rate_hz\":50,\"imu_range\":\"8g\",\"debug\":true}";
        if (length == strlen(androidConfig) && memcmp(payload, androidConfig, length) == 0) {
            selected = static_cast<DemoMode>((selected + 1) % 3); valid = true;
        }
        if (valid) {
            if (selected != demoMode.load()) {
                demoMode.store(selected);
                telemetryRtt.cancel();
                xQueueReset(telemetryQueue);
                demoReceiver.reset();
            }
            // Repeated explicit mode requests are idempotent for ACK retries.
            client.publish(topic_mode, modeNames[selected]);
            char status[128];
            snprintf(status, sizeof(status), "{\"state\":\"online\",\"mode\":\"%s\",\"rtt_session\":%lu}",
                     modeNames[selected], (unsigned long)telemetryRtt.session());
            client.publish(topic_status, status, true);
            Serial.printf("[DEMO] Mode confirmed: %s\n", modeNames[selected]);
        }
    } else if (strcmp(topic, topic_haptic) == 0 && demoMode.load() == AUTO) {
        Serial.println("[MQTT Rx] Haptic command (simulating motor trigger)");
    }
    // In manual modes the Ultra96 subscribes to Haptic commands as Send triggers.
}
