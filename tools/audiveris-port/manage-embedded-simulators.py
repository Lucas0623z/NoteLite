#!/usr/bin/env python3
"""Create fresh owned iPhone/iPad simulators and remove only those after acceptance."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import uuid

FAMILIES = ("iPhone", "iPad")


def run(*arguments, check=True):
    return subprocess.run(arguments, check=check, text=True, stdout=subprocess.PIPE).stdout.strip()


def data(*arguments):
    return json.loads(run("xcrun", "simctl", *arguments, "--json"))


def version(value):
    pieces = tuple(int(piece) for piece in value.split("."))
    return pieces + (0,) * max(0, 3 - len(pieces))


def select_devices(runtimes, installed_types, sdk):
    compatible = [runtime for runtime in runtimes
                  if runtime.get("isAvailable")
                  and runtime["identifier"].startswith("com.apple.CoreSimulator.SimRuntime.iOS-")
                  and "arm64" in runtime.get("supportedArchitectures", [])
                  and version("26") <= version(runtime["version"]) <= version(sdk)]
    if not compatible:
        raise ValueError("No installed arm64 iOS runtime matches the selected SDK and iOS 26 minimum")
    runtime = max(compatible, key=lambda item: (version(item["version"]), item["identifier"]))
    installed = {item["identifier"]: item for item in installed_types}
    selected = {}
    for family in FAMILIES:
        candidates = [item for item in runtime.get("supportedDeviceTypes", [])
                      if item.get("productFamily") == family and item["identifier"] in installed
                      and installed[item["identifier"]].get("productFamily") == family]
        if not candidates:
            raise ValueError("Latest compatible runtime lacks an installed " + family + " device type")
        # Select a supported installed type and record its exact identity.
        # Both phases reuse the new device ID, never a preexisting device by name.
        selected[family] = candidates[0]
    return runtime, selected


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def create(root):
    registry = root / "created-devices.json"
    if registry.exists():
        raise ValueError("Simulator ownership record already exists; use a fresh acceptance directory")
    sdk = run("xcrun", "--sdk", "iphonesimulator", "--show-sdk-version")
    runtime, types = select_devices(data("list", "runtimes")["runtimes"],
                                    data("list", "devicetypes")["devicetypes"], sdk)
    prefix = "NoteLite OMR " + os.environ.get("GITHUB_RUN_ID", "local") + "-" + uuid.uuid4().hex[:8]
    ownership = {"schema": 1, "namePrefix": prefix, "sdk": sdk, "devices": []}
    write_json(registry, ownership)
    for family in FAMILIES:
        name = prefix + " " + family
        device = str(uuid.UUID(run("xcrun", "simctl", "create", name, types[family]["identifier"],
                                   runtime["identifier"]))).upper()
        identity = {"family": family, "udid": device, "name": name,
                    "runtimeIdentifier": runtime["identifier"], "deviceTypeIdentifier": types[family]["identifier"]}
        # Persist ownership immediately so the always-run cleanup can also
        # recover a partial setup if the second device cannot be created.
        ownership["devices"].append(identity)
        write_json(registry, ownership)
        matches = [item for item in data("list", "devices")["devices"].get(runtime["identifier"], [])
                   if item["udid"].upper() == device]
        if len(matches) != 1 or matches[0].get("name") != name or not matches[0].get("isAvailable") \
                or matches[0].get("deviceTypeIdentifier") != types[family]["identifier"]:
            raise ValueError("CoreSimulator did not create the requested available " + family)
        write_json(root / family / "device.json", {
            "udid": device, "device": matches[0], "runtime": runtime,
            "deviceType": types[family], "createdForThisRun": True,
        })
        print("Created fresh " + family + ": " + device + " (" + types[family]["name"] + ", iOS " + runtime["version"] + ")")


def cleanup(root):
    registry = root / "created-devices.json"
    if not registry.exists():
        return
    ownership = json.loads(registry.read_text(encoding="utf-8"))
    available = data("list", "devices")["devices"]
    results = []
    for owned in ownership["devices"]:
        matches = [(runtime, item) for runtime, devices in available.items() for item in devices
                   if item["udid"].upper() == owned["udid"]]
        if not matches:
            results.append({"udid": owned["udid"], "status": "alreadyAbsent"})
            continue
        runtime, actual = matches[0]
        if len(matches) != 1 or not ownership["namePrefix"].startswith("NoteLite OMR ") \
                or owned["name"] != ownership["namePrefix"] + " " + owned["family"] \
                or owned["family"] not in FAMILIES or actual["name"] != owned["name"] \
                or runtime != owned["runtimeIdentifier"] \
                or actual.get("deviceTypeIdentifier") != owned["deviceTypeIdentifier"]:
            raise ValueError("Refusing to delete a simulator that no longer matches this run's ownership")
        run("xcrun", "simctl", "shutdown", owned["udid"], check=False)
        run("xcrun", "simctl", "delete", owned["udid"])
        results.append({"udid": owned["udid"], "status": "deleted"})
    write_json(root / "cleanup.json", {"devices": results})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "cleanup"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    {"create": create, "cleanup": cleanup}[args.action](args.directory)
