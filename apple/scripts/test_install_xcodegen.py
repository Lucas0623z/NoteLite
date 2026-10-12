"""Offline installer boundaries; fixtures never execute a macOS binary."""
import hashlib
import json
from pathlib import Path
import stat
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import warnings
import zipfile


SCRIPT = Path(__file__).with_name("install-xcodegen.sh")


def validator():
    text = SCRIPT.read_text(encoding="utf-8")
    embedded = text.split("<<'PY_XCODEGEN_VALIDATOR'\n", 1)[1].split(
        "\nPY_XCODEGEN_VALIDATOR\n", 1
    )[0]
    namespace = {"__name__": "offline_installer_boundary_test"}
    exec(compile(embedded, str(SCRIPT) + ":embedded-validator", "exec"), namespace)
    return namespace


def synthetic_macho(platform=1):
    # Two bounded MH_EXECUTE slices. This fixture contains headers, not runnable code.
    cpus = (0x1000007, 0x100000C)
    slices = []
    for cpu in cpus:
        header = struct.pack("<8I", 0xFEEDFACF, cpu, 0, 2, 1, 24, 0, 0)
        build = struct.pack("<6I", 0x32, 24, platform, 0xB0000, 0x1A0500, 0)
        slices.append(header + build)
    fat = struct.pack(">II", 0xCAFEBABE, 2)
    fat += struct.pack(">5I", cpus[0], 3, 64, 56, 4)
    fat += struct.pack(">5I", cpus[1], 0, 128, 56, 4)
    return fat.ljust(64, b"\0") + slices[0] + b"\0" * 8 + slices[1]


class InstallerBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="xcodegen-offline-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ns = validator()
        self.binary = synthetic_macho()
        self.rejection_count = 0
        prefix, bin_path = self.ns["PREFIX"], self.ns["BIN"]
        self.info = {
            "schemaVersion": "1.0",
            "artifacts": {
                "xcodegen": {
                    "version": "2.46.0",
                    "type": "executable",
                    "variants": [{
                        "supportedTriples": ["x86_64-apple-macosx", "arm64-apple-macosx"],
                        "path": "xcodegen-2.46.0-macosx/bin/xcodegen",
                    }],
                }
            },
        }
        self.contents = {
            prefix + "info.json": json.dumps(self.info).encode(),
            bin_path + "xcodegen": self.binary,
            bin_path + "LICENSE": b"MIT License\nCopyright (c) 2018 Yonas Kolb\n",
            bin_path + "XcodeGen_XcodeGenKit.bundle/Contents/Info.plist": b"fixture plist",
            bin_path + "XcodeGen_XcodeGenKit.bundle/Contents/Resources/SettingPresets/base.yml": b"fixture base",
            bin_path + "XcodeGen_XcodeGenKit.bundle/Contents/Resources/SettingPresets/Platforms/iOS.yml": b"fixture iOS",
        }

    def archive(self, extras=(), explicit_directories=False):
        path = self.root / "fixture.zip"
        entries = list(self.contents.items()) + list(extras)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as output:
            if explicit_directories:
                dirs = set()
                for name, _ in entries:
                    for parent in Path(name).parents:
                        if str(parent) != ".":
                            dirs.add(parent.as_posix() + "/")
                for name in sorted(dirs):
                    entry = zipfile.ZipInfo(name)
                    entry.create_system = 3
                    entry.external_attr = (stat.S_IFDIR | 0o755) << 16
                    output.writestr(entry, b"")
            for name, data in entries:
                if isinstance(name, zipfile.ZipInfo):
                    entry = name
                else:
                    entry = zipfile.ZipInfo(name)
                    # ZipInfo replaces Windows separators on Windows by default.
                    # Keep the original untrusted ZIP spelling for the boundary test.
                    entry.filename = name
                    entry.orig_filename = name
                    entry.create_system = 3
                    entry.external_attr = (stat.S_IFREG | 0o755) << 16
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", message="Duplicate name:.*", category=UserWarning)
                    output.writestr(entry, data)
        # Only this isolated test namespace accepts fixtures. Production has no bypass.
        self.ns["ARCHIVE_BYTES"] = path.stat().st_size
        self.ns["ARCHIVE_SHA256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.ns["BINARY_SHA256"] = hashlib.sha256(self.binary).hexdigest()
        return path

    def reject(self, path, message):
        self.rejection_count += 1
        destination = self.root / ("rejected-products-" + str(self.rejection_count))
        with self.assertRaisesRegex(ValueError, message):
            self.ns["extract_verified"](path, destination, "arm64")
        self.assertFalse(destination.exists(), "Rejected contents must not be extracted")

    def test_production_is_fixed_official_version_without_system_fallback(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertEqual(self.ns["VERSION"], "2.46.0")
        self.assertEqual(self.ns["ARCHIVE_BYTES"], 4286070)
        self.assertEqual(self.ns["ARCHIVE_SHA256"], "ef6d0a23bfb7393387f98e321ffd78a487231172e2e78c48d3c26275c263fd0c")
        self.assertEqual(self.ns["BINARY_SHA256"], "8774da746668bc18fe74e54cbaf10f2631a1fb05947cd374179aa912f14f99db")
        self.assertIn("https://github.com/yonaskolb/XcodeGen/releases/download/2.46.0/xcodegen.artifactbundle.zip", text)
        self.assertIn("--retry 2", text)
        self.assertIn("--max-time 90", text)
        self.assertIn("--retry-max-time 180", text)
        self.assertIn("lipo -verify_arch", text)
        self.assertIn('actual_version=$("$binary" --version)', text)
        self.assertNotIn("brew install", text)
        self.assertNotIn("sudo ", text)
        self.assertNotIn("command -v xcodegen", text)

    def test_valid_implicit_parents_preserve_license_and_all_adjacent_resources(self):
        path = self.archive()
        for architecture in ("arm64", "x86_64"):
            self.ns["inspect_archive"](path, architecture)
        destination = self.root / "products"
        self.ns["extract_verified"](path, destination, "arm64")
        actual = {p.relative_to(destination).as_posix(): p.read_bytes()
                  for p in destination.rglob("*") if p.is_file()}
        self.assertEqual(actual, self.contents)
        with zipfile.ZipFile(path) as source:
            self.assertEqual((source.getinfo(self.ns["BIN"] + "xcodegen").external_attr >> 16) & 0o777, 0o755)

    def test_valid_explicit_directories(self):
        path = self.archive(explicit_directories=True)
        self.ns["extract_verified"](path, self.root / "products", "x86_64")

    def test_hash_mismatch_is_rejected_before_extraction(self):
        path = self.archive()
        self.ns["ARCHIVE_SHA256"] = "0" * 64
        self.reject(path, "SHA256")

    def test_size_mismatch_is_rejected_before_extraction(self):
        path = self.archive()
        self.ns["ARCHIVE_BYTES"] += 1
        self.reject(path, "size")

    def test_nonordinary_archive_is_rejected_before_any_read(self):
        for kind in (stat.S_IFLNK, stat.S_IFIFO):
            path = Mock()
            path.lstat.return_value = SimpleNamespace(st_mode=kind | 0o600)
            with self.assertRaisesRegex(ValueError, "ordinary file"):
                self.ns["inspect_archive"](path, "arm64")
            path.read_bytes.assert_not_called()
            path.stat.assert_not_called()

    def test_unsafe_zip_paths_are_rejected_before_extraction(self):
        for name in (self.ns["BIN"] + "../../../escape", "/tmp/escape",
                     self.ns["BIN"] + "C:escape", self.ns["BIN"] + "a\\escape",
                     self.ns["BIN"] + "a//escape", self.ns["BIN"] + "a/./escape",
                     self.ns["BIN"] + "a\nescape"):
            with self.subTest(name=name):
                self.reject(self.archive([(name, b"untrusted")]), "artifact root|Unsafe artifact path")
        self.assertFalse((self.root / "escape").exists())

    def test_duplicate_and_case_colliding_paths_are_rejected(self):
        name = self.ns["BIN"] + "LICENSE"
        for candidate in (name, name.lower()):
            with self.subTest(candidate=candidate):
                self.reject(self.archive([(candidate, b"duplicate")]), "Duplicate artifact path")

    def test_link_fifo_and_privileged_member_modes_are_rejected(self):
        for mode in (stat.S_IFLNK | 0o777, stat.S_IFIFO | 0o600, stat.S_IFREG | 0o4755):
            entry = zipfile.ZipInfo(self.ns["BIN"] + "untrusted")
            entry.create_system = 3
            entry.external_attr = mode << 16
            with self.subTest(mode=mode):
                self.reject(self.archive([(entry, b"target")]), "Linked, special or privileged")

    def test_file_ancestor_is_rejected_with_controlled_error(self):
        name = self.ns["BIN"] + "XcodeGen_XcodeGenKit.bundle"
        self.reject(self.archive([(name, b"not a directory")]), "file ancestor")

    def test_missing_license_or_adjacent_resource_is_rejected(self):
        original = dict(self.contents)
        for name in (self.ns["BIN"] + "LICENSE",
                     self.ns["BIN"] + "XcodeGen_XcodeGenKit.bundle/Contents/Resources/SettingPresets/base.yml"):
            self.contents = dict(original)
            del self.contents[name]
            with self.subTest(name=name):
                self.reject(self.archive(), "license or adjacent resources")

    def test_wrong_version_or_architecture_metadata_is_rejected(self):
        for change in ("version", "variants"):
            original = json.loads(json.dumps(self.info))
            value = original["artifacts"]["xcodegen"]
            if change == "version":
                value["version"] = "2.45.0"
            else:
                value["variants"][0]["supportedTriples"] = ["x86_64-apple-macosx"]
            self.contents[self.ns["PREFIX"] + "info.json"] = json.dumps(original).encode()
            with self.subTest(change=change):
                self.reject(self.archive(), "version or type|architectures or path")

    def test_modified_binary_or_license_is_rejected(self):
        name = self.ns["BIN"] + "xcodegen"
        self.contents[name] = self.binary + b"changed"
        self.reject(self.archive(), "executable SHA256")
        self.contents[name] = self.binary
        self.contents[self.ns["BIN"] + "LICENSE"] = b"no original license"
        self.reject(self.archive(), "original MIT license")

    def test_existing_destination_is_never_overwritten(self):
        path = self.archive()
        destination = self.root / "existing"
        destination.mkdir()
        marker = destination / "unrelated-tool"
        marker.write_bytes(b"keep")
        with self.assertRaisesRegex(ValueError, "Refusing to replace"):
            self.ns["extract_verified"](path, destination, "arm64")
        self.assertEqual(marker.read_bytes(), b"keep")

    def test_invalid_macho_architecture_platform_or_bounds_is_rejected(self):
        cases = [(self.binary, "aarch64", "Unsupported architecture"),
                 (synthetic_macho(platform=2), "arm64", "macOS deployment"),
                 (b"not executable", "arm64", "universal Mach-O")]
        invalid_bounds = bytearray(self.binary)
        struct.pack_into(">I", invalid_bounds, 8 + 8, len(self.binary) + 1)
        cases.append((bytes(invalid_bounds), "arm64", "architecture bounds"))
        invalid_cpu = bytearray(self.binary)
        struct.pack_into("<I", invalid_cpu, 128 + 4, 0x1000007)
        cases.append((bytes(invalid_cpu), "arm64", "executable header"))
        for data, architecture, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    self.ns["validate_macho"](data, architecture)


if __name__ == "__main__":
    unittest.main()
