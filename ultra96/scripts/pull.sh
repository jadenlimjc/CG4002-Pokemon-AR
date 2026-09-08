#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/../.."
TUNNEL_SCRIPT="$SCRIPT_DIR/tunnel_ultra96.sh"

echo "-- STARTING PULL DRY RUN (Computer <- Ultra96) --"
"$TUNNEL_SCRIPT" --rsync \
    -avz --delete \
    --dry-run \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='.git' \
    --exclude='*secrets*' \
    "xilinx@makerslab-fpga-38.ddns.comp.nus.edu.sg:~/cg4002/"
    "$PROJECT_ROOT" \
echo "--------------------------------------------"

read -p "Apply these changes? (y/n): " confirm

if [[ $confirm == [yY] || $confirm == [yY][eE][sS] ]]; then
    echo "Syncing..."
    "$TUNNEL_SCRIPT" --rsync \
    -avz --delete \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='.git' \
    --exclude='*secrets*' \
    "xilinx@makerslab-fpga-38.ddns.comp.nus.edu.sg:~/cg4002/"
    "$PROJECT_ROOT" \
    echo "Pull Complete!"
else
    echo "Pull cancelled."
fi
