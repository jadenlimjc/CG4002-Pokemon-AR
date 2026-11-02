#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
compose_file="$script_dir/compose.yaml"

usage() {
    cat <<'EOF'
Usage: ./control.sh <outer|inner|all> <command> [arguments]

Commands:
  status                         Show active rules and packet/drop counters
  clear                          Remove all impairment
  loss <percent>                 Apply random packet loss, e.g. loss 10
  delay <milliseconds> [jitter]  Add latency, e.g. delay 250 25
  loss-delay <percent> <ms> [jitter]
  cut <seconds>                  Drop 100% immediately, then recover
  outage <wait-seconds> <seconds>
                                 Schedule a deterministic 100% outage
EOF
}

die() {
    echo "$*" >&2
    usage >&2
    exit 2
}

is_uint() {
    case "$1" in
        ''|*[!0-9]*) return 1 ;;
        *) return 0 ;;
    esac
}

is_percent() {
    is_uint "$1" && [ "$1" -le 100 ]
}

[ "$#" -ge 2 ] || die "Missing gate or command."
selection=$1
command=$2
shift 2

case "$selection" in
    outer) gates="outer-gate" ;;
    inner) gates="inner-gate" ;;
    all) gates="outer-gate inner-gate" ;;
    *) die "Unknown gate: $selection" ;;
esac

compose_exec() {
    gate=$1
    shift
    docker compose -f "$compose_file" exec -T "$gate" "$@"
}

apply_tc() {
    for gate in $gates; do
        echo "[$gate] tc $*"
        compose_exec "$gate" tc "$@"
    done
}

clear_impairment() {
    for gate in $gates; do
        echo "[$gate] clear"
        # Surface missing/stopped containers, while tolerating no active qdisc.
        compose_exec "$gate" true
        compose_exec "$gate" tc qdisc del dev eth0 root >/dev/null 2>&1 || true
    done
}

case "$command" in
    status)
        [ "$#" -eq 0 ] || die "status takes no arguments"
        for gate in $gates; do
            echo "[$gate]"
            compose_exec "$gate" tc -s qdisc show dev eth0
        done
        ;;
    clear)
        [ "$#" -eq 0 ] || die "clear takes no arguments"
        clear_impairment
        ;;
    loss)
        [ "$#" -eq 1 ] || die "loss needs a percentage"
        is_percent "$1" || die "loss percentage must be an integer from 0 to 100"
        apply_tc qdisc replace dev eth0 root netem loss "$1%"
        ;;
    delay)
        [ "$#" -ge 1 ] && [ "$#" -le 2 ] || die "delay needs milliseconds and optional jitter"
        is_uint "$1" || die "delay must be a non-negative integer"
        if [ "$#" -eq 2 ]; then
            is_uint "$2" || die "jitter must be a non-negative integer"
            apply_tc qdisc replace dev eth0 root netem delay "$1ms" "$2ms"
        else
            apply_tc qdisc replace dev eth0 root netem delay "$1ms"
        fi
        ;;
    loss-delay)
        [ "$#" -ge 2 ] && [ "$#" -le 3 ] || die "loss-delay needs percent, ms, and optional jitter"
        is_percent "$1" && is_uint "$2" || die "loss must be 0-100 and delay must be a non-negative integer"
        if [ "$#" -eq 3 ]; then
            is_uint "$3" || die "jitter must be a non-negative integer"
            apply_tc qdisc replace dev eth0 root netem delay "$2ms" "$3ms" loss "$1%"
        else
            apply_tc qdisc replace dev eth0 root netem delay "$2ms" loss "$1%"
        fi
        ;;
    cut)
        [ "$#" -eq 1 ] || die "cut needs a duration in seconds"
        is_uint "$1" || die "duration must be a non-negative integer"
        trap 'clear_impairment' EXIT HUP INT TERM
        apply_tc qdisc replace dev eth0 root netem loss 100%
        echo "Dropping all $selection traffic for $1 seconds..."
        sleep "$1"
        clear_impairment
        trap - EXIT HUP INT TERM
        ;;
    outage)
        [ "$#" -eq 2 ] || die "outage needs wait and duration seconds"
        is_uint "$1" && is_uint "$2" || die "wait and duration must be non-negative integers"
        echo "Waiting $1 seconds before the $2-second $selection outage..."
        sleep "$1"
        trap 'clear_impairment' EXIT HUP INT TERM
        apply_tc qdisc replace dev eth0 root netem loss 100%
        echo "Outage active."
        sleep "$2"
        clear_impairment
        trap - EXIT HUP INT TERM
        ;;
    *)
        die "Unknown command: $command"
        ;;
esac
