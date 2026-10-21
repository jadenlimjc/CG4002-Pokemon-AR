"""Generate Unity connection settings from setup.sh's environment and SSH key."""
import argparse
import json
import os
from pathlib import Path


def write_settings(key_path, output_path):
    required = ("SOC_USERNAME", "SOC_PASSWORD", "MQTT_USER", "MQTT_PASSWORD")
    if any(not os.environ.get(name) for name in required):
        raise ValueError("SOC_USERNAME, SOC_PASSWORD, MQTT_USER and MQTT_PASSWORD are required")
    settings = {
        "jumpHost": "stujump.comp.nus.edu.sg", "jumpPort": 22,
        "socUsername": os.environ["SOC_USERNAME"],
        "socPassword": os.environ["SOC_PASSWORD"],
        "ultra96Host": "makerslab-fpga-38.ddns.comp.nus.edu.sg", "ultra96Port": 22,
        "ultra96Username": "xilinx", "ultra96Password": "xilinx",
        "mqttUsername": os.environ["MQTT_USER"],
        "mqttPassword": os.environ["MQTT_PASSWORD"],
        "sshPrivateKey": Path(key_path).read_text(), "sshKeyPassphrase": "",
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Restrict permissions before writing, including when replacing an existing file.
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.truncate(0)
        json.dump(settings, stream, indent=2)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    write_settings(args.key, args.output)


if __name__ == "__main__":
    main()
