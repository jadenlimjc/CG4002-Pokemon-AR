#include <WiFi.h>
#include "esp_eap_client.h"
#include "secrets.h"

const uint16_t PORT = 1883;

void setup() {
    Serial.begin(115200);

    WiFi.disconnect(true);
    WiFi.mode(WIFI_STA);

    esp_eap_client_set_identity(
        (const unsigned char *)WIFI_USER,
        strlen(WIFI_USER)
    );

    esp_eap_client_set_username(
        (const unsigned char *)WIFI_USER,
        strlen(WIFI_USER)
    );

    esp_eap_client_set_password(
        (const unsigned char *)WIFI_PASSWORD,
        strlen(WIFI_PASSWORD)
    );

    esp_wifi_sta_enterprise_enable();

    WiFi.begin(WIFI_SSID);

    Serial.print("Connecting to WiFi");
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }

    Serial.println("\nConnected!");
    Serial.print("ESP32 IP: ");
    Serial.println(WiFi.localIP());

    Serial.println("Enter laptop IP:");

    while (!Serial.available()) {
        delay(10);
    }

    String ip = Serial.readStringUntil('\n');
    ip.trim();

    Serial.print("Connecting to ");
    Serial.println(ip);

    WiFiClient client;

    if (client.connect(ip.c_str(), PORT)) {
        Serial.println("SUCCESS!");
        client.println("hello from ESP32");
    } else {
        Serial.println("FAILED!");
    }

    client.stop();
}

void loop() {}
