#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
PASSWD_FILE="$SCRIPT_DIR/mosquitto.passwd"

echo "=== Project Setup ==="
echo

# 1. SoC Username
printf "NUS SoC username: "
read SOC_USERNAME
while [ -z "$SOC_USERNAME" ]; do
    echo "Username cannot be empty."
    printf "NUS SoC username: "
    read SOC_USERNAME
done

# 2. MQTT User (Hardcoded default)
MQTT_USER="team_user"

# 3. MQTT Password (Silent input)
printf "MQTT password: "
read MQTT_PASSWORD
echo
while [ -z "$MQTT_PASSWORD" ]; do
    echo "Password cannot be empty."
    printf "MQTT password: "
    read -s MQTT_PASSWORD
    echo
done

# Write single root .env file
cat > "$ENV_FILE" <<EOF
SOC_USERNAME=$SOC_USERNAME
MQTT_USER=$MQTT_USER
MQTT_PASSWORD=$MQTT_PASSWORD
EOF

chmod 600 "$ENV_FILE"

# Generate Mosquitto auth file
mosquitto_passwd -c -b "$PASSWD_FILE" "$MQTT_USER" "$MQTT_PASSWORD"

echo "=== Setup complete ==="
echo "Created secrets: $ENV_FILE"
echo "Created broker auth: $PASSWD_FILE"
