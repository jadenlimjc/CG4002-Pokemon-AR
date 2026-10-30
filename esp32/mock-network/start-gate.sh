#!/bin/sh
set -eu

: "${LISTEN_PORT:?LISTEN_PORT is required}"
: "${UPSTREAM_HOST:?UPSTREAM_HOST is required}"
: "${UPSTREAM_PORT:?UPSTREAM_PORT is required}"

# Always start clean, even if a container is restarted after an impairment.
tc qdisc del dev eth0 root >/dev/null 2>&1 || true

echo "gate listening on :${LISTEN_PORT}, forwarding to ${UPSTREAM_HOST}:${UPSTREAM_PORT}"
exec socat \
    "TCP-LISTEN:${LISTEN_PORT},fork,reuseaddr,nodelay" \
    "TCP:${UPSTREAM_HOST}:${UPSTREAM_PORT},nodelay"

