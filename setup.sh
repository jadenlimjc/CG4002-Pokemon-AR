#!/bin/bash
set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"
PASSWD_FILE="$PROJECT_ROOT/broker/mosquitto.passwd"
SECRETS_FILE="$PROJECT_ROOT/esp32/main/secrets.h"
SSH_KEY_PATH="$HOME/.ssh/esp32_key"

echo "=== Project Setup ==="
echo

# SoC Username
printf "NUS SoC username: "
read SOC_USERNAME
while [ -z "$SOC_USERNAME" ]; do
    echo "Username cannot be empty."
    printf "NUS SoC username: "
    read SOC_USERNAME
done

printf "NUS SoC password: "
read -s SOC_PASSWORD
echo
while [ -z "$SOC_PASSWORD" ]; do
    echo "Password cannot be empty."
    printf "NUS SoC password: "
    read -s SOC_PASSWORD
    echo
done

# Read SSH Key from ~/.ssh/esp32_key
if [ ! -f "$SSH_KEY_PATH" ]; then
    echo "Error: SSH private key not found at $SSH_KEY_PATH"
    echo "Please ensure the file exists before running this setup."
    exit 1
fi
SSH_PRIVATE_KEY="$(cat "$SSH_KEY_PATH")"

# MQTT User (Hardcoded default)
MQTT_USER="team_user"

# MQTT Password
printf "MQTT password: "
read MQTT_PASSWORD
while [ -z "$MQTT_PASSWORD" ]; do
    echo "Password cannot be empty."
    printf "MQTT password: "
    read -s MQTT_PASSWORD
done

# WiFi SSID (eduroam)
WIFI_SSID="eduroam"

# WiFi Username (Visible input)
printf "Eduroam username(e...@u.nus.edu): "
read WIFI_USER

# WiFi Password (Silent input)
printf "Eduroam password(same as school acc): "
read -s WIFI_PASSWORD

# Write root .env file
cat > "$ENV_FILE" <<EOF
SOC_USERNAME=$SOC_USERNAME
SOC_PASSWORD=$SOC_PASSWORD
MQTT_USER=$MQTT_USER
MQTT_PASSWORD=$MQTT_PASSWORD
EOF

chmod 600 "$ENV_FILE"

# Write esp32/include/secrets.h
mkdir -p "$(dirname "$SECRETS_FILE")"
cat > "$SECRETS_FILE" <<EOF
#ifndef SECRETS_H
#define SECRETS_H

const char* SOC_USERNAME = "$SOC_USERNAME";
const char* SOC_PASSWORD = "$SOC_PASSWORD";

const char* WIFI_SSID = "$WIFI_SSID";
const char* WIFI_USER = "$WIFI_USER";
const char* WIFI_PASSWORD = "$WIFI_PASSWORD";

// MQTT Credentials
const char* MQTT_USER = "$MQTT_USER";
const char* MQTT_PASSWORD = "$MQTT_PASSWORD";

// SSH Private Key (~/.ssh/esp32_key)
const char* SSH_PRIVATE_KEY = R"KEY(
$SSH_PRIVATE_KEY
)KEY";

#endif // SECRETS_H
EOF

# Ensure broker directory exists for auth file
mkdir -p "$(dirname "$PASSWD_FILE")"

# Generate Mosquitto auth file
mosquitto_passwd -c -b "$PASSWD_FILE" "$MQTT_USER" "$MQTT_PASSWORD"

echo "=== Setup complete ==="
echo "Created secrets: $ENV_FILE"
echo "Created C++ secrets: $SECRETS_FILE"
echo "Created broker auth: $PASSWD_FILE"
