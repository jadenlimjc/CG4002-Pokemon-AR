"""
Mock Gesture Server for CG4002 Pokemon AR
Sends gesture commands via UDP to the Unity app for testing without hardware.

Usage:
    python mock_gesture_server.py [--ip 127.0.0.1] [--port 8888]

Controls:
    a - ARM_PULLBACK (show reticle / enter aiming)
    c - CATCH_THROW (fire pokeball - hit if aimed)
    x - CANCEL (hide reticle / cancel aiming)
    b - POKEBALL_THROW (send out own Pokemon for battle)
    1 - BATTLE_MOVE 1 (Close Combat - many punches)
    2 - BATTLE_MOVE 2 (Protect - block stance)
    3 - BATTLE_MOVE 3 (Brick Break - up to down)
    4 - BATTLE_MOVE 4 (Drain Punch - single punch)
    q - Quit
"""

import socket
import json
import time
import sys
import argparse

def create_payload(action: str, gesture_id: int = 0, confidence: float = 0.95) -> str:
    payload = {
        "action": action,
        "gesture_id": gesture_id,
        "confidence": confidence,
        "timestamp": int(time.time() * 1000)
    }
    return json.dumps(payload)


def main():
    parser = argparse.ArgumentParser(description="Mock gesture sender for CG4002 Pokemon AR")
    parser.add_argument("--ip", default="127.0.0.1", help="Unity device IP (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8888, help="UDP port (default: 8888)")
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    target = (args.ip, args.port)

    print(f"Mock Gesture Server - sending to {args.ip}:{args.port}")
    print("=" * 50)
    print("Controls:")
    print("  a - Aim (arm pullback, show reticle)")
    print("  c - Catch throw (fire pokeball)")
    print("  x - Cancel (hide reticle, abort throw)")
    print("  b - Battle entry (underhand throw)")
    print("  1 - Move 1: Close Combat")
    print("  2 - Move 2: Protect")
    print("  3 - Move 3: Brick Break")
    print("  4 - Move 4: Drain Punch")
    print("  q - Quit")
    print("=" * 50)

    try:
        while True:
            key = input("\n> ").strip().lower()

            if key == "q":
                print("Exiting...")
                break
            elif key == "a":
                payload = create_payload("ARM_PULLBACK")
                print(f"  Sending: ARM_PULLBACK (show reticle)")
            elif key == "c":
                payload = create_payload("CATCH_THROW")
                print(f"  Sending: CATCH_THROW (fire pokeball)")
            elif key == "x":
                payload = create_payload("CANCEL")
                print(f"  Sending: CANCEL (hide reticle)")
            elif key == "b":
                payload = create_payload("POKEBALL_THROW")
                print(f"  Sending: POKEBALL_THROW")
            elif key in ("1", "2", "3", "4"):
                move_names = {
                    "1": "Close Combat",
                    "2": "Protect",
                    "3": "Brick Break",
                    "4": "Drain Punch"
                }
                gesture_id = int(key)
                payload = create_payload("BATTLE_MOVE", gesture_id=gesture_id)
                print(f"  Sending: BATTLE_MOVE {gesture_id} ({move_names[key]})")
            else:
                print("  Unknown command. Use a/c/x/b/1/2/3/4/q")
                continue

            sock.sendto(payload.encode("utf-8"), target)
            print(f"  Sent: {payload}")

    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
