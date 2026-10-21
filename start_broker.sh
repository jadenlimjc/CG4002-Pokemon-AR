#!/bin/bash
set -euo pipefail

service="cg4002-broker.service"

if systemctl is-active --quiet "$service"; then
    echo "CG4002 MQTT broker is already running."
else
    sudo systemctl start "$service"

    if systemctl is-active --quiet "$service"; then
        echo "CG4002 MQTT broker started."
    else
        echo "Broker failed to start. Check:"
        echo "sudo journalctl -u $service -n 30 --no-pager"
        exit 1
    fi
fi
