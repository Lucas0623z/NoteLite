"""Synthetic Mach-O regression fixtures; no native signature success is claimed."""
import plistlib
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

from verify_simulator_identity import IdentityError, inspect_installed_app, macho_evidence


IDENTIFIER = "G74YSFJX76.com.lucas0623z.yinban"
IDENTITY = {"application-identifier": IDENTIFIER}


def name(value):
    return value.encode().ljust(16, b"\0")


def image(identity=None, dependencies=(), file_type=2, duplicate=False, der=None):
    payloads = []
    if identity is not None:
        payloads += [("__entitlements", plistlib.dumps(identity))] * (2 if duplicate else 1)
    if der is not None:
        payloads.append(("__ents_der", der))
    count = len(payloads)
    dependency_commands = []
    for dependency in dependencies:
        text = dependency.encode() + b"\0"
        text += b"\0" * (-(24 + len(text)) % 8)
        dependency_commands.append(struct.pack("<6I", 0xC, 24 + len(text), 24, 0, 0, 0) + text)
    command_size = 72 + count * 80
    commands_bytes = command_size + sum(map(len, dependency_commands))
    start = 32 + commands_bytes
    payload = b"".join(raw for _, raw in payloads)
    segment = struct.pack("<2I16s4Q4I", 0x19, command_size, name("__TEXT"), 0, start + len(payload),
                          0, start + len(payload), 7, 5, count, 0)
    position = start
    for section_name, raw in payloads:
        segment += struct.pack("<16s16s2Q8I", name(section_name), name("__TEXT"),
                               position, len(raw), position, 0, 0, 0, 0, 0, 0, 0)
        position += len(raw)
    header = struct.pack("<8I", 0xFEEDFACF, 0x0100000C, 0, file_type,
                         len(dependency_commands) + 1, commands_bytes, 0, 0)
    return header + segment + b"".join(dependency_commands) + payload


def make_app(root, main, debug=None):
    bundle = root / "synthetic.app"
    bundle.mkdir()
    (bundle / "Info.plist").write_bytes(plistlib.dumps({"CFBundleExecutable": "Fixture",
                                                       "CFBundleIdentifier": "com.lucas0623z.yinban"}))
    (bundle / "Fixture").write_bytes(main)
    if debug is not None:
        (bundle / "Fixture.debug.dylib").write_bytes(debug)
    return bundle


class InstalledSimulatorIdentityTests(unittest.TestCase):
    def test_actual_der_must_equal_official_encoding_of_the_same_actual_xml_bytes(self):
        xml = plistlib.dumps(IDENTITY)
        der = b"synthetic-DER-fixture"
        with tempfile.TemporaryDirectory() as directory:
            bundle = make_app(Path(directory), image(IDENTITY, der=der))
            received = []
            def encoder(actual_xml):
                received.append(actual_xml)
                return der
            proof = inspect_installed_app(bundle, IDENTIFIER, lambda _: None, encoder)
            self.assertEqual(received, [xml])
            self.assertTrue(proof["identitySources"][1]["officialEncoderByteEqualityVerified"])
            with self.assertRaisesRegex(IdentityError, "contradict"):
                inspect_installed_app(bundle, IDENTIFIER, lambda _: None, lambda _: b"different-DER")
            with self.assertRaises(IdentityError):
                inspect_installed_app(bundle, IDENTIFIER, lambda _: None)

    def test_der_only_or_empty_der_cannot_be_treated_as_an_xml_identity(self):
        for main in (image(der=b"DER-without-XML"), image(IDENTITY, der=b"")):
            with self.subTest(size=len(main)), tempfile.TemporaryDirectory() as directory:
                bundle = make_app(Path(directory), main)
                with self.assertRaises(IdentityError):
                    inspect_installed_app(bundle, IDENTIFIER, lambda _: None, lambda _: b"synthetic")

    def test_main_embedded_identity_requires_both_bundle_and_executable_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = make_app(Path(directory), image(IDENTITY))
            calls = []
            proof = inspect_installed_app(bundle, IDENTIFIER, lambda path: calls.append(path))
            self.assertEqual(calls, [bundle, bundle / "Fixture"])
            self.assertTrue(proof["installedMachOIdentityVerified"])
            self.assertFalse(proof["signatureEntitlementBlobPresent"])
            self.assertEqual(proof["identitySources"][0]["image"], "Fixture")

    def test_actual_linked_debug_image_is_verified_and_read_instead_of_guessing_a_path(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = make_app(Path(directory), image(dependencies=["@rpath/Fixture.debug.dylib"]),
                              image(IDENTITY, file_type=6))
            calls = []
            proof = inspect_installed_app(bundle, IDENTIFIER, lambda path: calls.append(path))
            self.assertEqual(calls, [bundle, bundle / "Fixture", bundle / "Fixture.debug.dylib"])
            self.assertEqual(proof["identitySources"][0]["image"], "Fixture.debug.dylib")
            self.assertEqual(len(proof["verifiedImages"]), 2)

    def test_empty_signatures_and_an_unlinked_debug_file_cannot_supply_missing_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = make_app(Path(directory), image(), image(IDENTITY, file_type=6))
            with self.assertRaisesRegex(IdentityError, "No actual installed"):
                inspect_installed_app(bundle, IDENTIFIER, lambda _: None)

    def test_signature_failure_cannot_be_overridden_by_a_valid_section(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = make_app(Path(directory), image(IDENTITY))
            def failure(path):
                raise subprocess.CalledProcessError(1, ["codesign", "--verify", "--strict", str(path)])
            with self.assertRaises(subprocess.CalledProcessError):
                inspect_installed_app(bundle, IDENTIFIER, failure)

    def test_contradictory_signed_identifier_or_sharing_groups_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = make_app(Path(directory), image(IDENTITY))
            for identity in ({"application-identifier": "WRONG.com.lucas0623z.yinban"},
                             {**IDENTITY, "keychain-access-groups": ["G74YSFJX76.other"]},
                             {**IDENTITY, "keychain-access-groups": [IDENTIFIER]},
                             {**IDENTITY, "com.apple.security.application-groups": ["shared"]}):
                with self.subTest(identity=identity), self.assertRaises(IdentityError):
                    inspect_installed_app(bundle, IDENTIFIER, lambda _: identity)

    def test_empty_missing_or_wrong_embedded_identity_is_rejected(self):
        for identity in ({}, {"unrelated": True}, {"application-identifier": "wrong"},
                         {**IDENTITY, "keychain-access-groups": True}):
            with self.subTest(identity=identity), tempfile.TemporaryDirectory() as directory:
                bundle = make_app(Path(directory), image(identity))
                with self.assertRaises(IdentityError):
                    inspect_installed_app(bundle, IDENTIFIER, lambda _: None)

    def test_duplicate_sections_and_truncated_or_out_of_bounds_commands_are_rejected(self):
        for data in (image(IDENTITY, duplicate=True), image(IDENTITY)[:40], image(IDENTITY)[:-5]):
            with self.subTest(size=len(data)), self.assertRaises(IdentityError):
                macho_evidence(data)
        corrupt = bytearray(image(IDENTITY))
        struct.pack_into("<I", corrupt, 32 + 72 + 48, 0)
        with self.assertRaises(IdentityError):
            macho_evidence(corrupt)

    def test_unexpected_debug_path_or_missing_linked_binary_is_rejected(self):
        for dependency in ("@rpath/../Fixture.debug.dylib", "@rpath/Fixture.debug.dylib"):
            with self.subTest(dependency=dependency), tempfile.TemporaryDirectory() as directory:
                bundle = make_app(Path(directory), image(IDENTITY, dependencies=[dependency]))
                with self.assertRaises(IdentityError):
                    inspect_installed_app(bundle, IDENTIFIER, lambda _: None)

    def test_two_conflicting_linked_images_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = make_app(Path(directory), image(IDENTITY, dependencies=[
                "@rpath/Fixture.debug.dylib", "@rpath/Other.debug.dylib"]))
            with self.assertRaises(IdentityError):
                inspect_installed_app(bundle, IDENTIFIER, lambda _: None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
