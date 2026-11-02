#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
output="$script_dir/../main/network_profile.local.h"
host=${1:-}

if [ -z "$host" ]; then
    printf 'LAN address of this Docker host: '
    IFS= read -r host
fi

case "$host" in
    ''|*[!A-Za-z0-9.:-]*)
        echo "Invalid host. Use a LAN IP address or hostname." >&2
        exit 2
        ;;
esac

tmp="${output}.tmp"
trap 'rm -f "$tmp"' EXIT HUP INT TERM

cat >"$tmp" <<EOF
#pragma once

namespace NetworkProfile {

static constexpr char NAME[] = "local-mock";
static constexpr bool WIFI_ENTERPRISE = false;
static const char *const WIFI_SSID = ::WIFI_SSID;
static const char *const WIFI_PASSWORD = ::WIFI_PASSWORD;

static constexpr char JUMP_HOST[] = "$host";
static constexpr uint16_t JUMP_PORT = 2222;
static constexpr char JUMP_USERNAME[] = "jumper";
static constexpr char JUMP_PASSWORD[] = "jumper";

static constexpr char TARGET_HOST[] = "inner-gate";
static constexpr uint16_t TARGET_SSH_PORT = 2222;
static constexpr char TARGET_USERNAME[] = "target";
static constexpr char TARGET_PASSWORD[] = "target";

static constexpr char SERVICE_HOST[] = "broker";
static constexpr uint16_t SERVICE_PORT = 1883;

} // namespace NetworkProfile
EOF

mv "$tmp" "$output"
trap - EXIT HUP INT TERM
echo "Wrote $output"
echo "Local mock profile will be selected on the next firmware build."

