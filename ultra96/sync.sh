#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TUNNEL_SCRIPT="$SCRIPT_DIR/../broker/tunnel_ultra96.sh"

if ! "$TUNNEL_SCRIPT" --rsync \
    -avz --delete \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='.git' \
    --exclude='*secrets*' \
    "$SCRIPT_DIR/.." \
    "xilinx@makerslab-fpga-38.ddns.comp.nus.edu.sg:~/cg4002/"
then
    echo "Error: failed to sync Ultra96 directory."
    exit 1
fi
