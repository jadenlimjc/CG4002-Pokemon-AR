# Final live demo

Run from the repository root on the Ultra96, using the Python environment with
the existing FPGA/PYNQ and comms dependencies:

```sh
python ultra96/comms/tests/final_demo.py
```

Use the existing MQTT credentials (`MQTT_USER` and `MQTT_PASSWORD`, or `.env`).
The default broker is `127.0.0.1:1883`. Run this **instead of** `main.py`,
`comms_demo.py`, or `processing_demo.py`: multiple inference services would
send duplicate gestures and ACKs. The boards must already be streaming IMU
telemetry. This dashboard does not change their operating mode or configuration.

The dashboard's bottom `Log:` row shows only the newest event. The complete
rotating diagnostic log is written to `/tmp/cg4002-final-demo.log`; follow it
from a second Ultra96 terminal with:

```sh
tail -F /tmp/cg4002-final-demo.log
```

Use `--log-file PATH` to choose another location. Two 4 MiB rotated backups are
kept alongside the active log.

Useful options:

```sh
python ultra96/comms/tests/final_demo.py --model-id board1 --require-crc
python ultra96/comms/tests/final_demo.py --host 127.0.0.1 --port 1883 --confidence-threshold 0.95
```

`--model-id` is the board ID in its `esp32/<id>/telemetry` topic; omit it to
discover all boards (up to 64). Tab selects the next board. Press `q` or Ctrl-C
to stop. Use an interactive terminal; enlarge it if the footer reports hidden
rows. The selected device accepts `[1/t]` for Tutorial, `[2/g]` for God mode,
`[3/f]` for Full Play, and `[4/s]` to skip the current tutorial step. These
manual events use the same inference topic and gesture JSON contract as model
output. Hardware menu flags, including index/select, continue to be relayed to
Unity while this dashboard is running.

| Keys | Published action | Displayed gameplay mode |
| --- | --- | --- |
| `1` or `t` | `SET_TUTORIAL` | Tutorial |
| `2` or `g` | `SET_GOD_MODE` | God Mode |
| `3` or `f` | `SET_FULL_PLAY` | Full Play |
| `4` or `s` | `SKIP_STEP` | Unchanged |

## Reading the dashboard

- **CURRENT** is the latest raw classifier prediction and confidence, even if
  rejected. Its age is shown, and it is marked STALE after two seconds without
  a new result. Packet reception is shown separately: receiving packets does
  not prove that inference is keeping up.
- **DECISION / WHY** explain whether the prediction sent an event, was too
  uncertain, was blocked by cooldown, was out of sequence, or failed to publish.
- **LAST SENT** persists across later predictions and log messages. It shows
  both the classifier label and the actual gameplay event/ID, confidence, and
  local send time. For example, `STOP_AIMING -> CANCEL` is an intentional catch
  reset. SENT means the MQTT client accepted the QoS 0 publish, **not** that the
  broker or AR app acknowledged delivery. Failed publishes do not replace it.
- **STATE** is the gesture sequence state, not a second classifier prediction.
  `NEUTRAL` means ready for ordinary actions; `AIMING` means Aim was sent;
  `AWAITING_RESET` means Throw was sent and Stop Aim is required before another
  action. Neutral is ignored without changing either catch state.
- After a battle action is published, every classifier result is suppressed for
  two seconds with reason `COOLDOWN`. Confirmation restarts after the cooldown.
- The lower panel shows the selected device's throw mode and gameplay mode,
  manual-action shortcuts, packet rate, mean RTT, and estimated one-way latency.
  Gameplay mode starts at Full Play. The ESP-owned index state alternates that
  device between `CATCH_THROW` (the default) and `POKEBALL_THROW`, is carried in
  telemetry bit 3, and is still relayed separately as a menu-select event.

The default confidence threshold is **0.60**. Per-gesture overrides can be added
to `GESTURE_CONFIDENCE_THRESHOLDS` in `visualiser_protocol.py`; any classifier
label not present in that mapping retains the default. Thresholds apply before
confirmation, including for reset/neutral. They can also reject real gestures
or make resetting harder; compare CURRENT confidence with WHY when that happens.

```python
GESTURE_CONFIDENCE_THRESHOLDS = {
    "FLEE": 0.90,
    "NEUTRAL": 0.80,
    "AIM": 0.50,
    "DOWNWARD_SWIPE": 0.85,
}
```

| Reason | Meaning / next action |
| --- | --- |
| `VALID` | Valid gesture; `PUBLISHED` means MQTT accepted it. |
| `LOW_CONFIDENCE` | Below the resolved threshold. State stays unchanged and confirmation resets. |
| `COOLDOWN` | A battle action was just sent. All predictions are ignored and confirmation is reset for two seconds. |
| `NOT_AIMING` | Throw/Stop Aim while neutral. Aim must be sent before Throw. |
| `ALREADY_AIMING` | Repeated Aim; finish or cancel the catch sequence. |
| `AIMING_LOCK` | Battle action while aiming; Throw or cancel first. |
| `AWAITING_RESET` | A throw already occurred; use Stop Aim before another gesture. |
| `NEUTRAL` | Confident neutral is ignored without changing the current gesture state. |
| `RESET` | Stop Aim ends a catch sequence and sends CANCEL. |
| `PUBLISH_FAILED` | MQTT rejected an otherwise valid send. State and LAST SENT stay unchanged; a later valid prediction can retry. |

## Physical test pass

1. Check that reception settles around 50 Hz with no unexpected CRC errors
   or gaps. The existing **128 samples / 15-sample hop** are unchanged:
   approximately 2.56 seconds to fill the first window and 0.3 seconds between
   available windows at 50 Hz, before scheduling/inference time.
2. Tap index and confirm the displayed throw mode and connected LED change once
   per touch (green catch, red battle); two taps at least 250 ms apart should
   both register. A 500 ms hold should still send one menu-select event. Use
   each manual-action shortcut and confirm the gameplay
   mode changes only for successful mode publications; Skip Step keeps the
   current gameplay mode.
3. Perform each battle gesture, then immediately try the same and a different
   gesture. Expect `COOLDOWN` with no new send for two seconds. After it expires,
   three fresh matching predictions should publish the next battle action.
4. Try Throw without Aim (`NOT_AIMING`), then Aim -> Neutral -> Throw -> Neutral.
   Expect only `ARM_PULLBACK` and `CATCH_THROW`; both Neutral predictions should
   be suppressed without changing the catch state. Cancel with Stop Aim and
   expect `CANCEL`, then try Stop Aim while neutral and verify no new send.
5. Raise the hand into Guard at several speeds. Compare CURRENT, WHY, and
   LAST SENT. Record any high-confidence swipe before Guard. No new temporal
   filter or window change was added, so this transition error can still occur.
6. Compare 0.90 with 0.95 over the same gestures and neutral movements. Note
   both false sends and real gestures/resets rejected; changing the threshold
   alone cannot fix a confidently wrong prediction.
7. If using multiple boards, switch with Tab and confirm each retains its own
   state and last sent event. Interrupt telemetry and confirm stale results
   remain visibly dated rather than appearing to be fresh predictions.

The timing row measures local inference, local queue wait, and receipt of the
last sample through result completion. It does not measure end-to-end gesture
latency, earlier window samples, or radio/network transit.

## Automated regression checks (no FPGA or broker needed)

```sh
python -B -m unittest discover -s ultra96/comms/tests -p 'test_*.py'
```

The suite covers packet decoding and scheduling, all gesture labels in each
catch state, threshold boundaries, cooldown handling, publish
failure/retry, independent current/last-sent snapshots, per-board isolation,
packet rate/CRC/gaps/RTT, and dashboard rendering/terminal restoration. Mocked
classifier outputs verify software behavior; they do not establish recognition
accuracy on real movements.
