#!/bin/sh
set -eu

: "${SSH_USER:?SSH_USER is required}"
: "${SSH_PASSWORD:?SSH_PASSWORD is required}"

if ! id "$SSH_USER" >/dev/null 2>&1; then
    adduser -D -s /bin/ash "$SSH_USER"
fi
printf '%s:%s\n' "$SSH_USER" "$SSH_PASSWORD" | chpasswd

mkdir -p /run/sshd
ssh-keygen -A

exec /usr/sbin/sshd -D -e -f /etc/ssh/sshd_config

