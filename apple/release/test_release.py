"""Release validation tests; no Xcode, signing credentials or uploads are used."""
import json
import os
from pathlib import Path
import plistlib
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import release


def native_class(owner, methods):
    """Small valid class files keep the release tests independent of a host JDK."""
    constants = []

    def utf8(value):
        data = value.encode("utf-8")
        constants.append(b"\x01" + struct.pack(">H", len(data)) + data)
        return len(constants)

    name = utf8(owner)
    constants.append(b"\x07" + struct.pack(">H", name))
    parent = utf8("java/lang/Object")
    constants.append(b"\x07" + struct.pack(">H", parent))
    encoded = []
    for method, descriptor in methods:
        encoded.append(struct.pack(">HHHH", 0x0101, utf8(method), utf8(descriptor), 0))
    return (struct.pack(">IHHH", 0xCAFEBABE, 0, 65, len(constants) + 1) + b"".join(constants)
            + struct.pack(">HHHHHH", 0x0021, 2, 4, 0, 0, len(methods)) + b"".join(encoded) + b"\0\0")


class EmbeddedReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.practice_source = self.root / "practice-source"
        self.practice_source.mkdir()
        for relative in ("index.html", "app.js", "style.css", "icons/note.svg"):
            file = self.practice_source / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes((relative + " practice fixture").encode())
        practice_patch = patch.object(release, "PRACTICE_SOURCE", self.practice_source)
        practice_patch.start()
        self.addCleanup(practice_patch.stop)
        self.build = self.root / "embedded-build"
        self.evidence = self.build / "evidence"
        self.project = self.build / "build.test/project"
        self.resources = self.project / "Generated/OMRResources"
        self.evidence.mkdir(parents=True)
        (self.project / "NoteLite.xcodeproj").mkdir(parents=True)
        (self.project / "EmbeddedRuntime").mkdir()
        for name in ("EmbeddedJVM.h", "EmbeddedJVM.mm"):
            (self.project / "EmbeddedRuntime" / name).write_text("JNI bridge fixture", encoding="utf-8")
        (self.project / "Generated").mkdir()
        (self.project / "Generated/native-symbols.c").write_text("void loadfunctions(void) {}", encoding="utf-8")
        self.archive = self.root / "native/libjvm.a"
        self.archive.parent.mkdir()
        self.archive.write_bytes(b"native archive fixture")
        self.headers = self.root / "native/include"
        self.headers.mkdir()
        for name in ("jni.h", "jni_md.h"):
            (self.headers / name).write_text("header fixture", encoding="utf-8")
        self.flags = '$(inherited) "-Wl,-force_load,' + self.archive.as_posix() + '"'
        self.config = ('ARCHS = arm64\nOTHER_LDFLAGS = ' + self.flags + '\nHEADER_SEARCH_PATHS = $(inherited) "'
                       + self.headers.as_posix() + '"\n')
        self.write_config(self.config)
        self.spec = {"targets": {"NoteLite": {
            "configFiles": {"Release": "Generated/native-libraries.xcconfig"},
            "settings": {"base": {
                "SWIFT_ACTIVE_COMPILATION_CONDITIONS": "$(inherited) EMBEDDED_OMR_RUNTIME",
                "SWIFT_OBJC_BRIDGING_HEADER": str(self.project / "EmbeddedRuntime/EmbeddedJVM.h"),
            }},
        }}}
        self.write_spec()
        (self.evidence / "project-location.txt").write_text(str(self.project), encoding="utf-8")
        for relative in release.REQUIRED_ENGINE_RESOURCES:
            file = self.resources / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes((relative + " fixture").encode())
        native = {"sdk": "iphoneos", "architecture": "arm64", "nativeArchives": [
            {"path": self.archive.as_posix(), "sha256": release.digest(self.archive)},
        ]}
        (self.resources / "build-inventory.json").write_text(json.dumps(native), encoding="utf-8")
        self.jar = self.resources / "java/engine.jar"
        self.jar.parent.mkdir()
        with zipfile.ZipFile(self.jar, "w") as jar:
            for name in release.REQUIRED_ENGINE_CLASSES:
                jar.writestr(name, b"class fixture")
        with zipfile.ZipFile(self.jar.parent / "tesseract-5.5.1-1.5.12.jar", "w") as jar:
            owner = "org/bytedeco/tesseract/TessBaseAPI"
            jar.writestr(owner + ".class", native_class(owner, [("allocate", "()V"), ("Init", "(I)I"), ("Init", "(J)I")]))
        with zipfile.ZipFile(self.jar.parent / "leptonica-1.85.0-1.5.12.jar", "w") as jar:
            owner = "org/bytedeco/leptonica/global/leptonica"
            jar.writestr(owner + ".class", native_class(owner, [("pixRead", "(J)J")]))
        self.native_symbols = ["Java_org_bytedeco_tesseract_TessBaseAPI_allocate",
                               "Java_org_bytedeco_tesseract_TessBaseAPI_Init__I",
                               "Java_org_bytedeco_tesseract_TessBaseAPI_Init__J",
                               "Java_org_bytedeco_leptonica_global_leptonica_pixRead"]
        self.inventory = {"sdk": "iphoneos", "architecture": "arm64", "embeddedRuntimeEnabled": True,
                          "deviceFamilies": [1, 2], "resources": []}
        self.refresh_inventory()
        self.environment = patch.dict(os.environ, {"RELEASE_EMBEDDED_BUILD": str(self.build)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.settings = [{"target": "NoteLite", "buildSettings": {
            "PLATFORM_NAME": "iphoneos", "ARCHS": "arm64",
            "SWIFT_ACTIVE_COMPILATION_CONDITIONS": "EMBEDDED_OMR_RUNTIME",
            "OTHER_LDFLAGS": self.flags,
            "OTHER_CPLUSPLUSFLAGS": "-O2 -fno-fast-math -ffp-contract=off",
            "STRIP_INSTALLED_PRODUCT": "NO", "COPY_PHASE_STRIP": "NO",
        }}]
        self.command_mock = patch.object(release, "run", side_effect=self.command)
        self.mock_run = self.command_mock.start()
        self.addCleanup(self.command_mock.stop)

    def write_spec(self):
        data = json.dumps(self.spec)
        for path in (self.project / "embedded-project.json", self.evidence / "embedded-project.json"):
            path.write_text(data, encoding="utf-8")

    def write_config(self, text):
        for path in (self.project / "Generated/native-libraries.xcconfig", self.evidence / "native-libraries.xcconfig"):
            path.write_text(text, encoding="utf-8")

    def refresh_inventory(self):
        self.inventory["resources"] = [{"path": p.relative_to(self.resources).as_posix(),
                                        "bytes": p.stat().st_size, "sha256": release.digest(p)}
                                       for p in sorted(self.resources.rglob("*")) if p.is_file()]
        self.write_inventory()

    def write_inventory(self):
        (self.evidence / "app-inventory.json").write_text(json.dumps(self.inventory), encoding="utf-8")

    def command(self, arguments, *, capture=False):
        if "-showBuildSettings" in arguments:
            return json.dumps(self.settings)
        if "lipo" in arguments:
            return ""
        if "vtool" in arguments:
            return "platform IOS\nminos 16.0\n"
        if "nm" in arguments:
            return "\n".join("00000000 T _" + name for name in (*release.NATIVE_ENGINE_ENTRIES, *self.native_symbols))
        self.fail("Unexpected external command: " + repr(arguments))

    def make_archived_app(self):
        app = self.root / "archive/Products/Applications/NoteLite.app"
        app.mkdir(parents=True)
        shutil.copytree(self.resources, app / "OMRResources")
        shutil.copytree(self.practice_source, app / "practice")
        (app / "Assets.car").write_bytes(b"compiled asset catalog fixture")
        (app / "NoteLite").write_bytes(b"executable fixture")
        (app / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundleExecutable": "NoteLite", "UIDeviceFamily": [1, 2],
            "CFBundleIdentifier": "com.example.notelite", "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "7", "CFBundleSupportedPlatforms": ["iPhoneOS"], "DTSDKName": "iphoneos26.5",
        }))
        return app

    def make_ipa(self, app, transform=None):
        ipa = self.root / "export.ipa"
        with zipfile.ZipFile(ipa, "w") as archive:
            for file in app.rglob("*"):
                if not file.is_file():
                    continue
                relative = file.relative_to(app).as_posix()
                data = file.read_bytes()
                if transform:
                    data = transform(relative, data)
                if data is not None:
                    archive.writestr("Payload/NoteLite.app/" + relative, data)
        return ipa

    def verify_ipa(self, ipa, composition, app):
        private = self.root / "ipa-private"
        private.mkdir(exist_ok=True)
        release.verify_exported_ipa(ipa, composition, private, self.root,
                                    plistlib.loads((app / "Info.plist").read_bytes()))

    def test_complete_composition_and_archived_app_pass(self):
        composition = release.embedded_build()
        self.assertEqual(composition["project"], (self.project / "NoteLite.xcodeproj").resolve())
        app = self.make_archived_app()
        release.verify_embedded_archive(app, composition, self.root)
        report = json.loads((self.root / "embedded-archive-inventory.json").read_text(encoding="utf-8"))
        self.assertTrue(report["embeddedRuntimeEnabled"])
        self.assertEqual(report["resources"], self.inventory["resources"])
        self.assertEqual(report["compositionInventorySHA256"], release.digest(self.evidence / "app-inventory.json"))
        self.assertEqual(report["practiceResourceCount"], 4)
        self.assertEqual(report["assetCatalogSHA256"], release.digest(app / "Assets.car"))
        self.assertEqual(report["nativeCPlusPlusFlags"], ["-O2", "-fno-fast-math", "-ffp-contract=off"])
        bindings = report["nativePresetBindings"]
        self.assertTrue(bindings["passed"])
        self.assertEqual(bindings["linked"]["nativeDeclarations"], 4)
        self.assertEqual(bindings["linked"]["nativeClasses"], 2)
        self.assertEqual(len(bindings["jars"]), 2)

    def test_missing_build_never_falls_back_to_baseline(self):
        with patch.dict(os.environ, {"RELEASE_EMBEDDED_BUILD": ""}):
            with self.assertRaisesRegex(release.ReleaseError, "RELEASE_EMBEDDED_BUILD"):
                release.embedded_build()
        self.mock_run.assert_not_called()

    def test_simulator_composition_cannot_be_released(self):
        self.inventory["sdk"] = "iphonesimulator"
        self.write_inventory()
        with self.assertRaisesRegex(release.ReleaseError, "iphoneos/arm64"):
            release.embedded_build()
        self.mock_run.assert_not_called()

    def test_project_outside_composition_is_rejected(self):
        (self.evidence / "project-location.txt").write_text(str(self.root), encoding="utf-8")
        with self.assertRaisesRegex(release.ReleaseError, "belong to this embedded build"):
            release.embedded_build()

    def test_generated_configuration_must_match_evidence(self):
        (self.project / "Generated/native-libraries.xcconfig").write_text("ARCHS = x86_64", encoding="utf-8")
        with self.assertRaisesRegex(release.ReleaseError, "differs from its evidence"):
            release.embedded_build()

    def test_disabled_engine_flag_is_rejected(self):
        self.spec["targets"]["NoteLite"]["settings"]["base"]["SWIFT_ACTIVE_COMPILATION_CONDITIONS"] = ""
        self.write_spec()
        with self.assertRaisesRegex(release.ReleaseError, "does not enable"):
            release.embedded_build()

    def test_native_archive_mutation_is_rejected(self):
        self.archive.write_bytes(b"changed native library")
        with self.assertRaisesRegex(release.ReleaseError, "native archive changed"):
            release.embedded_build()

    def test_native_link_configuration_must_use_verified_archives(self):
        self.write_config(self.config.replace(self.archive.as_posix(), self.archive.as_posix() + "other.a"))
        with self.assertRaisesRegex(release.ReleaseError, "archive provenance"):
            release.embedded_build()

    def test_resource_manifest_cannot_escape_bundle(self):
        self.inventory["resources"][0]["path"] = "../outside"
        self.write_inventory()
        with self.assertRaisesRegex(release.ReleaseError, "escapes"):
            release.embedded_build()

    def test_changed_and_unlisted_resources_are_rejected(self):
        file = self.resources / "assets/Bravura.otf"
        original = file.read_bytes()
        file.write_bytes(b"changed")
        with self.assertRaisesRegex(release.ReleaseError, "differs from composition"):
            release.embedded_build()
        file.write_bytes(original)
        (self.resources / "unexpected.dat").write_bytes(b"extra")
        with self.assertRaisesRegex(release.ReleaseError, "complete composition inventory"):
            release.embedded_build()

    def test_inventory_cannot_omit_runtime_or_notices(self):
        for name in ("runtime/lib/modules", "licenses/fonts/MakeMusic-OFL.txt"):
            with self.subTest(name=name):
                file = self.resources / name
                data = file.read_bytes()
                file.unlink()
                self.refresh_inventory()
                with self.assertRaisesRegex(release.ReleaseError, "required engine resources"):
                    release.embedded_build()
                file.write_bytes(data)
                self.refresh_inventory()

    def test_missing_engine_class_is_rejected_even_with_new_resource_hash(self):
        with zipfile.ZipFile(self.jar, "w") as jar:
            jar.writestr("unrelated.class", b"class fixture")
        self.refresh_inventory()
        with self.assertRaisesRegex(release.ReleaseError, "lacks the engine"):
            release.embedded_build()

    def test_effective_xcode_settings_cannot_drop_engine_or_native_libraries(self):
        settings = self.settings[0]["buildSettings"]
        for key, invalid in (("SWIFT_ACTIVE_COMPILATION_CONDITIONS", ""), ("PLATFORM_NAME", "iphonesimulator"),
                             ("ARCHS", "x86_64"), ("OTHER_LDFLAGS", "")):
            with self.subTest(setting=key):
                original = settings[key]
                settings[key] = invalid
                with self.assertRaises(release.ReleaseError):
                    release.embedded_build()
                settings[key] = original

    def test_actual_archive_missing_resource_is_rejected(self):
        composition = release.embedded_build()
        app = self.make_archived_app()
        (app / "OMRResources/tessdata/eng.traineddata").unlink()
        with self.assertRaisesRegex(release.ReleaseError, "Missing or escaped"):
            release.verify_embedded_archive(app, composition, self.root)
        self.assertFalse((self.root / "embedded-archive-inventory.json").exists())

    def test_effective_embedded_cpp_settings_require_all_kernel_flags(self):
        settings = self.settings[0]["buildSettings"]
        original = settings["OTHER_CPLUSPLUSFLAGS"]
        for missing in ("-O2", "-fno-fast-math", "-ffp-contract=off"):
            with self.subTest(missing=missing):
                settings["OTHER_CPLUSPLUSFLAGS"] = original.replace(missing, "")
                with self.assertRaisesRegex(release.ReleaseError, "Embedded C\\+\\+ settings must include"):
                    release.embedded_build()
        settings["OTHER_CPLUSPLUSFLAGS"] = original

    def test_effective_embedded_cpp_settings_reject_later_conflicting_flags(self):
        settings = self.settings[0]["buildSettings"]
        original = settings["OTHER_CPLUSPLUSFLAGS"]
        for override in ("-O0", "-O3", "-Os", "-Ofast", "-ffast-math", "-ffp-contract=fast",
                         "-ffp-contract=on", "-ffp-model=fast", "-funsafe-math-optimizations",
                         "-fassociative-math", "-freciprocal-math", "-ffinite-math-only"):
            with self.subTest(override=override):
                settings["OTHER_CPLUSPLUSFLAGS"] = original + " " + override
                with self.assertRaisesRegex(release.ReleaseError, "conflicting optimization or floating-point"):
                    release.embedded_build()
        settings["OTHER_CPLUSPLUSFLAGS"] = original

    def test_effective_embedded_cpp_settings_preserve_unrelated_compiler_flags(self):
        settings = self.settings[0]["buildSettings"]
        settings["OTHER_CPLUSPLUSFLAGS"] += ' -DPORT_ENABLED=1 -Wextra -I"/tmp/SDK Includes"'
        composition = release.embedded_build()
        self.assertIn("-DPORT_ENABLED=1", composition["nativeCPlusPlusFlags"])
        self.assertIn("-I/tmp/SDK Includes", composition["nativeCPlusPlusFlags"])

    def test_archive_stripping_cannot_remove_dynamic_jni_exports(self):
        settings = self.settings[0]["buildSettings"]
        for key in ("STRIP_INSTALLED_PRODUCT", "COPY_PHASE_STRIP"):
            with self.subTest(setting=key):
                settings[key] = "YES"
                with self.assertRaisesRegex(release.ReleaseError, "preserve native exports"):
                    release.embedded_build()
                settings[key] = "NO"

    def test_actual_archive_missing_jni_symbol_is_rejected(self):
        composition = release.embedded_build()
        app = self.make_archived_app()
        previous = self.command
        self.mock_run.side_effect = lambda args, **kwargs: "" if "nm" in args else previous(args, **kwargs)
        with self.assertRaisesRegex(release.ReleaseError, "JNI entry points"):
            release.verify_embedded_archive(app, composition, self.root)

    def test_archive_rejects_missing_tesseract_constructor_with_all_entry_points_present(self):
        composition = release.embedded_build()
        app = self.make_archived_app()
        self.native_symbols.remove("Java_org_bytedeco_tesseract_TessBaseAPI_allocate")
        with self.assertRaisesRegex(release.ReleaseError, "native preset bindings"):
            release.verify_embedded_archive(app, composition, self.root)
        proof = json.loads((self.root / "embedded-archive-jni-bindings.json").read_text())
        self.assertFalse(proof["passed"])
        self.assertEqual([item["method"] for item in proof["linked"]["missing"]], ["allocate"])
        self.assertFalse((self.root / "embedded-archive-inventory.json").exists())

    def test_actual_archive_missing_practice_resource_is_rejected(self):
        composition = release.embedded_build()
        app = self.make_archived_app()
        (app / "practice/icons/note.svg").unlink()
        with self.assertRaisesRegex(release.ReleaseError, "Missing or escaped embedded file: icons/note.svg"):
            release.verify_embedded_archive(app, composition, self.root)
        self.assertFalse((self.root / "embedded-archive-inventory.json").exists())

    def test_actual_archive_changed_practice_resource_is_rejected(self):
        composition = release.embedded_build()
        app = self.make_archived_app()
        (app / "practice/app.js").write_bytes(b"stale practice renderer")
        with self.assertRaisesRegex(release.ReleaseError, "practice resource differs from its source: app.js"):
            release.verify_embedded_archive(app, composition, self.root)

    def test_actual_archive_missing_asset_catalog_is_rejected(self):
        composition = release.embedded_build()
        app = self.make_archived_app()
        (app / "Assets.car").unlink()
        with self.assertRaisesRegex(release.ReleaseError, "Missing or escaped embedded file: Assets.car"):
            release.verify_embedded_archive(app, composition, self.root)

    def test_actual_archive_simulator_macho_is_rejected(self):
        composition = release.embedded_build()
        app = self.make_archived_app()
        previous = self.command
        self.mock_run.side_effect = lambda args, **kwargs: "platform IOSSIMULATOR" if "vtool" in args else previous(args, **kwargs)
        with self.assertRaisesRegex(release.ReleaseError, "not an iOS device binary"):
            release.verify_embedded_archive(app, composition, self.root)

    def test_exported_ipa_passes_and_keeps_separate_archive_proof(self):
        composition = release.embedded_build()
        app = self.make_archived_app()
        release.verify_embedded_archive(app, composition, self.root)
        original_proof = (self.root / "embedded-archive-inventory.json").read_bytes()
        self.verify_ipa(self.make_ipa(app), composition, app)
        proof = json.loads((self.root / "embedded-ipa-inventory.json").read_text(encoding="utf-8"))
        self.assertEqual(proof["bundleIdentifier"], "com.example.notelite")
        self.assertEqual(proof["version"], "1.0.0")
        self.assertEqual(proof["build"], "7")
        self.assertTrue(proof["nativePresetBindings"]["passed"])
        self.assertTrue((self.root / "embedded-ipa-jni-bindings.json").is_file())
        self.assertEqual((self.root / "embedded-archive-inventory.json").read_bytes(), original_proof)

    def test_exported_ipa_missing_engine_resource_fails(self):
        composition = release.embedded_build()
        app = self.make_archived_app()
        ipa = self.make_ipa(app, lambda name, data: None if name == "OMRResources/runtime/lib/modules" else data)
        with self.assertRaisesRegex(release.ReleaseError, "Missing or escaped"):
            self.verify_ipa(ipa, composition, app)
        self.assertFalse((self.root / "embedded-ipa-inventory.json").exists())

    def test_exported_ipa_changed_practice_resource_fails(self):
        composition = release.embedded_build()
        app = self.make_archived_app()
        ipa = self.make_ipa(app, lambda name, data: b"changed" if name == "practice/app.js" else data)
        with self.assertRaisesRegex(release.ReleaseError, "practice resource differs"):
            self.verify_ipa(ipa, composition, app)

    def test_exported_ipa_changed_bundle_identity_fails(self):
        composition = release.embedded_build()
        app = self.make_archived_app()

        def renamed(name, data):
            if name == "Info.plist":
                info = plistlib.loads(data)
                info["CFBundleIdentifier"] = "com.example.other"
                return plistlib.dumps(info)
            return data

        with self.assertRaisesRegex(release.ReleaseError, "identity/version differs"):
            self.verify_ipa(self.make_ipa(app, renamed), composition, app)

    def test_exported_ipa_lost_native_exports_fails(self):
        composition = release.embedded_build()
        app = self.make_archived_app()
        previous = self.command
        self.mock_run.side_effect = lambda args, **kwargs: "" if "nm" in args else previous(args, **kwargs)
        with self.assertRaisesRegex(release.ReleaseError, "JNI entry points"):
            self.verify_ipa(self.make_ipa(app), composition, app)

    def test_exported_ipa_rejects_missing_tesseract_overload_even_with_short_alias(self):
        composition = release.embedded_build()
        app = self.make_archived_app()
        self.native_symbols.remove("Java_org_bytedeco_tesseract_TessBaseAPI_Init__J")
        self.native_symbols.append("Java_org_bytedeco_tesseract_TessBaseAPI_Init")
        with self.assertRaisesRegex(release.ReleaseError, "native preset bindings"):
            self.verify_ipa(self.make_ipa(app), composition, app)
        proof = json.loads((self.root / "embedded-ipa-jni-bindings.json").read_text())
        self.assertFalse(proof["passed"])
        missing = proof["linked"]["missing"]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["method"], "Init")
        self.assertEqual(missing[0]["descriptor"], "(J)I")
        self.assertTrue(missing[0]["requiresLongName"])
        self.assertFalse((self.root / "embedded-ipa-inventory.json").exists())

    def test_exported_ipa_cannot_write_outside_verification_directory(self):
        composition = release.embedded_build()
        app = self.make_archived_app()
        ipa = self.make_ipa(app)
        with zipfile.ZipFile(ipa, "a") as archive:
            archive.writestr("../outside", b"unexpected")
        with self.assertRaisesRegex(release.ReleaseError, "invalid ZIP path"):
            self.verify_ipa(ipa, composition, app)
        self.assertFalse((self.root / "ipa-private/outside").exists())

    def test_invalid_embedded_archive_stops_before_export_or_upload(self):
        app = self.make_archived_app()
        (app / "OMRResources/runtime/lib/modules").unlink()
        private, output = self.root / "private", self.root / "output"
        previous = self.command

        def commands(arguments, **kwargs):
            if arguments[:2] == ["xcodebuild", "archive"]:
                destination = Path(arguments[arguments.index("-archivePath") + 1]) / "Products/Applications/NoteLite.app"
                shutil.copytree(app, destination)
                return ""
            return previous(arguments, **kwargs)

        self.mock_run.side_effect = commands
        with patch.object(release, "settings", return_value=("export", False, "com.example.notelite", "TESTTEAM00", "1.0.0", "7")), \
                patch.object(release, "paths", return_value=(private, output)), \
                patch.object(release, "install_signing", return_value=("test-profile", "test-fingerprint")), \
                patch.object(release, "cleanup") as cleanup:
            with self.assertRaisesRegex(release.ReleaseError, "Missing or escaped"):
                release.archive()
        cleanup.assert_called_once()
        self.assertFalse(any("-exportArchive" in call.args[0] or "altool" in call.args[0]
                             for call in self.mock_run.call_args_list))
        archive_call = next(call.args[0] for call in self.mock_run.call_args_list if "archive" in call.args[0])
        self.assertEqual(archive_call[archive_call.index("-project") + 1], str((self.project / "NoteLite.xcodeproj").resolve()))


if __name__ == "__main__":
    unittest.main()
