#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/../.."
TUNNEL_SCRIPT="$SCRIPT_DIR/tunnel_ultra96.sh"

# Excluded paths are also protected from rsync's --delete. Keep both runs aligned.
PROTECTED_PATHS=(
    --exclude='/esp32/'
    --exclude='/ultra96/fpga/'
    --exclude='/ultra96/vitis/'
    --exclude='/ultra96/pytorch/'
    --exclude='/ultra96/real_data/processed/'
)

echo "-- STARTING PUSH DRY RUN (Computer -> Ultra96) --"
"$TUNNEL_SCRIPT" --rsync \
    -avz --delete \
    --dry-run \
    "${PROTECTED_PATHS[@]}" \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='visualiser/' \
    --exclude='.git' \
    --exclude='*secrets*' \
    --exclude='*.csv' \
    "$PROJECT_ROOT" \
    "xilinx@makerslab-fpga-38.ddns.comp.nus.edu.sg:~/cg4002/"
echo "--------------------------------------------"

read -p "Apply these changes? (y/n): " confirm

if [[ $confirm == [yY] || $confirm == [yY][eE][sS] ]]; then
    echo "Syncing..."
    "$TUNNEL_SCRIPT" --rsync \
    -avz --delete \
    "${PROTECTED_PATHS[@]}" \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='.git' \
    --exclude='visualiser/' \
    --exclude='*secrets*' \
    --exclude='*.csv' \
    "$PROJECT_ROOT" \
    "xilinx@makerslab-fpga-38.ddns.comp.nus.edu.sg:~/cg4002/"
    echo "Push Complete!"
else
    echo "Push cancelled."
fi
