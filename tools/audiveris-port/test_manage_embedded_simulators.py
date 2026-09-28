import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("simulators", Path(__file__).with_name("manage-embedded-simulators.py"))
simulators = importlib.util.module_from_spec(spec)
spec.loader.exec_module(simulators)


class SimulatorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.types = [{"identifier": "type." + family, "name": family + " model", "productFamily": family}
                      for family in simulators.FAMILIES]
        self.runtime = {"identifier": "com.apple.CoreSimulator.SimRuntime.iOS-26-5", "version": "26.5",
                        "isAvailable": True, "supportedArchitectures": ["arm64"], "supportedDeviceTypes": self.types}
        self.devices = {self.runtime["identifier"]: [
            {"udid": "00000000-0000-0000-0000-000000000099", "name": "Runner's existing iPhone",
             "deviceTypeIdentifier": "type.iPhone", "isAvailable": True}]}
        self.commands = []

    def fake_data(self, *arguments):
        return {("list", "runtimes"): {"runtimes": [self.runtime]},
                ("list", "devicetypes"): {"devicetypes": self.types},
                ("list", "devices"): {"devices": self.devices}}[arguments]

    def fake_run(self, *arguments, check=True):
        self.commands.append(arguments)
        if arguments == ("xcrun", "--sdk", "iphonesimulator", "--show-sdk-version"):
            return "26.5"
        if arguments[2] == "create":
            _, _, _, name, kind, runtime = arguments
            identifier = "00000000-0000-0000-0000-00000000000" + str(len(self.devices[runtime]))
            self.devices[runtime].append({"udid": identifier, "name": name, "deviceTypeIdentifier": kind,
                                          "isAvailable": True, "state": "Shutdown"})
            return identifier
        if arguments[2] == "delete":
            for devices in self.devices.values():
                devices[:] = [item for item in devices if item["udid"] != arguments[3]]
        return ""

    def test_latest_installed_sdk_compatible_arm64_runtime_is_selected(self):
        older = {**self.runtime, "version": "26.4"}
        newer = {**self.runtime, "version": "26.6"}
        wrong_arch = {**self.runtime, "version": "26.5.1", "supportedArchitectures": ["x86_64"]}
        selected, types = simulators.select_devices([older, newer, wrong_arch, self.runtime], self.types, "26.5")
        self.assertEqual(selected, self.runtime)
        self.assertEqual(set(types), {"iPhone", "iPad"})

    def test_latest_runtime_missing_one_family_does_not_fall_back(self):
        older = {**self.runtime, "version": "26.4"}
        latest = {**self.runtime, "supportedDeviceTypes": self.types[:1]}
        with self.assertRaisesRegex(ValueError, "iPad"):
            simulators.select_devices([older, latest], self.types, "26.5")

    def test_device_family_is_verified_against_installed_type(self):
        mislabeled = [{**item, "productFamily": "iPhone"} for item in self.types]
        with self.assertRaisesRegex(ValueError, "iPad"):
            simulators.select_devices([self.runtime], mislabeled, "26.5")

    def test_old_or_newer_than_sdk_runtimes_are_rejected(self):
        for value in ("18.6", "26.6"):
            with self.subTest(version=value), self.assertRaises(ValueError):
                simulators.select_devices([{**self.runtime, "version": value}], self.types, "26.5")

    def test_screenshot_selection_preserves_both_required_display_sizes(self):
        types = self.types + [
            {"identifier": "type.largePhone", "name": "iPhone 17 Pro Max", "productFamily": "iPhone"},
            {"identifier": "type.smallPad", "name": "iPad Pro 11-inch (M5)", "productFamily": "iPad"},
            {"identifier": "type.largePad", "name": "iPad Pro 13-inch (M5)", "productFamily": "iPad"}]
        runtime = {**self.runtime, "supportedDeviceTypes": types}
        selected, devices = simulators.select_devices([runtime], types, "26.5", screenshot=True)
        self.assertEqual(selected, runtime)
        self.assertEqual(devices["iPhone"]["identifier"], "type.largePhone")
        self.assertEqual(devices["iPad"]["identifier"], "type.largePad")

    def test_screenshot_selection_rejects_other_sizes_without_falling_back(self):
        with self.assertRaisesRegex(ValueError, "screenshot-sized iPhone"):
            simulators.select_devices([self.runtime], self.types, "26.5", ("iPhone",), screenshot=True)

    def test_matrix_creates_only_its_family_and_cleanup_preserves_existing_devices(self):
        with patch.object(simulators, "data", side_effect=self.fake_data), patch.object(simulators, "run", side_effect=self.fake_run):
            simulators.create(self.root, ("iPhone",))
            self.assertTrue((self.root / "iPhone" / "device.json").is_file())
            self.assertFalse((self.root / "iPad").exists())
            self.assertEqual(len(json.loads((self.root / "created-devices.json").read_text())["devices"]), 1)
            simulators.cleanup(self.root)
        self.assertEqual(len(self.devices[self.runtime["identifier"]]), 1)
        self.assertEqual(self.devices[self.runtime["identifier"]][0]["name"], "Runner's existing iPhone")

    def test_creates_both_families_records_identity_and_only_deletes_owned_devices(self):
        with patch.object(simulators, "data", side_effect=self.fake_data), patch.object(simulators, "run", side_effect=self.fake_run):
            simulators.create(self.root)
            identities = [json.loads((self.root / family / "device.json").read_text()) for family in simulators.FAMILIES]
            self.assertEqual(len({item["udid"] for item in identities}), 2)
            for family, identity in zip(simulators.FAMILIES, identities):
                self.assertTrue(identity["createdForThisRun"])
                self.assertEqual(identity["deviceType"]["productFamily"], family)
                self.assertEqual(identity["device"]["deviceTypeIdentifier"], "type." + family)
                self.assertEqual(identity["runtime"], self.runtime)
            with self.assertRaisesRegex(ValueError, "already exists"):
                simulators.create(self.root)
            simulators.cleanup(self.root)
            simulators.cleanup(self.root)
        remaining = self.devices[self.runtime["identifier"]]
        self.assertEqual([item["name"] for item in remaining], ["Runner's existing iPhone"])
        deleted = {cmd[3] for cmd in self.commands if len(cmd) > 3 and cmd[2] == "delete"}
        self.assertEqual(deleted, {item["udid"] for item in identities})

    def test_partial_creation_can_be_cleaned_after_second_device_fails(self):
        def fail_ipad(*arguments, **kwargs):
            if len(arguments) > 4 and arguments[2] == "create" and arguments[4] == "type.iPad":
                raise RuntimeError("device creation failed")
            return self.fake_run(*arguments, **kwargs)
        with patch.object(simulators, "data", side_effect=self.fake_data), patch.object(simulators, "run", side_effect=fail_ipad):
            with self.assertRaisesRegex(RuntimeError, "creation failed"):
                simulators.create(self.root)
            self.assertEqual(len(json.loads((self.root / "created-devices.json").read_text())["devices"]), 1)
            simulators.cleanup(self.root)
        self.assertEqual(len(self.devices[self.runtime["identifier"]]), 1)

    def test_cleanup_refuses_device_whose_ownership_changed(self):
        with patch.object(simulators, "data", side_effect=self.fake_data), patch.object(simulators, "run", side_effect=self.fake_run):
            simulators.create(self.root)
            self.devices[self.runtime["identifier"]][1]["name"] = "Different task's simulator"
            with self.assertRaisesRegex(ValueError, "ownership"):
                simulators.cleanup(self.root)
        self.assertFalse(any(len(cmd) > 2 and cmd[2] == "delete" for cmd in self.commands))


if __name__ == "__main__":
    unittest.main()
