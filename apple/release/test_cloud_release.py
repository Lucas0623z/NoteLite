"""Release gates: no private signing credentials, model inference or Apple uploads."""
import datetime as dt
import hashlib
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import cloud_release as cloud

SHA = "a" * 40
SETTINGS = {"RELEASE_MODE": "verify", "RELEASE_UPLOAD": "false", "RELEASE_BUNDLE_ID": cloud.BUNDLE,
            "RELEASE_TEAM_ID": cloud.TEAM, "RELEASE_VERSION": "1.0.0", "RELEASE_BUILD_NUMBER": "12",
            "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/release"}


def successful_run():
    return {"path": cloud.WORKFLOW, "status": "completed", "conclusion": "success", "head_sha": SHA, "run_attempt": 2}


def successful_jobs():
    return [{"name": name, "status": "completed", "conclusion": "success", "head_sha": SHA, "run_attempt": 2}
            for name, _ in cloud.PLATFORMS.values()]


def test_tree(platform):
    return {"testNodes": [{"nodeType": "Test Plan", "name": "All Tests", "result": "Passed", "children": [
        {"nodeType": "Test Case", "name": name.split("/")[-1] + "()", "nodeIdentifier": name + "()", "result": "Passed"}
        for name in sorted(cloud.required_tests(platform))]}]}


class AcceptanceGateTests(unittest.TestCase):
    def test_export_requires_exact_registered_identity_manual_dispatch_and_upload_opt_in(self):
        with patch.dict(os.environ, SETTINGS, clear=True):
            self.assertEqual(cloud.settings()[:2], ("verify", False))
            os.environ["RELEASE_UPLOAD"] = "true"
            with self.assertRaises(cloud.release.ReleaseError): cloud.settings()
            os.environ["RELEASE_MODE"] = "export"
            self.assertEqual(cloud.settings()[:2], ("export", True))
            for key, value in (("GITHUB_EVENT_NAME", "push"), ("GITHUB_REF", "refs/pull/12/merge"),
                               ("RELEASE_BUNDLE_ID", "com.example.stolen"), ("RELEASE_TEAM_ID", "AAAAAAAAAA")):
                with patch.dict(os.environ, {key: value}):
                    with self.assertRaises(cloud.release.ReleaseError): cloud.settings()

    def test_workflow_green_is_insufficient_without_all_three_current_attempt_native_jobs(self):
        cloud.validate_native_run(successful_run(), successful_jobs(), SHA)
        for key, value in (("head_sha", "b" * 40), ("path", ".github/workflows/app-store-release.yml"),
                           ("conclusion", "failure"), ("status", "in_progress")):
            with self.subTest(key=key):
                with self.assertRaises(cloud.release.ReleaseError):
                    cloud.validate_native_run({**successful_run(), key: value}, successful_jobs(), SHA)
        for key, value in (("run_attempt", 1), ("head_sha", "b" * 40), ("conclusion", "skipped")):
            jobs = successful_jobs(); jobs[2][key] = value
            with self.assertRaises(cloud.release.ReleaseError): cloud.validate_native_run(successful_run(), jobs, SHA)
        with self.assertRaises(cloud.release.ReleaseError): cloud.validate_native_run(successful_run(), successful_jobs()[:2], SHA)

    def test_each_platform_must_contain_actual_passed_leaf_results_including_coreml(self):
        for platform in cloud.PLATFORMS:
            tree = test_tree(platform)
            summary = {"result": "Passed", "failedTests": 0, "passedTests": len(cloud.required_tests(platform))}
            result = cloud.validate_test_results(platform, tree, summary)
            self.assertIn("NoteWiseRecordedTranscriptionTests/testActualBundledCoreMLTranscribesChordAndLaterRepeatedPitch", result["actualResults"])
            for status in ("Skipped", "Failed", None):
                tree["testNodes"][0]["children"][0]["result"] = status
                with self.assertRaises(cloud.release.ReleaseError): cloud.validate_test_results(platform, tree, summary)
            tree = test_tree(platform); tree["testNodes"][0]["children"].pop()
            with self.assertRaises(cloud.release.ReleaseError): cloud.validate_test_results(platform, tree, summary)
            with self.assertRaises(cloud.release.ReleaseError): cloud.validate_test_results(platform, test_tree(platform), {**summary, "failedTests": 1})

    def test_suite_status_or_duplicate_leaf_cannot_fake_native_acceptance(self):
        with self.assertRaises(cloud.release.ReleaseError):
            cloud.test_outcomes({"testNodes": [{"nodeType": "Test Suite", "name": "FigmaShellUITests", "result": "Passed"}]})
        tree = test_tree("iPad"); tree["testNodes"][0]["children"].append(tree["testNodes"][0]["children"][0])
        with self.assertRaises(cloud.release.ReleaseError): cloud.test_outcomes(tree)
        nested = {"testNodes": [{"nodeType": "Test Suite", "name": "NoteWiseRecordedTranscriptionTests", "children": [
            {"nodeType": "Test Case", "name": "testActualBundledCoreMLSilenceDoesNotBecomeCorrectNotes()", "result": "Passed"}]}]}
        self.assertEqual(cloud.test_outcomes(nested), {"NoteWiseRecordedTranscriptionTests/testActualBundledCoreMLSilenceDoesNotBecomeCorrectNotes": "Passed"})

    def test_actual_public_account_lifecycle_cannot_be_missing_skipped_or_failed_on_any_platform(self):
        for platform in cloud.PLATFORMS:
            with self.subTest(platform=platform):
                required = cloud.required_tests(platform)
                self.assertIn(cloud.LIVE_ACCOUNT_TEST, required)
                summary = {"result": "Passed", "failedTests": 0, "passedTests": len(required)}
                tree = test_tree(platform)
                leaves = tree["testNodes"][0]["children"]
                actual = next(leaf for leaf in leaves if leaf["nodeIdentifier"] == cloud.LIVE_ACCOUNT_TEST + "()")
                self.assertEqual(cloud.validate_test_results(platform, tree, summary)["actualResults"][cloud.LIVE_ACCOUNT_TEST], "Passed")
                # Other test leaves and even the parent bundle stay green: a
                # test opt-in that was skipped must never permit signing.
                for status in ("Skipped", "Failed", "Unknown", "In Progress", None):
                    actual["result"] = status
                    with self.assertRaises(cloud.release.ReleaseError):
                        cloud.validate_test_results(platform, tree, summary)
                leaves.remove(actual)
                with self.assertRaises(cloud.release.ReleaseError):
                    cloud.validate_test_results(platform, tree, summary)
        nested = {"testNodes": [{"nodeType": "Test Suite", "name": "CloudAccountLiveLifecycleTests", "children": [
            {"nodeType": "Test Case", "name": cloud.LIVE_ACCOUNT_TEST.split("/")[-1] + "()", "result": "Passed"}]}]}
        self.assertEqual(cloud.test_outcomes(nested), {cloud.LIVE_ACCOUNT_TEST: "Passed"})

    def test_added_inference_legal_resource_and_recording_tail_regressions_are_required_on_every_platform(self):
        original_read = Path.read_text
        for suite in ("NoteWiseRecordedTranscriptionTests", "FigmaLegalInformationTests", "NoteWiseStopTailTests"):
            name = suite + "/testAdditionalActualAcceptance"
            def source_with_added_test(path, *args, **kwargs):
                source = original_read(path, *args, **kwargs)
                return source + "\nfunc testAdditionalActualAcceptance() throws {}\n" if path.name == suite + ".swift" else source
            with patch.object(Path, "read_text", source_with_added_test):
                for platform in cloud.PLATFORMS:
                    self.assertIn(name, cloud.required_tests(platform))
                    tree = test_tree(platform)
                    summary = {"result": "Passed", "failedTests": 0, "passedTests": len(cloud.required_tests(platform))}
                    self.assertEqual(cloud.validate_test_results(platform, tree, summary)["actualResults"][name], "Passed")
                    leaves = tree["testNodes"][0]["children"]
                    actual = next(leaf for leaf in leaves if leaf["nodeIdentifier"] == name + "()")
                    actual["result"] = "Skipped"
                    with self.assertRaises(cloud.release.ReleaseError):
                        cloud.validate_test_results(platform, tree, summary)
                    leaves.remove(actual)
                    with self.assertRaises(cloud.release.ReleaseError):
                        cloud.validate_test_results(platform, tree, summary)

    def test_installed_legal_resources_and_recording_tail_leaf_results_are_recognized_without_identifiers(self):
        legal = "FigmaLegalInformationTests/testActualInstalledAppHasReadableFullLicenseNoticeAndCommitSourceOffer"
        for platform in cloud.PLATFORMS:
            self.assertIn(legal, cloud.required_tests(platform))
            for suite in ("FigmaLegalInformationTests", "NoteWiseStopTailTests"):
                names = sorted(name for name in cloud.required_tests(platform) if name.startswith(suite + "/"))
                self.assertTrue(names, suite)
                nested = {"testNodes": [{"nodeType": "Test Suite", "name": suite, "result": "Passed", "children": [
                    {"nodeType": "Test Case", "name": name.split("/")[-1] + "()", "result": "Passed"} for name in names]}]}
                self.assertEqual(cloud.test_outcomes(nested), {name: "Passed" for name in names})
                for result in ("Skipped", "Failed", None):
                    nested["testNodes"][0]["children"][0]["result"] = result
                    self.assertEqual(cloud.test_outcomes(nested)[names[0]], result)

    def test_account_identity_profile_and_recording_regressions_cannot_be_missing_or_skipped(self):
        for platform in cloud.PLATFORMS:
            required = cloud.required_tests(platform)
            for suite in ("CloudAccountTests", "FigmaCloudRequestIdentityTests", "NoteWiseRecordingStatusTests",
                          "FigmaLegalInformationTests", "NoteWiseStopTailTests"):
                names = sorted(name for name in required if name.startswith(suite + "/"))
                self.assertTrue(names, suite)
                for name in names:
                    for outcome in ("Skipped", None):
                        tree = test_tree(platform)
                        leaves = tree["testNodes"][0]["children"]
                        actual = next(leaf for leaf in leaves if leaf["nodeIdentifier"] == name + "()")
                        if outcome is None:
                            leaves.remove(actual)
                        else:
                            actual["result"] = outcome
                        with self.assertRaises(cloud.release.ReleaseError):
                            cloud.validate_test_results(platform, tree, {"result": "Passed", "failedTests": 0, "passedTests": len(required)})


class PackagingGateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.app = self.root / "app"; self.app.mkdir()
        environment = patch.dict(os.environ, {"GITHUB_SHA": SHA, "GITHUB_REPOSITORY": cloud.legal_resources.REPOSITORY})
        environment.start(); self.addCleanup(environment.stop)
        root_patch = patch.object(cloud, "ROOT", self.root); root_patch.start(); self.addCleanup(root_patch.stop)
        # Keep the real policy module: only synthetic source/app resources change.
        real_policy = Path(__file__).resolve().parents[2] / "packaging/cloud-client-release/release.py"
        target = self.root / "packaging/cloud-client-release/release.py"
        target.parent.mkdir(parents=True); target.write_bytes(real_policy.read_bytes())
        for folder, source, values in (("FigmaUI", self.root / "apple/FigmaUI", {"index.html": b"<html>release</html>", "assets/app.js": b"console.log('release')"}),
                                       ("practice", self.root / "app/res/practice", {"index.html": b"<html>practice</html>", "demo.musicxml": b"<score-partwise/>"})):
            for name, data in values.items():
                for path in (source / name, self.app / folder / name):
                    path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        for name in ("MODEL-LOCK.json", "DIVIDE-NO-NAN-PATCH.json", "THIRD-PARTY.txt", "BASIC-PITCH-LICENSE"):
            path = self.root / "apple/NoteWiseModels" / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic locked model notice fixture")
            (self.app / name).write_bytes(path.read_bytes())
        profiles = self.root / "apple/NoteLite/NoteWiseProfiles.json"
        profiles.parent.mkdir(parents=True)
        profiles.write_bytes(b'{"schemaVersion":1,"profiles":[]}' )
        (self.app / "NoteWiseProfiles.json").write_bytes(profiles.read_bytes())
        model = self.app / "NoteWiseBasicPitch.mlmodelc"; model.mkdir(); (model / "model.mil").write_bytes(b"synthetic compiled fixture, not inference proof")
        real_root = Path(__file__).resolve().parents[2]
        shutil.copytree(real_root / "apple/AudiverisCore", self.root / "apple/AudiverisCore",
                        ignore=shutil.ignore_patterns(".build", ".swiftpm", "__pycache__"))
        legal = self.root / "apple/Legal"; legal.mkdir()
        for name in cloud.legal_resources.STATIC_NAMES:
            shutil.copyfile(real_root / "apple/Legal" / name, legal / name)
        (legal / cloud.legal_resources.SOURCE_OFFER).write_bytes(cloud.legal_resources.encoded_offer(self.root, SHA))
        shutil.copytree(legal, self.app / "Legal")

    def test_resources_must_match_actual_production_build_and_locked_model_notices(self):
        result = cloud.verify_resources(self.app)
        self.assertIn("NoteWiseBasicPitch.mlmodelc", result)
        (self.app / "FigmaUI/assets/app.js").write_bytes(b"altered")
        with self.assertRaises(cloud.release.ReleaseError): cloud.verify_resources(self.app)
        (self.app / "FigmaUI/assets/app.js").write_bytes(b"console.log('release')")
        (self.app / "BASIC-PITCH-LICENSE").write_bytes(b"altered")
        with self.assertRaises(cloud.release.ReleaseError): cloud.verify_resources(self.app)

    def test_actual_app_requires_full_unchanged_agpl_and_complete_notice_resources(self):
        result = cloud.verify_resources(self.app)["Legal"]
        self.assertTrue(result["actualAppLicenseBytesVerified"])
        self.assertFalse(result["distributionCompatibilityEstablished"])
        self.assertEqual(result["sourceCommit"], SHA)
        for name in cloud.legal_resources.STATIC_NAMES:
            path = self.app / "Legal" / name
            original = path.read_bytes()
            path.unlink()
            with self.assertRaises(cloud.release.ReleaseError): cloud.verify_resources(self.app)
            path.write_bytes(original + b" altered")
            with self.assertRaises(cloud.release.ReleaseError): cloud.verify_resources(self.app)
            path.write_bytes(original)
        # Even changing both source and packaged license must not turn a URL
        # or shortened notice into a purported full license.
        for folder in (self.root / "apple/Legal", self.app / "Legal"):
            (folder / "AGPL-3.0-LICENSE.txt").write_bytes(b"https://www.gnu.org/licenses/agpl-3.0.html")
        with self.assertRaises(cloud.release.ReleaseError): cloud.verify_resources(self.app)
        (self.root / "apple/AudiverisCore/LICENSE").write_bytes(b"https://www.gnu.org/licenses/agpl-3.0.html")
        with self.assertRaisesRegex(cloud.release.ReleaseError, "full AGPL"): cloud.verify_resources(self.app)

    def test_source_offer_must_bind_actual_release_commit_archive_and_package_source(self):
        source = self.root / "apple/Legal" / cloud.legal_resources.SOURCE_OFFER
        installed = self.app / "Legal" / cloud.legal_resources.SOURCE_OFFER
        good = source.read_bytes()
        import json
        baseline = json.loads(good)
        self.assertEqual(baseline["sourceArchiveURL"], "https://github.com/" + cloud.legal_resources.REPOSITORY + "/archive/" + SHA + ".tar.gz")
        mutations = [
            {**baseline, "sourceCommit": "b" * 40},
            {**baseline, "sourceArchiveURL": "https://github.com/Lucas0623z/NoteLite/archive/refs/heads/main.tar.gz"},
            {**baseline, "translatedPackageInventory": {}},
            {**baseline, "upstreamProvenance": {}},
            {**baseline, "distributionCompatibility": "all legally compliant"},
        ]
        for changed in mutations:
            data = (json.dumps(changed, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
            source.write_bytes(data); installed.write_bytes(data)
            with self.assertRaises(cloud.release.ReleaseError): cloud.verify_resources(self.app)
        source.write_bytes(good); installed.write_bytes(good)
        original_source = self.root / "apple/AudiverisCore/Sources/AudiverisCore/Runs.swift"
        original_source.write_bytes(original_source.read_bytes() + b"\n// changed after offer generation\n")
        with self.assertRaises(cloud.release.ReleaseError): cloud.verify_resources(self.app)

    def test_source_offer_missing_and_unexpected_legal_payloads_fail_in_actual_app(self):
        installed = self.app / "Legal" / cloud.legal_resources.SOURCE_OFFER
        good = installed.read_bytes(); installed.unlink()
        with self.assertRaises(cloud.release.ReleaseError): cloud.verify_resources(self.app)
        installed.write_bytes(good)
        extra = self.app / "Legal/old-source-offer.json"; extra.write_bytes(good)
        with self.assertRaises(cloud.release.ReleaseError): cloud.verify_resources(self.app)
        extra.unlink()
        with patch.dict(os.environ, {"GITHUB_SHA": "b" * 40}):
            with self.assertRaises(cloud.release.ReleaseError): cloud.verify_resources(self.app)
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "private/copied-client"}):
            with self.assertRaises(cloud.release.ReleaseError): cloud.verify_resources(self.app)

    def test_preparation_refuses_wrong_head_dirty_source_and_stale_generated_offer(self):
        legal = cloud.legal_resources
        with patch.dict(os.environ, {"GITHUB_SHA": SHA}), patch.object(legal, "git", return_value="b" * 40):
            with self.assertRaisesRegex(legal.LegalResourceError, "different checkout"): legal.prepare(self.root)
        def dirty(root, *args):
            return SHA if args[:1] == ("rev-parse",) else " M apple/NoteLite/NoteWise.swift"
        with patch.object(legal, "git", side_effect=dirty):
            with self.assertRaisesRegex(legal.LegalResourceError, "Commit corresponding source"): legal.prepare(self.root)
        def clean(root, *args):
            return SHA if args[:1] == ("rev-parse",) else ""
        with patch.object(legal, "git", side_effect=clean):
            legal.prepare(self.root, check=True)
            path = self.root / "apple/Legal" / legal.SOURCE_OFFER
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaisesRegex(legal.LegalResourceError, "stale"): legal.prepare(self.root, check=True)
            legal.prepare(self.root)
            legal.prepare(self.root, check=True)

    def test_embedded_jdk_private_data_test_maps_and_debug_controls_are_rejected(self):
        for name in ("OMRResources/classes.jar", "runtime/lib/modules", "history.sqlite", "distribution.p12", "assets/debug.map", "capture.log"):
            path = self.app / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b"synthetic forbidden fixture")
            with self.assertRaises(cloud.release.ReleaseError): cloud.verify_resources(self.app)
            path.unlink()
            if path.parent != self.app:
                # Empty forbidden directories also fail; remove only this fixture path.
                parent = path.parent
                while parent != self.app and not any(parent.iterdir()):
                    parent.rmdir(); parent = parent.parent
        for marker in (b"--uitesting-figma", b"JNI_CreateJavaVM", b"//# sourceMappingURL=debug.map"):
            for base in (self.root / "apple/FigmaUI", self.app / "FigmaUI"):
                (base / "assets/app.js").write_bytes(marker)
            with self.assertRaises(Exception): cloud.verify_resources(self.app)

    def test_ipa_instrument_profiles_must_be_present_and_match_the_verified_resolver(self):
        installed = self.app / "NoteWiseProfiles.json"
        original = installed.read_bytes()
        installed.write_bytes(b'{"schemaVersion":1,"profiles":[{"id":"piano","minMidi":0}]}')
        with self.assertRaises(cloud.release.ReleaseError): cloud.verify_resources(self.app)
        installed.unlink()
        with self.assertRaises(cloud.release.ReleaseError): cloud.verify_resources(self.app)
        installed.write_bytes(original)
        self.assertEqual(cloud.verify_resources(self.app)["NoteWiseProfiles.json"]["sha256"], hashlib.sha256(original).hexdigest())

    def test_model_divide_no_nan_provenance_is_required_and_must_match_exact_source(self):
        installed = self.app / "DIVIDE-NO-NAN-PATCH.json"
        original = installed.read_bytes()
        actual = cloud.verify_resources(self.app)["DIVIDE-NO-NAN-PATCH.json"]
        self.assertEqual(actual, {"bytes": len(original), "sha256": hashlib.sha256(original).hexdigest()})
        installed.write_bytes(original + b" altered graph provenance")
        with self.assertRaises(cloud.release.ReleaseError): cloud.verify_resources(self.app)
        installed.unlink()
        with self.assertRaises(cloud.release.ReleaseError): cloud.verify_resources(self.app)
        installed.write_bytes(original)
        self.assertEqual(cloud.verify_resources(self.app)["DIVIDE-NO-NAN-PATCH.json"], actual)

    def test_actual_device_archive_requires_primary_appicon_and_nonempty_compiled_catalog(self):
        source = self.root / "apple/NoteLite/Assets.xcassets/AppIcon.appiconset"
        source.mkdir(parents=True)
        (source / "Contents.json").write_bytes(b'{"images":[],"info":{"version":1}}')
        (source / "AppIcon-1024.png").write_bytes(b"synthetic source image fixture; not compiled-pixel evidence")
        primary = {"CFBundlePrimaryIcon": {"CFBundleIconName": "AppIcon"}}
        info = {"CFBundleIdentifier": cloud.BUNDLE, "CFBundleDisplayName": cloud.BRAND,
                "CFBundleShortVersionString": "1.0.0", "CFBundleVersion": "13",
                "UIDeviceFamily": [1, 2], "CFBundleSupportedPlatforms": ["iPhoneOS"],
                "DTSDKName": "iphoneos26.0", "CFBundleExecutable": "NoteLite",
                "CFBundleIcons": primary, "CFBundleIcons~ipad": primary}
        catalog = self.app / "Assets.car"
        catalog_bytes = b"synthetic compiled catalog fixture; no Xcode execution"
        catalog.write_bytes(catalog_bytes)
        (self.app / "NoteLite").write_bytes(b"synthetic executable fixture")
        def verify(candidate):
            (self.app / "Info.plist").write_bytes(plistlib.dumps(candidate))
            with patch.object(cloud.release, "run", side_effect=lambda args, capture=False: "platform IOS\n" if "vtool" in args else ""):
                return cloud.verify_app(self.app, self.root, "1.0.0", "13")
        icon = verify(info)["appIcon"]
        self.assertEqual(icon["actualPrimaryIconName"], "AppIcon")
        self.assertEqual(icon["actualIPadPrimaryIconName"], "AppIcon")
        self.assertEqual(icon["actualCompiledAssetCatalog"], {"bytes": len(catalog_bytes), "sha256": hashlib.sha256(catalog_bytes).hexdigest()})
        self.assertEqual(icon["sourceAppIconInventory"]["scope"], "source_assets_only")
        self.assertFalse(icon["compiledIconPixelsComparedToSource"])
        without_ipad = dict(info); without_ipad.pop("CFBundleIcons~ipad")
        self.assertIsNone(verify(without_ipad)["appIcon"]["actualIPadPrimaryIconName"])
        missing_primary = dict(info); missing_primary.pop("CFBundleIcons")
        for candidate in (missing_primary, {**info, "CFBundleIcons": {}},
                          {**info, "CFBundleIcons": {"CFBundlePrimaryIcon": {"CFBundleIconName": "WrongIcon"}}},
                          {**info, "CFBundleIcons~ipad": {"CFBundlePrimaryIcon": {"CFBundleIconName": "WrongIcon"}}},
                          {**info, "CFBundleIcons~ipad": []}):
            with self.assertRaises(cloud.release.ReleaseError): verify(candidate)
        catalog.unlink()
        with self.assertRaises(cloud.release.ReleaseError): verify(info)
        catalog.write_bytes(b"")
        with self.assertRaises(cloud.release.ReleaseError): verify(info)
        catalog.write_bytes(catalog_bytes)
        self.assertEqual(verify(info)["appIcon"], icon)

    def test_zip_traversal_symlink_case_collision_and_size_rejected_before_extraction(self):
        for kind in ("traversal", "symlink", "collision", "size"):
            archive = self.root / (kind + ".zip")
            with zipfile.ZipFile(archive, "w") as zipped:
                if kind == "traversal": zipped.writestr("../outside", b"unsafe")
                elif kind == "symlink":
                    entry = zipfile.ZipInfo("Payload/link"); entry.external_attr = 0o120777 << 16; zipped.writestr(entry, "outside")
                elif kind == "collision": zipped.writestr("Payload/A", b"one"); zipped.writestr("Payload/a", b"two")
                else: zipped.writestr("Payload/large", b"123456789")
            destination = self.root / (kind + "-extracted")
            with patch.object(cloud, "MAX_ZIP_FILE", 8):
                with self.assertRaises(cloud.release.ReleaseError): cloud.safe_unzip(archive, destination)
            self.assertFalse(destination.exists())

    def test_signed_ipa_must_have_actual_distribution_profile_and_certificate(self):
        certificate = b"synthetic distribution certificate fixture"
        fingerprint = hashlib.sha1(certificate).hexdigest().upper()
        profile_uuid = "11111111-1111-1111-1111-111111111111"
        entitlements = {"application-identifier": cloud.TEAM + "." + cloud.BUNDLE,
                        "com.apple.developer.team-identifier": cloud.TEAM, "get-task-allow": False}
        profile = {"UUID": profile_uuid, "Platform": ["iOS"], "TeamIdentifier": [cloud.TEAM],
                   "ApplicationIdentifierPrefix": [cloud.TEAM], "DeveloperCertificates": [certificate],
                   "Entitlements": entitlements, "ExpirationDate": dt.datetime.now() + dt.timedelta(days=30)}
        (self.app / "embedded.mobileprovision").write_bytes(b"synthetic CMS fixture")
        private = self.root / "private"; private.mkdir()
        description = unittest.mock.Mock(returncode=0, stdout="", stderr="TeamIdentifier=" + cloud.TEAM + "\n")

        def command(args, capture=False):
            if args[0] == "security": return plistlib.dumps(profile).decode()
            if "--entitlements" in args: return plistlib.dumps(entitlements).decode()
            options = [arg for arg in args if arg.startswith("--extract-certificates=")]
            if options:
                self.assertEqual(len(options), 1)
                self.assertEqual(len(args), 4)
                self.assertEqual(args[-1], str(self.app))
                Path(options[0].split("=", 1)[1] + "0").write_bytes(certificate)
            return ""

        with patch.object(cloud.release, "run", side_effect=command), patch.object(cloud.subprocess, "run", return_value=description):
            self.assertTrue(cloud.code_signature(self.app, private, profile_uuid, fingerprint)["signatureVerified"])
            with self.assertRaises(cloud.release.ReleaseError): cloud.code_signature(self.app, private, profile_uuid, "B" * 40)
            entitlements["get-task-allow"] = True
            with self.assertRaises(cloud.release.ReleaseError): cloud.code_signature(self.app, private, profile_uuid, fingerprint)

    def test_signature_failure_identifies_static_stage_without_command_output(self):
        diagnostic = "private command output must never be published"
        result = subprocess.CompletedProcess([], 1, stdout=diagnostic, stderr=diagnostic)
        with patch.object(cloud.release.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(cloud.release.ReleaseError, r"^Actual app signature strict verification: codesign failed \(exit 1\)\.$") as caught:
                cloud.code_signature(self.app, self.root, "unused", "unused")
        self.assertNotIn(diagnostic, str(caught.exception))

    @unittest.skipUnless(sys.platform == "darwin", "Requires the real macOS codesign executable")
    def test_real_macos_certificate_extraction_rejects_split_optional_prefix(self):
        # The installed Xcode application is public Apple-signed code; this needs no
        # developer identity, profile, private key, or network request.
        binary = "/usr/bin/codesign"
        application = Path(os.environ["DEVELOPER_DIR"]).parents[1]
        self.assertEqual(application.suffix, ".app")
        self.assertTrue(application.is_dir())
        prefix = self.root / "real-system-signer-"
        broken = subprocess.run([binary, "-d", "--extract-certificates", str(prefix), str(application)],
                                cwd=self.root, capture_output=True, text=True)
        self.assertNotEqual(broken.returncode, 0, "The separate prefix must be treated as a nonexistent code path")
        fixed = subprocess.run([binary, "-d", "--extract-certificates=" + str(prefix), str(application)],
                               cwd=self.root, capture_output=True, text=True)
        self.assertEqual(fixed.returncode, 0, "Actual macOS must accept the combined optional argument")
        certificate = Path(str(prefix) + "0")
        self.assertTrue(certificate.is_file() and certificate.stat().st_size > 0,
                        "The actual leaf certificate must be extracted at the requested prefix")
        parsed = subprocess.run(["openssl", "x509", "-inform", "DER", "-in", str(certificate), "-noout"],
                                capture_output=True, text=True)
        self.assertEqual(parsed.returncode, 0, "The extracted leaf must be an actual DER certificate")
        self.assertFalse((self.root / "codesign0").exists(), "The default output prefix must not be used")


if __name__ == "__main__":
    unittest.main()
