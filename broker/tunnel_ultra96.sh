#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "Error: $ENV_FILE not found at repository root."
    echo "Please run ./broker/setup.sh first."
    exit 1
fi

source "$ENV_FILE"

if [[ -z "$SOC_USERNAME" ]]; then
    echo "Error: SOC_USERNAME is missing in $ENV_FILE."
    echo "Please rerun ./broker/setup.sh"
    exit 1
fi

SSH_ARGS=(
    -J "$SOC_USERNAME@stujump.comp.nus.edu.sg"
)

if [[ "$1" == "--rsync" ]]; then
    exec rsync "${@:2}" -e "ssh ${SSH_ARGS[*]}"
fi

exec ssh "${SSH_ARGS[@]}" \
    -R 1883:localhost:1883 \
    xilinx@makerslab-fpga-38.ddns.comp.nus.edu.sg
