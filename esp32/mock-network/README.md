# Controllable local SSH jump lab

This lab replaces the unreachable NUS jump path with local containers while
keeping the firmware's real two-session SSH implementation:

```text
ESP32 -> outer gate -> jump sshd -> inner gate -> target sshd -> MQTT broker
```

The two gates are TCP forwarders with Linux `netem` controls. Impair them
independently to determine whether a failure comes from the ESP32-to-jump SSH
session or the nested jump-to-target SSH session. This is not an SSH stub: both
hops are real OpenSSH servers and the final service is a real Mosquitto broker.

## Start and select the lab

Docker with the Compose plugin is required. From this directory:

```sh
docker compose up --build -d
./configure-firmware.sh 192.168.1.50
```

Replace `192.168.1.50` with the LAN address of the computer running Docker. The
script creates the ignored `../main/network_profile.local.h`; its presence makes
the firmware use home WPA/WPA2 Wi-Fi and the local lab. Update `WIFI_SSID` and
`WIFI_PASSWORD` in the already-ignored `../main/secrets.h`, then build and flash
normally. Allow inbound TCP port 2222 through the host firewall.

The mock credentials are intentionally fixed and LAN-only:

- jump: `jumper` / `jumper`
- target: `target` / `target`

The existing private key is tried first; password fallback then authenticates
against these mock accounts. The broker accepts the firmware's existing MQTT
credentials so no production secrets are needed by the containers.

To switch back to the campus path, move or remove
`../main/network_profile.local.h` and rebuild. Stop the lab with:

```sh
docker compose down
```

## Controlled failures

Run controls from this directory in a second terminal. `outer` affects the first
SSH connection, `inner` affects the nested SSH connection, and `all` affects
both.

```sh
# Exact five-second packet blackout, starting now
./control.sh outer cut 5

# Exact five-second inner-hop blackout, starting 20 seconds from now
./control.sh inner outage 20 5

# Sustained loss or latency until explicitly cleared
./control.sh inner loss 10
./control.sh outer delay 250 25
./control.sh inner loss-delay 5 200 20
./control.sh all clear

# Read active settings and kernel packet/drop counters
./control.sh all status
```

`cut` and `outage` are deterministic 100% loss windows. Percentage loss is
useful for repeated recovery testing but the exact packets selected are random.
Controls automatically clear a timed outage when interrupted.

For a packet capture around an incident:

```sh
./capture.sh outer 30 outer-incident.pcap
./capture.sh inner 30 inner-incident.pcap
```

The captures contain encrypted SSH traffic, but their timing, retransmissions,
and connection resets can be correlated with the firmware's serial diagnostics.

## What each failure means

- Failure before `channel1 open`: outer gate, jump authentication, or the jump
  server itself.
- `channel1 open` followed by stage-2 failure: inner gate or target SSH.
- Both SSH authentications succeed but `Forward2` fails: target-to-broker path.
- `Tunnel established` followed by MQTT failure: inspect broker logs with
  `docker compose logs broker` and the firmware MQTT state.
