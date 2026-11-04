# Live gesture testing

Run from the repository root on the Ultra96, using the Python environment with
the existing FPGA/PYNQ and comms dependencies:

```sh
python ultra96/comms/tests/gesture_demo.py
```

Use the existing MQTT credentials (`MQTT_USER` and `MQTT_PASSWORD`, or `.env`).
The default broker is `127.0.0.1:1883`. Run this **instead of** `main.py`,
`comms_demo.py`, or `processing_demo.py`: multiple inference services would
send duplicate gestures and ACKs. The boards must already be streaming IMU
telemetry. This dashboard does not change their operating mode or configuration.

Useful options:

```sh
python ultra96/comms/tests/gesture_demo.py --model-id board1 --require-crc
python ultra96/comms/tests/gesture_demo.py --host 127.0.0.1 --port 1883 --confidence-threshold 0.95
```

`--model-id` is the board ID in its `esp32/<id>/telemetry` topic; omit it to
discover all boards (up to 64). Tab selects the next board. Press `q` or Ctrl-C
to stop. Use an interactive terminal; enlarge it if the footer reports hidden
statistics. There are no haptic, config, file-transfer, or mode controls.

## Reading the dashboard

- **CURRENT** is the latest raw classifier prediction and confidence, even if
  rejected. Its age is shown, and it is marked STALE after two seconds without
  a new result. Packet reception is shown separately: receiving packets does
  not prove that inference is keeping up.
- **DECISION / WHY** explain whether the prediction sent an event, was too
  uncertain, was repeated, was out of sequence, or failed to publish.
- **LAST SENT** persists across later predictions and log messages. It shows
  both the classifier label and the actual gameplay event/ID, confidence, and
  local send time. For example, `NEUTRAL -> CANCEL` is an intentional catch
  reset. SENT means the MQTT client accepted the QoS 0 publish, **not** that the
  broker or AR app acknowledged delivery. Failed publishes do not replace it.
- **STATE** is the gesture sequence state, not a second classifier prediction.
  `NEUTRAL` means ready for ordinary actions; `AIMING` means Aim was sent;
  `AWAITING_RESET` means Throw was sent and a confident Neutral/Stop Aim is
  required before another action.
  `RECOVERING` means a battle action was sent; one confident Neutral prediction
  rearms recognition. Other labels still require three consecutive predictions.
- Packet rate is the unique arrivals in the last second versus the expected
  **100 Hz**; the session average counts received sample intervals. CRC,
  malformed/retained packets, gaps, duplicate packets, backwards/reset
  counters, silence/recovery counts, RTT, inference timing, and skipped windows
  help distinguish recognition problems from data-flow problems. Sequence
  gaps are observed missing slots, not proof of network loss. RTT is measured
  by the board and needs its status/session plus RTT reports; `--` is unknown.

The default confidence threshold is **0.90**, up from 0.75. It is a conservative
starting point for testing, not a measured optimum or a calibrated probability
of correctness. Both this dashboard and the production service accept
`--confidence-threshold` as a fraction from 0 to 1. The threshold applies to
every label, including reset/neutral. It can also reject real gestures or make
resetting harder; compare the CURRENT confidence with the reason when that happens.

| Reason | Meaning / next action |
| --- | --- |
| `VALID` | Valid gesture; `PUBLISHED` means MQTT accepted it. |
| `LOW_CONFIDENCE` | Below the threshold. State and repeat filter stay unchanged. |
| `REPEATED` | Same held battle gesture already sent. Return to confirmed Neutral before another gesture. |
| `RECOVERING` | Battle action already sent. Other gestures are blocked until confirmed Neutral, including hand-return movements. |
| `NOT_AIMING` | Throw/Stop Aim while neutral. Aim must be sent before Throw. Idle Stop Aim does not rearm a held battle gesture. |
| `ALREADY_AIMING` | Repeated Aim; finish or cancel the catch sequence. |
| `AIMING_LOCK` | Battle action while aiming; Throw or cancel first. |
| `AWAITING_RESET` | A throw already occurred; return to Neutral or Stop Aim. |
| `NEUTRAL` | Confident neutral clears the repeat filter without a gameplay event. |
| `RESET` | Neutral/Stop Aim ends a catch sequence and sends CANCEL. |
| `PUBLISH_FAILED` | MQTT rejected an otherwise valid send. State and LAST SENT stay unchanged; a later valid prediction can retry. |

## Physical test pass

1. Check that reception settles around 100 Hz with no unexpected CRC errors
   or gaps. The existing **256 samples / 25-sample hop** are unchanged:
   approximately 2.56 seconds to fill the first window and 0.25 seconds between
   available windows at 100 Hz, before scheduling/inference time.
2. Perform each battle gesture, then hold it. Confirm one send followed by
   `REPEATED`. Return to confident Neutral and repeat the gesture. Also try a
   different battle gesture directly: expect `RECOVERING` with no new send.
   Specifically try Guard -> hand down and Use Item -> hand back. One confident
   Neutral prediction should rearm recognition; the next action still needs
   three consecutive predictions.
3. Try Throw without Aim (`NOT_AIMING`), then Aim -> Throw -> Neutral. Expect
   `ARM_PULLBACK`, `CATCH_THROW`, and `CANCEL`; check the state after each.
   While aiming, try a battle action and verify `AIMING_LOCK`. Cancel with
   Stop Aim, then try Stop Aim while neutral and verify no new send.
4. Raise the hand into Guard at several speeds. Compare CURRENT, WHY, and
   LAST SENT. Record any high-confidence swipe before Guard. No new temporal
   filter or window change was added, so this transition error can still occur.
5. Compare 0.90 with 0.95 over the same gestures and neutral movements. Note
   both false sends and real gestures/resets rejected; changing the threshold
   alone cannot fix a confidently wrong prediction.
6. If using multiple boards, switch with Tab and confirm each retains its own
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
catch state, threshold boundaries, rejected-label repeat handling, publish
failure/retry, independent current/last-sent snapshots, per-board isolation,
packet rate/CRC/gaps/RTT, and dashboard rendering/terminal restoration. Mocked
classifier outputs verify software behavior; they do not establish recognition
accuracy on real movements.
