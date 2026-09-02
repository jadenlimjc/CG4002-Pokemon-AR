#!/bin/bash
set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"
PASSWD_FILE="$PROJECT_ROOT/broker/mosquitto.passwd"
SECRETS_FILE="$PROJECT_ROOT/esp32/include/secrets.h"

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

# KVDB Bucket (Visible input)
printf "KVDB Bucket: "
read KVDB_BUCKET
while [ -z "$KVDB_BUCKET" ]; do
    echo "KVDB Bucket cannot be empty."
    printf "KVDB Bucket: "
    read KVDB_BUCKET
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
MQTT_USER=$MQTT_USER
MQTT_PASSWORD=$MQTT_PASSWORD
KVDB_BUCKET=$KVDB_BUCKET
EOF

chmod 600 "$ENV_FILE"

# Write esp32/include/secrets.h
mkdir -p "$(dirname "$SECRETS_FILE")"
cat > "$SECRETS_FILE" <<EOF
#ifndef SECRETS_H
#define SECRETS_H

const char* WIFI_SSID = "$WIFI_SSID";
const char* WIFI_USER = "$WIFI_USER";
const char* WIFI_PASSWORD = "$WIFI_PASSWORD";

// MQTT Credentials
const char* MQTT_USER = "$MQTT_USER";
const char* MQTT_PASSWORD = "$MQTT_PASSWORD";

#define KVDB_BUCKET "$KVDB_BUCKET"

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
