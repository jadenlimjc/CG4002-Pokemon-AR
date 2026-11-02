#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
compose_file="$script_dir/compose.yaml"

[ "$#" -ge 1 ] && [ "$#" -le 3 ] || {
    echo "Usage: ./capture.sh <outer|inner> [seconds] [output.pcap]" >&2
    exit 2
}

case "$1" in
    outer) gate=outer-gate ;;
    inner) gate=inner-gate ;;
    *) echo "Gate must be outer or inner." >&2; exit 2 ;;
esac

seconds=${2:-30}
output=${3:-"$1-${seconds}s.pcap"}

echo "Capturing $gate for $seconds seconds to $output"
status=0
docker compose -f "$compose_file" exec -T "$gate" \
    timeout "$seconds" tcpdump -U -n -i any -w - tcp >"$output" || status=$?

# timeout(1) uses 124 for the expected end of a duration-limited capture.
if [ "$status" -ne 0 ] && [ "$status" -ne 124 ]; then
    echo "Capture failed with status $status" >&2
    exit "$status"
fi
echo "Saved $output"
