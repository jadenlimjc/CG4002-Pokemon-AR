"""
Continuous Mock - Simulates a full encounter->battle sequence automatically.
Useful for demo/testing the full flow without manual input.

Usage:
    python continuous_mock.py [--ip 127.0.0.1] [--port 8888]
"""

import socket
import json
import time
import argparse
import random


def send_gesture(sock, target, action, gesture_id=0, confidence=0.95):
    payload = {
        "action": action,
        "gesture_id": gesture_id,
        "confidence": confidence,
        "timestamp": int(time.time() * 1000)
    }
    data = json.dumps(payload).encode("utf-8")
    sock.sendto(data, target)
    print(f"  [{time.strftime('%H:%M:%S')}] Sent: {action}" + (f" (id={gesture_id})" if gesture_id else ""))


def run_battle_sequence(sock, target):
    """Simulate a full battle with random moves."""
    print("\n=== Starting battle sequence ===")

    # Wait for encounter (user would see wild Pokemon appear)
    print("Waiting 3s for encounter to register...")
    time.sleep(3)

    # Choose battle
    print("Sending POKEBALL_THROW (enter battle)...")
    send_gesture(sock, target, "POKEBALL_THROW")
    time.sleep(3)  # Wait for battle entry animation

    # Execute 5 random moves
    moves = [1, 2, 3, 4]
    for turn in range(5):
        print(f"\n--- Turn {turn + 1} ---")
        move = random.choice(moves)
        move_names = {1: "Close Combat", 2: "Protect", 3: "Brick Break", 4: "Drain Punch"}
        print(f"Using {move_names[move]}...")
        send_gesture(sock, target, "BATTLE_MOVE", gesture_id=move)
        time.sleep(3)  # Wait for move animation + wild Pokemon turn

    print("\n=== Battle sequence complete ===")


def run_catch_sequence(sock, target):
    """Simulate a catch attempt with aiming."""
    print("\n=== Starting catch sequence ===")

    print("Waiting 3s for encounter...")
    time.sleep(3)

    print("Sending ARM_PULLBACK (show reticle, player aims)...")
    send_gesture(sock, target, "ARM_PULLBACK")

    print("Aiming for 2s (player centers Pokemon in reticle)...")
    time.sleep(2)

    print("Sending CATCH_THROW (fire pokeball)...")
    send_gesture(sock, target, "CATCH_THROW")

    print("Waiting for catch animation (5s)...")
    time.sleep(5)

    print("=== Catch sequence complete ===")


def main():
    parser = argparse.ArgumentParser(description="Continuous mock gesture sender")
    parser.add_argument("--ip", default="127.0.0.1", help="Unity device IP")
    parser.add_argument("--port", type=int, default=8888, help="UDP port")
    parser.add_argument("--mode", choices=["battle", "catch", "random"], default="random",
                        help="Sequence mode")
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    target = (args.ip, args.port)

    print(f"Continuous Mock - target {args.ip}:{args.port}, mode={args.mode}")

    try:
        if args.mode == "battle":
            run_battle_sequence(sock, target)
        elif args.mode == "catch":
            run_catch_sequence(sock, target)
        else:
            # Random: alternate between catch and battle
            while True:
                if random.random() > 0.5:
                    run_battle_sequence(sock, target)
                else:
                    run_catch_sequence(sock, target)
                print("\nWaiting 10s before next encounter...")
                time.sleep(10)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
