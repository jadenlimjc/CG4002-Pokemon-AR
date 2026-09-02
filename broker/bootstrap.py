import time
import requests
import sys
import subprocess
import signal
import os

# ==============================================================================
# CONFIGURATION
# ==============================================================================
KVDB_BUCKET = os.getenv("KVDB_BUCKET")
KVDB_URL = f"https://kvdb.io/{KVDB_BUCKET}/bootstrap"

# Globals to track processes starting up
mosquitto_proc = None
ngrok_proc = None


def get_ngrok_tunnel():
    """Queries ngrok's local client API to extract the public TCP tunnel address."""
    try:
        # ngrok exposes a local admin API on port 4040
        resp = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=2)
        if resp.status_code == 200:
            data = resp.json()
            tunnels = data.get("tunnels", [])
            for tunnel in tunnels:
                if tunnel.get("proto") == "tcp":
                    public_url = tunnel.get("public_url")
                    clean_url = public_url.replace("tcp://", "")
                    host, port = clean_url.split(":")
                    return host, int(port)
    except requests.exceptions.ConnectionError:
        print("[Error] Could not connect to local ngrok API. Is ngrok running?")
        print("        Command to run: ngrok tcp 1883")
    except Exception as e:
        print(f"[Error] Failed to parse ngrok configuration: {e}")
    return None, None

def publish_to_kvdb(host, port):
    """Pushes host and port configurations to kvdb.io as a JSON payload."""
    try:
        payload = {
            "host": host,
            "port": port
        }
        print(f"[KVDB] Attempting to write coordinates to {KVDB_URL}...")
        resp = requests.put(KVDB_URL, json=payload, timeout=5)

        if resp.status_code in (200, 201):
            print(f"[Success] Published coordinates successfully!")
            print(f"          Broker Host : {host}")
            print(f"          Broker Port : {port}")
            print(f"          KVDB Endpoint: {KVDB_URL}")
            return True
        else:
            print(f"[Error] KVDB API returned status code {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"[Error] Failed to push to KVDB: {e}")
    return False

def start_background_services():
    global mosquitto_proc, ngrok_proc

    # Resolve absolute path of mosquitto.conf based on where the script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "mosquitto.conf")

    # Start Mosquitto Broker
    print("[System] Starting Mosquitto Broker...")
    try:
        mosquitto_proc = subprocess.Popen(
            ["mosquitto", "-c", config_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except FileNotFoundError:
        print("[Error] 'mosquitto' executable not found on system PATH.")
        sys.exit(1)
    except Exception as e:
        print(f"[Error] Failed to start Mosquitto: {e}")
        sys.exit(1)

    # Start Ngrok TCP Tunnel
    print("[System] Starting ngrok TCP tunnel on port 1883...")
    try:
        ngrok_proc = subprocess.Popen(
            ["ngrok", "tcp", "1883"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except FileNotFoundError:
        print("[Error] 'ngrok' executable not found on system PATH.")
        mosquitto_proc.terminate()
        sys.exit(1)
    except Exception as e:
        print(f"[Error] Failed to start ngrok: {e}")
        mosquitto_proc.terminate()
        sys.exit(1)

    # Wait for ngrok to spin up and bind its local API
    print("[System] Waiting 3 seconds for ngrok to initialize...")
    time.sleep(3) # TODO: why the fuck we waiting 3s

def clear_kvdb():
    """Clears/Deletes the glove configuration on KVDB.io."""
    try:
        print(f"[KVDB] Cleaning up... Deleting coordinates at {KVDB_URL}")
        resp = requests.delete(KVDB_URL, timeout=5)
        if resp.status_code in (200, 204, 404):
            print("[Success] KVDB configuration cleared.")
        else:
            print(f"[Warning] Clear returned status code {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"[Error] Failed to clear KVDB on exit: {e}")

def kill_processes(signum=None, frame=None):
    print("[Shutdown] Killing processes")
    # Kill Ngrok
    global ngrok_proc
    if ngrok_proc and ngrok_proc.poll() is None:
        print("[Shutdown] Stopping ngrok...")
        ngrok_proc.terminate()
        ngrok_proc.wait()  # Wait for it to exit fully

    # Kill Mosquitto
    global mosquitto_proc
    if mosquitto_proc and mosquitto_proc.poll() is None:
        print("[Shutdown] Stopping Mosquitto...")
        mosquitto_proc.terminate()
        mosquitto_proc.wait()

    print("[Shutdown] All services stopped.")
    sys.exit(0)

def graceful_exit(sig, frame):
    """Handle graceful shutdown signals."""
    print("\n[Shutdown] Caught termination signal. Cleaning up configuration before exit...")
    clear_kvdb()
    kill_processes()
    print("[Shutdown] Done. Exiting.")
    sys.exit(0)


def main():
    print("==================================================")
    print("            MQTT Startup Orchestration            ")
    print("==================================================")

    # Register shutdown signals
    signal.signal(signal.SIGINT, graceful_exit)
    signal.signal(signal.SIGTERM, graceful_exit)

    start_background_services()

    host, port = get_ngrok_tunnel()
    if not host or not port:
        print("[Abort] No active TCP ngrok tunnel resolved.")
        kill_processes()
        sys.exit(1)

    publish_to_kvdb(host, port)

    try:
        while True:
            if mosquitto_proc and mosquitto_proc.poll() is not None:
                print("[Warning] Mosquitto stopped unexpectedly!")
                break
            if ngrok_proc and ngrok_proc.poll() is not None:
                print("[Warning] Ngrok stopped unexpectedly!")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        graceful_exit()

if __name__ == "__main__":
    main()
