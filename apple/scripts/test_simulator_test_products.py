"""Product transport boundary tests; these do not run native XCTest."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import plistlib
import stat
import tarfile
import tempfile
import unittest
from unittest import mock

import simulator_test_products as products

ROOT = products.ARCHIVE_ROOT


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve(strict=True)
        self.sequence = 0

    def link(self, path, target, directory=False):
        try:
            path.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError) as error:
            if os.name == "posix":
                raise
            self.skipTest("Fixture symlinks unavailable on this platform: " + str(error))

    def archive(self, entries):
        self.sequence += 1
        path = self.base / ("fixture-" + str(self.sequence) + ".tar.gz")
        with tarfile.open(path, "w:gz") as archive:
            for name, kind, content in entries:
                member = tarfile.TarInfo(name)
                member.mode = 0o755 if kind == "dir" else 0o644
                member.mtime = 1700000000
                if kind == "dir":
                    member.type = tarfile.DIRTYPE
                elif kind in ("sym", "hard"):
                    member.type = tarfile.SYMTYPE if kind == "sym" else tarfile.LNKTYPE
                    member.linkname = content
                elif kind in ("fifo", "device"):
                    member.type = tarfile.FIFOTYPE if kind == "fifo" else tarfile.CHRTYPE
                    member.devmajor = member.devminor = 1
                else:
                    member.size = len(content)
                    if kind == "privileged":
                        member.mode = 0o4755
                archive.addfile(member, io.BytesIO(content) if member.isfile() else None)
        return path

    def extract(self, entries):
        archive = self.archive(entries)
        return products.safe_extract(archive, self.base / ("extracted-" + str(self.sequence)))


class ArchiveTests(Fixture):
    def testOrdinaryFileArchiveUsesTheRequiredRoot(self):
        restored = self.extract([(ROOT, "dir", b""), (ROOT + "/Products", "dir", b""),
                                 (ROOT + "/Products/runtime", "file", b"exact bytes")])
        self.assertEqual(restored.name, ROOT)
        self.assertEqual((restored / "Products/runtime").read_bytes(), b"exact bytes")

    def testOrdinaryFileAndDirectoryModificationTimesSurviveExtraction(self):
        restored = self.extract([(ROOT, "dir", b""), (ROOT + "/Products", "dir", b""),
                                 (ROOT + "/Products/runtime", "file", b"exact bytes")])
        for path in [restored, restored / "Products", restored / "Products/runtime"]:
            with self.subTest(path=path.name):
                self.assertEqual(path.stat().st_mtime, 1700000000)

    def testRejectsCorruptArchiveAndBoundedSizeOrMemberCount(self):
        corrupt = self.base / "corrupt.tar.gz"
        corrupt.write_bytes(b"not a tar archive")
        with self.assertRaises(ValueError):
            products.safe_extract(corrupt, self.base / "corrupt-out")
        with mock.patch.object(products, "MAX_BYTES", 5), self.assertRaises(ValueError):
            self.extract([(ROOT, "dir", b""), (ROOT + "/payload", "file", b"123456")])
        with mock.patch.object(products, "MAX_MEMBERS", 1), self.assertRaises(ValueError):
            self.extract([(ROOT, "dir", b""), (ROOT + "/payload", "file", b"x")])

    def testRealTreeRoundTripPreservesBytesAndInternalRelativeSymlink(self):
        source = self.base / ROOT
        source.mkdir()
        (source / "runtime").write_bytes(b"signed executable fixture")
        self.link(source / "alias", "runtime")
        expected = products.tree_inventory(source)
        archive = self.base / "real-tree.tar.gz"
        with tarfile.open(archive, "w:gz", dereference=False) as stream:
            stream.add(source, arcname=ROOT)
        restored = products.safe_extract(archive, self.base / "roundtrip")
        self.assertEqual(products.tree_inventory(restored), expected)
        self.assertTrue((restored / "alias").is_symlink())
        self.assertEqual(os.readlink(restored / "alias"), "runtime")

    @unittest.skipUnless(os.name == "posix", "Executable permission semantics require POSIX; Apple CI must execute")
    def testExecutableModeAndRealHardlinkSurviveTarRoundTrip(self):
        source = self.base / ROOT
        source.mkdir()
        (source / "runtime").write_bytes(b"executable fixture")
        (source / "runtime").chmod(0o755)
        os.link(source / "runtime", source / "same-inode")
        expected = products.tree_inventory(source)
        archive = self.base / "executable.tar.gz"
        with tarfile.open(archive, "w:gz", dereference=False) as stream:
            stream.add(source, arcname=ROOT)
        restored = products.safe_extract(archive, self.base / "executable-out")
        self.assertEqual(products.tree_inventory(restored), expected)
        self.assertEqual(stat.S_IMODE((restored / "runtime").stat().st_mode), 0o755)
        self.assertTrue(os.path.samefile(restored / "runtime", restored / "same-inode"))

    def testInternalHardlinkNamesAnActualOrdinaryFile(self):
        restored = self.extract([(ROOT, "dir", b""), (ROOT + "/source", "file", b"same bytes"),
                                 (ROOT + "/copy", "hard", ROOT + "/source")])
        self.assertEqual((restored / "copy").read_bytes(), b"same bytes")
        self.assertTrue(os.path.samefile(restored / "copy", restored / "source"))

    def testRejectsMissingWrongAndNonDirectoryArchiveRoot(self):
        for entries in [[], [(ROOT + "/payload", "file", b"x")],
                        [("ForeignProducts", "dir", b"")], [(ROOT, "file", b"x")]]:
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                self.extract(entries)

    def testRejectsAbsoluteTraversalAndWindowsMemberPaths(self):
        for name in ["/" + ROOT + "/payload", ROOT + "/../escaped", ROOT + "/./payload",
                     ROOT + "/Products/../../escaped", ROOT + "\\payload", ROOT + "/C:payload"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.extract([(ROOT, "dir", b""), (name, "file", b"x")])

    def testRejectsExactCasefoldAndUnicodeNormalizedDuplicateMembers(self):
        for first, second in [("payload", "payload"), ("Payload", "payload"), ("caf\u00e9", "cafe\u0301")]:
            with self.subTest(first=first, second=second), self.assertRaises(ValueError):
                self.extract([(ROOT, "dir", b""), (ROOT + "/" + first, "file", b"1"),
                              (ROOT + "/" + second, "file", b"2")])

    def testRejectsSpecialAndPrivilegedMembers(self):
        for kind in ["fifo", "device", "privileged"]:
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.extract([(ROOT, "dir", b""), (ROOT + "/unsafe", kind, b"x")])

    def testRejectsAbsoluteAndExternalLinks(self):
        for kind, target in [("sym", "/private/outside"), ("sym", "../outside"),
                             ("sym", "C:/outside"), ("sym", "..\\outside"),
                             ("hard", "../outside"), ("hard", "/private/outside")]:
            with self.subTest(kind=kind, target=target), self.assertRaises(ValueError):
                self.extract([(ROOT, "dir", b""), (ROOT + "/unsafe", kind, target)])

    def testRejectsLinksUsedAsArchiveParentRegardlessOfOrder(self):
        entries = [(ROOT, "dir", b""), (ROOT + "/ordinary", "dir", b""),
                   (ROOT + "/alias", "sym", "ordinary"), (ROOT + "/alias/payload", "file", b"x")]
        for ordered in (entries, list(reversed(entries))):
            with self.subTest(ordered=ordered), self.assertRaises(ValueError):
                self.extract(ordered)

    def testRejectsNonDirectoryParentsAndMissingOrNonordinaryHardlinkTargets(self):
        cases = [[(ROOT, "dir", b""), (ROOT + "/parent", "file", b"x"),
                  (ROOT + "/parent/payload", "file", b"x")],
                 [(ROOT, "dir", b""), (ROOT + "/alias", "hard", ROOT + "/missing")],
                 [(ROOT, "dir", b""), (ROOT + "/dir", "dir", b""),
                  (ROOT + "/alias", "hard", ROOT + "/dir")]]
        for entries in cases:
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                self.extract(entries)

    def testRejectsLinkedLegalResourcesForBothLinkTypes(self):
        for name in ["Legal/notice", "Legal/SOURCE-OFFER.json", "SOURCE-OFFER.json"]:
            for kind in ["sym", "hard"]:
                target = "../source" if name.startswith("Legal/") and kind == "sym" else "source"
                if kind == "hard":
                    target = ROOT + "/source"
                with self.subTest(name=name, kind=kind), self.assertRaises(ValueError):
                    self.extract([(ROOT, "dir", b""), (ROOT + "/source", "file", b"x"),
                                  (ROOT + "/" + name, kind, target)])

    def testRejectsNonemptyDestinationWithoutChangingExistingBytes(self):
        archive = self.archive([(ROOT, "dir", b""), (ROOT + "/payload", "file", b"x")])
        occupied = self.base / "occupied"
        occupied.mkdir()
        (occupied / "existing").write_bytes(b"preserve me")
        with self.assertRaises(ValueError):
            products.safe_extract(archive, occupied)
        self.assertEqual((occupied / "existing").read_bytes(), b"preserve me")

    def testRejectsPreexistingDestinationSymlinkAncestorAndArchiveSymlink(self):
        archive = self.archive([(ROOT, "dir", b"")])
        actual = self.base / "actual"
        actual.mkdir()
        self.link(self.base / "linked", "actual", directory=True)
        with self.assertRaises(ValueError):
            products.safe_extract(archive, self.base / "linked/out")
        self.assertFalse((actual / "out").exists())
        self.link(self.base / "archive-link", archive.name)
        with self.assertRaises(ValueError):
            products.safe_extract(self.base / "archive-link", self.base / "ordinary-out")
        with self.assertRaises(ValueError):
            products.sha256(self.base / "archive-link")

    @unittest.skipUnless(os.name == "posix", "FIFO fixture requires POSIX; Apple CI must execute")
    def testRejectsFifoArchiveBeforeReading(self):
        fifo = self.base / "not-an-archive"
        os.mkfifo(fifo)
        with self.assertRaises(ValueError):
            products.safe_extract(fifo, self.base / "fifo-out")
        with self.assertRaises(ValueError):
            products.sha256(fifo)


class InventoryTests(Fixture):
    def fixture(self):
        root = self.base / "tree"
        root.mkdir()
        (root / "file").write_bytes(b"original bytes")
        return root

    def testReportsActualSizeHashModeAndDetectsChangedBytes(self):
        root = self.fixture()
        expected = products.tree_inventory(root)
        self.assertEqual(expected["file"], {"type": "file", "bytes": 14,
            "sha256": hashlib.sha256(b"original bytes").hexdigest(),
            "mode": stat.S_IMODE((root / "file").stat().st_mode)})
        (root / "file").write_bytes(b"different data")
        self.assertNotEqual(products.tree_inventory(root), expected)

    def testDetectsMissingAndExtraFiles(self):
        root = self.fixture()
        expected = products.tree_inventory(root)
        (root / "extra").write_bytes(b"new")
        self.assertNotEqual(products.tree_inventory(root), expected)
        (root / "extra").unlink()
        (root / "file").unlink()
        self.assertNotEqual(products.tree_inventory(root), expected)

    def testReportsInternalLinkAndRejectsExternalAndLegalLinks(self):
        root = self.fixture()
        self.link(root / "alias", "file")
        inventory = products.tree_inventory(root)
        self.assertEqual(inventory["alias"]["type"], "symlink")
        self.assertEqual(inventory["alias"]["target"], "file")
        (root / "alias").unlink()
        (self.base / "outside").write_bytes(b"private")
        self.link(root / "alias", "../outside")
        with self.assertRaises(ValueError):
            products.tree_inventory(root)
        (root / "alias").unlink()
        self.link(root / "SOURCE-OFFER.json", "file")
        with self.assertRaises(ValueError):
            products.tree_inventory(root)

    def testRejectsLinkedRoot(self):
        self.fixture()
        self.link(self.base / "root-link", "tree", directory=True)
        with self.assertRaises(ValueError):
            products.tree_inventory(self.base / "root-link")

    @unittest.skipUnless(os.name == "posix", "Special members and modes require POSIX")
    def testRejectsSpecialFilesAndPrivilegedModes(self):
        root = self.fixture()
        os.mkfifo(root / "fifo")
        with self.assertRaises(ValueError):
            products.tree_inventory(root)
        (root / "fifo").unlink()
        (root / "file").chmod(0o4755)
        with self.assertRaises(ValueError):
            products.tree_inventory(root)


class XctestrunTests(Fixture):
    def setUp(self):
        super().setUp()
        self.products = self.base / "Products"
        self.platforms = self.base / "Xcode.app/Contents/Developer/Platforms"
        self.debug = self.products / "Debug-iphonesimulator"
        for path in [self.debug / "NoteLite.app/PlugIns/NoteLiteTests.xctest",
                     self.debug / "NoteLiteUITests-Runner.app/PlugIns/NoteLiteUITests.xctest",
                     self.platforms / "iPhoneSimulator.platform/Developer/Library/Frameworks"]:
            path.mkdir(parents=True)
        environment = {"NOTELITE_LIVE_ACCOUNT_ACCEPTANCE": "1", "NOTELITE_SIM_SWIFT_PATH": "",
                       "DYLD_FALLBACK_LIBRARY_PATH": ""}
        self.targets = {"NoteLiteTests": {
            "TestHostPath": "__TESTROOT__/Debug-iphonesimulator/NoteLite.app",
            "TestBundlePath": "__TESTHOST__/PlugIns/NoteLiteTests.xctest",
            "EnvironmentVariables": copy.deepcopy(environment),
            "TestingEnvironmentVariables": {"DYLD_FRAMEWORK_PATH": "__TESTROOT__/Debug-iphonesimulator:" +
                "__PLATFORMS__/iPhoneSimulator.platform/Developer/Library/Frameworks"}},
            "NoteLiteUITests": {
            "TestHostPath": "__TESTROOT__/Debug-iphonesimulator/NoteLiteUITests-Runner.app",
            "TestBundlePath": "__TESTHOST__/PlugIns/NoteLiteUITests.xctest", "IsUITestBundle": True,
            "UITargetAppPath": "__TESTROOT__/Debug-iphonesimulator/NoteLite.app",
            "EnvironmentVariables": copy.deepcopy(environment)}}

    def document(self, version):
        if version == 1:
            return {"__xctestrun_metadata__": {"FormatVersion": 1}, **copy.deepcopy(self.targets)}
        return {"__xctestrun_metadata__": {"FormatVersion": 2}, "TestConfigurations": [{
            "Name": "Debug", "IsEnabled": True,
            "TestTargets": [{"BlueprintName": name, **copy.deepcopy(target)} for name, target in self.targets.items()]}]}

    def validate(self, document):
        return products.validate_xctestrun(document, self.products, self.platforms)

    def target(self, document, version, name):
        if version == 1:
            return document[name]
        return next(target for target in document["TestConfigurations"][0]["TestTargets"]
                    if target["BlueprintName"] == name)

    def testRealPlistFormatsOneAndTwoRetainBothTargetsAndPortablePaths(self):
        for version in (1, 2):
            for encoding in (plistlib.FMT_XML, plistlib.FMT_BINARY):
                with self.subTest(version=version, encoding=encoding):
                    raw = plistlib.dumps(self.document(version), fmt=encoding)
                    path = self.base / (str(version) + ".xctestrun")
                    path.write_bytes(raw)
                    plan = self.validate(plistlib.loads(path.read_bytes()))
                    self.assertEqual(plan["formatVersion"], version)
                    self.assertEqual({target["name"] for target in plan["targets"]}, products.TARGETS)
                    self.assertEqual(plan["hostApp"], "Debug-iphonesimulator/NoteLite.app")
                    self.assertEqual(plan["uiRunnerApp"], "Debug-iphonesimulator/NoteLiteUITests-Runner.app")
                    self.assertEqual(path.read_bytes(), raw, "Never rewrite the original plist")

    def testBlueprintProjectMetadataKeepsOriginalPlistBytesAndDictionaryInBothFormats(self):
        # These are project-container fixtures, not values observed in the CI plist.
        for version in (1, 2):
            for encoding in (plistlib.FMT_XML, plistlib.FMT_BINARY):
                for project_path in ["NoteLite.xcodeproj", "../NoteLite.xcodeproj",
                                     "../../checkout/apple/NoteLite.xcodeproj"]:
                    with self.subTest(version=version, encoding=encoding, project_path=project_path):
                        document = self.document(version)
                        for name in sorted(products.TARGETS):
                            self.target(document, version, name).update({
                                "BlueprintName": name, "BlueprintProviderName": "NoteLite",
                                "BlueprintProviderRelativePath": project_path})
                        raw = plistlib.dumps(document, fmt=encoding)
                        path = self.base / "blueprint-metadata.xctestrun"
                        path.write_bytes(raw)
                        decoded = plistlib.loads(path.read_bytes())
                        original = copy.deepcopy(decoded)
                        plan = self.validate(decoded)
                        self.assertEqual(decoded, original, "Validation must not change the original dictionary")
                        self.assertEqual(path.read_bytes(), raw, "Validation must not rewrite original plist bytes")
                        self.assertEqual({target["name"] for target in plan["targets"]}, products.TARGETS)
                        for target in plan["targets"]:
                            self.assertNotIn("BlueprintProviderRelativePath", target["runtimePathKeys"])

    def testBlueprintMetadataNeverExemptsActualRuntimePathsInEitherFormat(self):
        runtime_fields = [
            ("NoteLiteTests", "TestHostPath", None),
            ("NoteLiteTests", "TestBundlePath", None),
            ("NoteLiteUITests", "UITargetAppPath", None),
            ("NoteLiteTests", "DependentProductPaths", None),
            ("NoteLiteTests", "TestingEnvironmentVariables", "DYLD_FRAMEWORK_PATH"),
            ("NoteLiteTests", "TestingEnvironmentVariables", "DYLD_LIBRARY_PATH"),
            ("NoteLiteTests", "EnvironmentVariables", "DYLD_INSERT_LIBRARIES"),
        ]
        for version in (1, 2):
            baseline = self.document(version)
            for target_name in products.TARGETS:
                self.target(baseline, version, target_name).update({
                    "BlueprintProviderName": "NoteLite",
                    "BlueprintProviderRelativePath": "../../checkout/apple/NoteLite.xcodeproj"})
            self.validate(baseline)  # A rejected mutation must fail because of its runtime path.
            for name, field, environment_key in runtime_fields:
                for runtime_path in [str((self.debug / "NoteLite.app").resolve()),
                                     "/Users/compiler/DerivedData/Debug-iphonesimulator/NoteLite.app",
                                     "__TESTROOT__/../outside.app"]:
                    document = copy.deepcopy(baseline)
                    target = self.target(document, version, name)
                    if environment_key is not None:
                        target.setdefault(field, {})[environment_key] = runtime_path
                    else:
                        target[field] = [runtime_path] if field == "DependentProductPaths" else runtime_path
                    original = copy.deepcopy(document)
                    with self.subTest(version=version, field=field, environment_key=environment_key,
                                      runtime_path=runtime_path), self.assertRaises(ValueError):
                        self.validate(document)
                    self.assertEqual(document, original, "A rejected plist must also remain unmodified")

    def testOriginalDiagnosticsKeepExactBytesHashAndIdentityWithoutDumpingEnvironmentValues(self):
        for version in (1, 2):
            for encoding in (plistlib.FMT_XML, plistlib.FMT_BINARY):
                with self.subTest(version=version, encoding=encoding):
                    document = self.document(version)
                    target = self.target(document, version, "NoteLiteTests")
                    target["BlueprintProviderRelativePath"] = "../../checkout/apple/NoteLite.xcodeproj"
                    target["EnvironmentVariables"]["OS_ACTIVITY_DT_MODE"] = "environment-value-fixture"
                    target["CommandLineArguments"] = ["--ordinary-argument-fixture"]
                    original_dictionary = copy.deepcopy(document)
                    raw = plistlib.dumps(document, fmt=encoding)
                    original = self.base / "build-original.xctestrun"
                    original.write_bytes(raw)
                    repo = self.base / ("diagnostics-" + str(version) + "-" + encoding.name)
                    identity = {"sourceCommit": "a" * 40, "runId": "123456", "runAttempt": "2",
                                "toolchain": {"xcodebuild": "Xcode 26.6"}, "sourceInputs": {}}
                    capture = io.StringIO()
                    with mock.patch("sys.stdout", capture):
                        products.save_original_diagnostics(repo, original, raw, identity, document)
                    directory = repo / "apple/build/SimulatorProductDiagnostics"
                    self.assertEqual((directory / "original.xctestrun").read_bytes(), raw)
                    self.assertEqual(original.read_bytes(), raw)
                    self.assertEqual(document, original_dictionary)
                    report_text = (directory / "original-xctestrun-identity.json").read_text(encoding="utf-8")
                    report = json.loads(report_text)
                    self.assertEqual(report["originalBytes"], len(raw))
                    self.assertEqual(report["originalSHA256"], hashlib.sha256(raw).hexdigest())
                    for key, value in identity.items():
                        self.assertEqual(report[key], value)
                    self.assertTrue(report["credentialEnvironmentCheckPassed"])
                    self.assertIn("no native XCTest result", report["actualTestResults"])
                    for output in (report_text, capture.getvalue()):
                        self.assertNotIn("environment-value-fixture", output)
                        self.assertNotIn("--ordinary-argument-fixture", output)
                        self.assertNotIn("../../checkout/apple/NoteLite.xcodeproj", output)

    def testCredentialEnvironmentRejectsOriginalArtifactBeforeCreatingItsDirectory(self):
        mutations = [("DEEPSEEK_API_KEY", "dummy-fixture"), ("PASSWORD", "dummy-fixture"),
                     ("AUTHORIZATION", "dummy-fixture"), ("BENIGN_SETTING", "Bearer dummy-fixture"),
                     ("BENIGN_SETTING", "sk-" + "a" * 24),
                     ("BENIGN_SETTING", "-----BEGIN RSA PRIVATE KEY-----"),
                     ("NOTELITE_UNKNOWN_SETTING", "dummy-fixture"),
                     ("NOTELITE_LIVE_ACCOUNT_ACCEPTANCE", "0"),
                     ("NOTELITE_SIM_SWIFT_PATH", "/compiler/swift"),
                     ("BENIGN_SETTING", 1), ("BENIGN_SETTING", "x" * 8193)]
        for version in (1, 2):
            baseline = self.document(version)
            products.check_diagnostic_environment(baseline)
            for environment in ["EnvironmentVariables", "TestingEnvironmentVariables",
                                "UITargetAppEnvironmentVariables"]:
                for name, value in mutations:
                    with self.subTest(version=version, environment=environment, name=name):
                        document = copy.deepcopy(baseline)
                        self.target(document, version, "NoteLiteUITests").setdefault(environment, {})[name] = value
                        original_dictionary = copy.deepcopy(document)
                        raw = plistlib.dumps(document)
                        original = self.base / "private-fixture.xctestrun"
                        original.write_bytes(raw)
                        repo = self.base / "rejected-diagnostic-repo"
                        capture = io.StringIO()
                        with mock.patch("sys.stdout", capture), self.assertRaises(ValueError):
                            products.save_original_diagnostics(repo, original, raw, {}, document)
                        self.assertFalse((repo / "apple/build/SimulatorProductDiagnostics").exists())
                        self.assertEqual(capture.getvalue(), "", "Rejected diagnostics must print no values")
                        self.assertEqual(original.read_bytes(), raw)
                        self.assertEqual(document, original_dictionary)
        # Format 2 may carry configuration-level settings outside either target dictionary.
        document = self.document(2)
        document["TestConfigurations"][0]["EnvironmentVariables"] = {"API_TOKEN": "dummy-fixture"}
        raw = plistlib.dumps(document)
        original = self.base / "private-configuration.xctestrun"
        original.write_bytes(raw)
        repo = self.base / "rejected-configuration-repo"
        capture = io.StringIO()
        with mock.patch("sys.stdout", capture), self.assertRaises(ValueError):
            products.save_original_diagnostics(repo, original, raw, {}, document)
        self.assertFalse((repo / "apple/build/SimulatorProductDiagnostics").exists())
        self.assertEqual(capture.getvalue(), "")
        self.assertEqual(original.read_bytes(), raw)

    def testOversizeOrControlCharacterRuntimeDiagnosticsCannotCreateOriginalArtifact(self):
        for version in (1, 2):
            for field, value in [("DependentProductPaths", ["__TESTROOT__/runtime"] * 201),
                                 ("DependentProductPaths", [1]),
                                 ("TestHostPath", "x" * 2049),
                                 ("TestHostPath", "__TESTROOT__/runtime\nprivate"),
                                 ("TestHostPath", "__TESTROOT__/runtime\0private")]:
                with self.subTest(version=version, field=field, value_type=type(value).__name__):
                    document = self.document(version)
                    self.target(document, version, "NoteLiteTests")[field] = value
                    # Binary plists can represent NUL-bearing strings; XML writer rejects them itself.
                    raw = plistlib.dumps(document, fmt=plistlib.FMT_BINARY)
                    original = self.base / "oversize-fixture.xctestrun"
                    original.write_bytes(raw)
                    repo = self.base / "bounded-diagnostic-repo"
                    with mock.patch("sys.stdout", io.StringIO()), self.assertRaises(ValueError):
                        products.save_original_diagnostics(repo, original, raw, {}, document)
                    self.assertFalse((repo / "apple/build/SimulatorProductDiagnostics").exists())
                    self.assertEqual(original.read_bytes(), raw)

    def testCredentialOrMalformedArgumentsCannotPublishOriginalArtifact(self):
        for version in (1, 2):
            baseline = self.document(version)
            self.target(baseline, version, "NoteLiteUITests").update({
                "CommandLineArguments": ["--ordinary-argument-fixture"],
                "UITargetAppCommandLineArguments": []})
            products.check_diagnostic_environment(baseline)
            for field in ["CommandLineArguments", "UITargetAppCommandLineArguments"]:
                for arguments in [["--api-key=dummy-fixture"], ["Bearer dummy-fixture"],
                                  ["sk-" + "a" * 24], ["--password=dummy-fixture"],
                                  "not-an-array", [1], ["x" * 8193], ["--ordinary"] * 201]:
                    with self.subTest(version=version, field=field, argument_type=type(arguments).__name__):
                        document = copy.deepcopy(baseline)
                        self.target(document, version, "NoteLiteUITests")[field] = arguments
                        raw = plistlib.dumps(document)
                        original = self.base / "private-arguments.xctestrun"
                        original.write_bytes(raw)
                        repo = self.base / "rejected-arguments-repo"
                        capture = io.StringIO()
                        with mock.patch("sys.stdout", capture), self.assertRaises(ValueError):
                            products.save_original_diagnostics(repo, original, raw, {}, document)
                        self.assertFalse((repo / "apple/build/SimulatorProductDiagnostics").exists())
                        self.assertEqual(capture.getvalue(), "")
                        self.assertEqual(original.read_bytes(), raw)

    def testExistingOriginalDiagnosticCannotBeOverwritten(self):
        repo = self.base / "existing-diagnostic-repo"
        directory = repo / "apple/build/SimulatorProductDiagnostics"
        directory.mkdir(parents=True)
        (directory / "original.xctestrun").write_bytes(b"preserve previous diagnostic")
        document = self.document(1)
        raw = plistlib.dumps(document)
        original = self.base / "new-original.xctestrun"
        original.write_bytes(raw)
        with mock.patch("sys.stdout", io.StringIO()), self.assertRaises(ValueError):
            products.save_original_diagnostics(repo, original, raw, {}, document)
        self.assertEqual((directory / "original.xctestrun").read_bytes(), b"preserve previous diagnostic")
        self.assertFalse((directory / "original-xctestrun-identity.json").exists())
        self.assertEqual(original.read_bytes(), raw)

    def testActualXcodeProducerPlistValidatesWithoutChangingItsBytesOrDictionary(self):
        source = Path(__file__).parent / "fixtures/NoteLite-Xcode-26.6-original.xctestrun"
        raw = source.read_bytes()
        self.assertEqual(len(raw), 8997)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         "3cb5b43304f4ce03d2784e1b4e52d194a563f56c7bf6550d3b57749137e6e5d0")
        # The original plist is genuine; this local resource tree is only a validator fixture.
        local_injection = self.debug / "NoteLite.app/Frameworks/libXCTestBundleInject.dylib"
        local_injection.parent.mkdir(parents=True)
        local_injection.write_bytes(b"local injection file fixture")
        (self.platforms / "iPhoneSimulator.platform/Developer/usr/lib").mkdir(parents=True)
        document = plistlib.loads(raw)
        original = copy.deepcopy(document)
        products.check_diagnostic_environment(document)
        plan = self.validate(document)
        self.assertEqual(plan["formatVersion"], 1)
        self.assertEqual({target["name"] for target in plan["targets"]}, products.TARGETS)
        self.assertEqual(document, original)
        self.assertEqual(source.read_bytes(), raw)
        self.assertFalse((self.debug / "PackageFrameworks").exists())

    def testOnlyTwoExactSystemHooksAreAcceptedAsInsertedLibrariesInBothFormats(self):
        hooks = "/usr/lib/libRPAC.dylib:__SIMRUNTIMEROOT__/usr/lib/libMainThreadChecker.dylib"
        for version in (1, 2):
            document = self.document(version)
            for name in products.TARGETS:
                target = self.target(document, version, name)
                for environment in ["EnvironmentVariables", "TestingEnvironmentVariables",
                                    "UITargetAppEnvironmentVariables"]:
                    target.setdefault(environment, {})["DYLD_INSERT_LIBRARIES"] = hooks
            original = copy.deepcopy(document)
            plan = self.validate(document)
            self.assertEqual({target["name"] for target in plan["targets"]}, products.TARGETS)
            self.assertEqual(document, original)

    def testOtherAbsoluteOrSimulatorRootInjectionsRemainRejected(self):
        for version in (1, 2):
            for path in ["/usr/lib/libOther.dylib", "/usr/lib/libRPAC.dylib/extra",
                         "__SIMRUNTIMEROOT__/usr/lib/libOther.dylib",
                         "__SIMRUNTIMEROOT__/../usr/lib/libMainThreadChecker.dylib",
                         "__SIMRUNTIMEROOT__/usr/lib/libMainThreadChecker.dylib/extra"]:
                document = self.document(version)
                self.target(document, version, "NoteLiteTests")["EnvironmentVariables"]["DYLD_INSERT_LIBRARIES"] = path
                with self.subTest(version=version, path=path), self.assertRaises(ValueError):
                    self.validate(document)

    def testExactSystemHooksAreNotGeneralRuntimeOrSearchPathExceptions(self):
        search_keys = ["DYLD_FRAMEWORK_PATH", "DYLD_LIBRARY_PATH", "__XPC_DYLD_FRAMEWORK_PATH",
                       "__XPC_DYLD_LIBRARY_PATH", "__XCODE_BUILT_PRODUCTS_DIR_PATHS"]
        for version in (1, 2):
            for hook in ["/usr/lib/libRPAC.dylib", "__SIMRUNTIMEROOT__/usr/lib/libMainThreadChecker.dylib"]:
                for key in search_keys:
                    document = self.document(version)
                    self.target(document, version, "NoteLiteTests")["TestingEnvironmentVariables"][key] = hook
                    with self.subTest(version=version, key=key, hook=hook), self.assertRaises(ValueError):
                        self.validate(document)
                for name, field in [("NoteLiteTests", "TestHostPath"), ("NoteLiteTests", "TestBundlePath"),
                                    ("NoteLiteUITests", "UITargetAppPath"),
                                    ("NoteLiteTests", "DependentProductPaths")]:
                    document = self.document(version)
                    self.target(document, version, name)[field] = [hook] if field.endswith("Paths") else hook
                    with self.subTest(version=version, field=field, hook=hook), self.assertRaises(ValueError):
                        self.validate(document)

    def testLocalBundleInjectionMustBeAnExistingOrdinaryFile(self):
        injection = self.debug / "NoteLite.app/Frameworks/libXCTestBundleInject.dylib"
        injection.parent.mkdir(parents=True)
        injection.write_bytes(b"local injection file fixture")
        document = self.document(1)
        document["NoteLiteTests"]["TestingEnvironmentVariables"]["DYLD_INSERT_LIBRARIES"] = \
            "__TESTHOST__/Frameworks/libXCTestBundleInject.dylib"
        self.validate(document)
        injection.unlink()
        with self.assertRaises(ValueError):
            self.validate(document)
        injection.mkdir()
        with self.assertRaises(ValueError):
            self.validate(document)

    def testMissingBoundedSearchDirectoriesAndAuxiliarySearchRootsAreValid(self):
        missing = "__TESTROOT__/Debug-iphonesimulator/PackageFrameworks"
        keys = ["DYLD_FRAMEWORK_PATH", "DYLD_LIBRARY_PATH", "__XPC_DYLD_FRAMEWORK_PATH",
                "__XPC_DYLD_LIBRARY_PATH", "__XCODE_BUILT_PRODUCTS_DIR_PATHS"]
        self.assertFalse((self.debug / "PackageFrameworks").exists())
        for version in (1, 2):
            document = self.document(version)
            for name in products.TARGETS:
                for group in ["EnvironmentVariables", "TestingEnvironmentVariables",
                              "UITargetAppEnvironmentVariables"]:
                    target = self.target(document, version, name)
                    for key in keys:
                        target.setdefault(group, {})[key] = missing
            original = copy.deepcopy(document)
            self.assertEqual(len(self.validate(document)["targets"]), 2)
            self.assertEqual(document, original)
        self.assertFalse((self.debug / "PackageFrameworks").exists(), "Do not synthesize absent search directories")

    def testSearchRootsRejectAbsoluteTraversalAndExistingNonDirectoryPaths(self):
        (self.debug / "ordinary-file").write_bytes(b"not a directory")
        keys = ["DYLD_FRAMEWORK_PATH", "DYLD_LIBRARY_PATH", "__XPC_DYLD_FRAMEWORK_PATH",
                "__XPC_DYLD_LIBRARY_PATH", "__XCODE_BUILT_PRODUCTS_DIR_PATHS"]
        for version in (1, 2):
            for key in keys:
                for path in ["/Users/compiler/DerivedData/PackageFrameworks", "__TESTROOT__/../missing",
                             "__TESTROOT__/Debug-iphonesimulator/../../outside",
                             "__TESTROOT__/Debug-iphonesimulator/ordinary-file"]:
                    document = self.document(version)
                    self.target(document, version, "NoteLiteTests")["TestingEnvironmentVariables"][key] = path
                    with self.subTest(version=version, key=key, path=path), self.assertRaises(ValueError):
                        self.validate(document)

    def testSearchDirectorySymlinkCannotEscapeRootsEvenWhenFinalDirectoryIsMissing(self):
        outside = self.base / "outside-search"
        outside.mkdir()
        self.link(self.debug / "external-search", "../../outside-search", directory=True)
        for key in ["DYLD_FRAMEWORK_PATH", "DYLD_LIBRARY_PATH", "__XPC_DYLD_FRAMEWORK_PATH",
                    "__XPC_DYLD_LIBRARY_PATH", "__XCODE_BUILT_PRODUCTS_DIR_PATHS"]:
            document = self.document(1)
            document["NoteLiteTests"]["TestingEnvironmentVariables"][key] = \
                "__TESTROOT__/Debug-iphonesimulator/external-search/missing-directory"
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.validate(document)

    def testMissingRequiredHostBundlesAndDependentProductsAreNeverSearchExceptions(self):
        for version in (1, 2):
            self.validate(self.document(version))
            for name, field, path in [("NoteLiteTests", "TestHostPath", "__TESTROOT__/missing.app"),
                                      ("NoteLiteTests", "TestBundlePath", "__TESTHOST__/PlugIns/Missing.xctest"),
                                      ("NoteLiteUITests", "UITargetAppPath", "__TESTROOT__/missing.app"),
                                      ("NoteLiteTests", "DependentProductPaths", "__TESTROOT__/missing.app")]:
                document = self.document(version)
                self.target(document, version, name)[field] = [path] if field.endswith("Paths") else path
                with self.subTest(version=version, field=field), self.assertRaises(ValueError):
                    self.validate(document)

    def testDefaultFormatOneAndAbsentEmptySwiftPathsRemainValid(self):
        document = copy.deepcopy(self.targets)
        for target in document.values():
            target["EnvironmentVariables"] = {"NOTELITE_LIVE_ACCOUNT_ACCEPTANCE": "1"}
        self.assertEqual(self.validate(document)["formatVersion"], 1)

    def testEmptyOnlyAndSkipFiltersDoNotRemoveActualTests(self):
        document = self.document(1)
        document["NoteLiteTests"].update({"OnlyTestIdentifiers": [], "SkipTestIdentifiers": []})
        self.assertEqual(len(self.validate(document)["targets"]), 2)

    def testRejectsWrongMissingDuplicatedAndDisabledTargetsOrConfigurations(self):
        variants = []
        document = self.document(1)
        document.pop("NoteLiteTests")
        variants.append(document)
        document = self.document(1)
        document["ForeignTests"] = document.pop("NoteLiteTests")
        variants.append(document)
        document = self.document(2)
        document["TestConfigurations"][0]["TestTargets"][1]["BlueprintName"] = "NoteLiteTests"
        variants.append(document)
        document = self.document(2)
        document["TestConfigurations"][0]["IsEnabled"] = False
        variants.append(document)
        document = self.document(2)
        document["TestConfigurations"].append(copy.deepcopy(document["TestConfigurations"][0]))
        variants.append(document)
        document = self.document(1)
        document["NoteLiteTests"]["IsEnabled"] = False
        variants.append(document)
        for index, document in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.validate(document)

    def testRejectsUnsupportedMixedAndMalformedPlistShapes(self):
        variants = [[], {"__xctestrun_metadata__": []}, {"__xctestrun_metadata__": {"FormatVersion": 3}},
                    {**self.document(1), "TestConfigurations": []},
                    {"__xctestrun_metadata__": {"FormatVersion": 2}, "TestConfigurations": []}]
        for index, document in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.validate(document)

    def testRejectsMissingWrongAndNonemptyPathEnvironment(self):
        for target in products.TARGETS:
            for key, value in [("NOTELITE_LIVE_ACCOUNT_ACCEPTANCE", None),
                               ("NOTELITE_LIVE_ACCOUNT_ACCEPTANCE", "0"),
                               ("NOTELITE_LIVE_ACCOUNT_ACCEPTANCE", 1),
                               ("NOTELITE_SIM_SWIFT_PATH", "/build-host/swift"),
                               ("DYLD_FALLBACK_LIBRARY_PATH", "/build-host/lib")]:
                document = self.document(1)
                if value is None:
                    document[target]["EnvironmentVariables"].pop(key)
                else:
                    document[target]["EnvironmentVariables"][key] = value
                with self.subTest(target=target, key=key, value=value), self.assertRaises(ValueError):
                    self.validate(document)

    def testRejectsNonemptyOnlySkipAndNestedConfigurationFilters(self):
        for key in ["OnlyTestIdentifiers", "SkipTestIdentifiers", "OnlyTestConfigurations", "SkipTestConfigurations"]:
            for version in (1, 2):
                document = self.document(version)
                if version == 1:
                    document["NoteLiteTests"][key] = ["testRequired"]
                else:
                    document["TestConfigurations"][0]["nested"] = {key: ["testRequired"]}
                with self.subTest(key=key, version=version), self.assertRaises(ValueError):
                    self.validate(document)

    def testRejectsAbsoluteEscapingUnrecognizedAndMissingRuntimePaths(self):
        for field in ("TestHostPath", "TestBundlePath", "UITargetAppPath"):
            target = "NoteLiteUITests" if field == "UITargetAppPath" else "NoteLiteTests"
            for value in [str((self.debug / "NoteLite.app").resolve()), "/Users/compiler/DerivedData/NoteLite.app",
                          "__TESTROOT__/../private.app", "__TESTROOT__/./Debug-iphonesimulator/NoteLite.app",
                          "__UNKNOWN__/NoteLite.app", "__TESTROOT__/missing.app"]:
                document = self.document(1)
                document[target][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.validate(document)

    def testRejectsMissingBundlesWrongBundleNamesAndTargetType(self):
        variants = []
        for key, value in [("TestBundlePath", "__TESTHOST__/PlugIns/Missing.xctest"),
                           ("TestBundlePath", "__TESTHOST__/PlugIns"), ("IsUITestBundle", True)]:
            document = self.document(1)
            document["NoteLiteTests"][key] = value
            variants.append(document)
        document = self.document(1)
        document["NoteLiteUITests"].pop("IsUITestBundle")
        variants.append(document)
        for document in variants:
            with self.subTest(document=document), self.assertRaises(ValueError):
                self.validate(document)

    def testRejectsAbsoluteDynamicLoaderAndRuntimeListPaths(self):
        for field, value in [("DependentProductPaths", ["/Users/compiler/DerivedData/runtime"]),
                             ("DependentProductPaths", "not-a-list"),
                             ("TestingEnvironmentVariables", {"DYLD_INSERT_LIBRARIES": "/build/lib.dylib"}),
                             ("TestingEnvironmentVariables", {"DYLD_FRAMEWORK_PATH": 1})]:
            document = self.document(1)
            document["NoteLiteTests"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.validate(document)

    def testRejectsRuntimeBundleSymlinkEscapingProducts(self):
        outside = self.base / "outside.app"
        outside.mkdir()
        self.link(self.debug / "outside.app", "../../outside.app", directory=True)
        document = self.document(1)
        document["NoteLiteTests"]["TestHostPath"] = "__TESTROOT__/Debug-iphonesimulator/outside.app"
        with self.assertRaises(ValueError):
            self.validate(document)


class Arm64BinaryTests(Fixture):
    def application(self, document=None, plist_format=plistlib.FMT_XML):
        self.sequence += 1
        app = self.base / ("NoteLite-" + str(self.sequence) + ".app")
        app.mkdir()
        info = {"CFBundleExecutable": "NoteLite"} if document is None else document
        (app / "Info.plist").write_bytes(plistlib.dumps(info, fmt=plist_format))
        (app / "NoteLite").write_bytes(b"binary file fixture; lipo is mocked")
        return app

    def testAppAndRunnerOrdinaryExecutablesUseExactArm64LipoContract(self):
        for name, plist_format in [("NoteLite", plistlib.FMT_XML),
                                   ("NoteLiteUITests-Runner", plistlib.FMT_BINARY)]:
            app = self.application({"CFBundleExecutable": name}, plist_format)
            if name != "NoteLite":
                (app / "NoteLite").rename(app / name)
            original = {item.name: item.read_bytes() for item in app.iterdir()}
            with self.subTest(name=name), mock.patch.object(products, "command", return_value="") as command:
                products._verify_arm64_binary(app)
                command.assert_called_once_with("lipo", str(app / name), "-verify_arch", "arm64")
                self.assertEqual({item.name: item.read_bytes() for item in app.iterdir()}, original)

    def testExecutableNameMustBeAnOrdinaryBasename(self):
        for value in [None, [], 123, "", ".", "..", "A" * 256, "../outside", "/tmp/outside", "dir/binary",
                      "dir\\binary", "C:\\binary", "binary\nother"]:
            # Binary plists can represent a null value; XML serialization rejects it before the reader.
            app = self.application({"CFBundleExecutable": value}, plistlib.FMT_BINARY)
            with self.subTest(value=value), mock.patch.object(products, "command") as command:
                with self.assertRaises(ValueError):
                    products._verify_arm64_binary(app)
                command.assert_not_called()
        app = self.application()
        with mock.patch.object(products, "MAX_BYTES", (app / "NoteLite").stat().st_size - 1), \
                mock.patch.object(products, "command") as command:
            with self.assertRaises(ValueError):
                products._verify_arm64_binary(app)
            command.assert_not_called()
        app = self.application({})
        with mock.patch.object(products, "command") as command, self.assertRaises(ValueError):
            products._verify_arm64_binary(app)
        command.assert_not_called()

    def testExecutableMustExistAsAnOrdinaryBoundedFile(self):
        for variant in ("missing", "directory"):
            app = self.application()
            binary = app / "NoteLite"
            binary.unlink()
            if variant == "directory":
                binary.mkdir()
            with self.subTest(variant=variant), mock.patch.object(products, "command") as command:
                with self.assertRaises(ValueError):
                    products._verify_arm64_binary(app)
                command.assert_not_called()

    def testInfoPlistMustBeOrdinaryBoundedAndWellFormedDictionary(self):
        for variant in ("missing", "directory", "oversize", "malformed", "array"):
            app = self.application()
            info = app / "Info.plist"
            info.unlink()
            if variant == "directory":
                info.mkdir()
            elif variant == "oversize":
                info.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
            elif variant == "malformed":
                info.write_bytes(b"not a plist")
            elif variant == "array":
                info.write_bytes(plistlib.dumps([{"CFBundleExecutable": "NoteLite"}]))
            with self.subTest(variant=variant), mock.patch.object(products, "command") as command:
                with self.assertRaises(ValueError):
                    products._verify_arm64_binary(app)
                command.assert_not_called()

    def testLinkedInfoPlistAndLinkedExecutableAreRejectedBeforeLipo(self):
        for relative in ("Info.plist", "NoteLite"):
            app = self.application()
            original = app / relative
            ordinary = app / (relative + ".ordinary")
            original.rename(ordinary)
            self.link(original, ordinary.name)
            with self.subTest(relative=relative), mock.patch.object(products, "command") as command:
                with self.assertRaises(ValueError):
                    products._verify_arm64_binary(app)
                command.assert_not_called()


class CommandDiagnosticTests(unittest.TestCase):
    def testSuccessfulToolContractUsesBoundedCaptureAndReturnsStrippedOutput(self):
        result = products.subprocess.CompletedProcess(("lipo", "ordinary-binary", "-verify_arch", "arm64"),
                                                      0, stdout=" success \n", stderr="unused diagnostic")
        capture = io.StringIO()
        with mock.patch.object(products.subprocess, "run", return_value=result) as run, \
                mock.patch("sys.stderr", capture):
            self.assertEqual(products.command("lipo", "ordinary-binary", "-verify_arch", "arm64"), "success")
        run.assert_called_once_with(("lipo", "ordinary-binary", "-verify_arch", "arm64"),
                                    check=True, capture_output=True, text=True, timeout=120)
        self.assertEqual(capture.getvalue(), "")

    def testFailedToolDiagnosticsAreBoundedAndOmitCredentialLikeStderrAndArguments(self):
        arguments = ("lipo", "argument-must-not-be-printed", "-verify_arch", "arm64")
        for stderr, omitted in [("ordinary diagnostic\x00\n" + "x" * 3000, False),
                                ("API_TOKEN=dummy-fixture", True),
                                ("bearer dummy-fixture", True),
                                ("https://dummy-user:dummy-pass@example.invalid", True),
                                ("sk-" + "x" * 24, True)]:
            failure = products.subprocess.CalledProcessError(2, arguments, stderr=stderr)
            capture = io.StringIO()
            with self.subTest(omitted=omitted, stderr_length=len(stderr)), \
                    mock.patch.object(products.subprocess, "run", side_effect=failure), \
                    mock.patch("sys.stderr", capture), self.assertRaises(ValueError) as caught:
                products.command(*arguments)
            text = capture.getvalue()
            report = json.loads(text)
            self.assertEqual(set(report), {"failedTool", "exitStatus", "boundedStderr", "stderrBytes", "stderrSHA256"})
            self.assertEqual(report["failedTool"], "lipo")
            self.assertEqual(report["exitStatus"], 2)
            self.assertEqual(report["stderrBytes"], len(stderr.encode("utf-8")))
            self.assertEqual(report["stderrSHA256"], hashlib.sha256(stderr.encode("utf-8")).hexdigest())
            self.assertLessEqual(len(report["boundedStderr"]), 2048)
            self.assertNotIn("argument-must-not-be-printed", text + str(caught.exception))
            self.assertNotIn("\x00", report["boundedStderr"])
            self.assertIsNone(caught.exception.__cause__)
            self.assertTrue(caught.exception.__suppress_context__)
            if omitted:
                self.assertEqual(report["boundedStderr"], "[credential-like stderr omitted]")
                self.assertNotIn(stderr, text + str(caught.exception))
            else:
                self.assertTrue(report["boundedStderr"].startswith("ordinary diagnostic?\n"))


class SimulatorRuntimeTests(unittest.TestCase):
    device_id = "12345678-1234-1234-1234-123456789ABC"
    runtime_id = "com.apple.CoreSimulator.SimRuntime.iOS-26-6"

    def fixtures(self):
        devices = {"devices": {self.runtime_id: [{"udid": self.device_id,
                    "isAvailable": True, "state": "Booted"}]}}
        runtimes = {"runtimes": [{"identifier": self.runtime_id, "version": "26.6",
                    "buildversion": "23A123", "isAvailable": True,
                    "supportedArchitectures": ["arm64"]}]}
        return devices, runtimes

    def resolve(self, devices, runtimes, architecture="arm64", device_id=None):
        destination = self.device_id if device_id is None else device_id
        calls = []

        def command(*arguments):
            calls.append(arguments)
            if arguments == ("xcrun", "simctl", "list", "devices", "--json"):
                return json.dumps(devices)
            if arguments == ("xcrun", "simctl", "list", "runtimes", "--json"):
                return json.dumps(runtimes)
            raise AssertionError("Unexpected simulator identity command: " + repr(arguments))

        with mock.patch.object(products, "command", side_effect=command), \
                mock.patch.object(products.platform, "machine", return_value=architecture):
            identity = products.simulator_runtime_identity(destination)
        return identity, calls

    def testActualBootedDeviceRuntimeIdentityAndZeroPatchVersionAreAccepted(self):
        for identifier, version in [(self.runtime_id, "26.6"),
                                    ("com.apple.CoreSimulator.SimRuntime.iOS-26-5", "26.5.0")]:
            devices, runtimes = self.fixtures()
            devices["devices"][identifier] = devices["devices"].pop(self.runtime_id)
            runtimes["runtimes"][0].update(identifier=identifier, version=version)
            original = copy.deepcopy((devices, runtimes))
            identity, calls = self.resolve(devices, runtimes)
            with self.subTest(identifier=identifier, version=version):
                self.assertEqual(identity, {"identifier": identifier, "version": version,
                                            "buildVersion": "23A123", "architecture": "arm64"})
                self.assertEqual(calls, [("xcrun", "simctl", "list", "devices", "--json"),
                                        ("xcrun", "simctl", "list", "runtimes", "--json")])
                self.assertEqual((devices, runtimes), original)
                self.assertNotIn(self.device_id, json.dumps(identity))

    def testDeviceMustBeUniqueAvailableBootedAndBoundToItsInstalledRuntime(self):
        devices, runtimes = self.fixtures()
        self.resolve(devices, runtimes)
        variants = []
        for field, value in [("udid", "00000000-0000-0000-0000-000000000000"),
                             ("isAvailable", False), ("isAvailable", 1), ("state", "Shutdown")]:
            altered = copy.deepcopy(devices)
            altered["devices"][self.runtime_id][0][field] = value
            variants.append((field + "=" + str(value), altered))
        altered = copy.deepcopy(devices)
        altered["devices"][self.runtime_id].append(copy.deepcopy(altered["devices"][self.runtime_id][0]))
        variants.append(("duplicated within runtime", altered))
        altered = copy.deepcopy(devices)
        altered["devices"]["com.apple.CoreSimulator.SimRuntime.iOS-26-5"] = copy.deepcopy(
            altered["devices"][self.runtime_id])
        variants.append(("duplicated across runtimes", altered))
        altered = copy.deepcopy(devices)
        altered["devices"]["com.apple.CoreSimulator.SimRuntime.iOS-26-5"] = altered["devices"].pop(self.runtime_id)
        variants.append(("actual device runtime is not installed", altered))
        variants.extend([("missing devices", {}), ("devices not a dictionary", {"devices": []}),
                         ("runtime devices not a list", {"devices": {self.runtime_id: {}}})])
        for label, altered in variants:
            with self.subTest(label=label), self.assertRaises(ValueError):
                self.resolve(altered, runtimes)
        for destination in ["iPhone 17", "", "/tmp/device", "12345678-1234-1234-1234-123456789ABZ"]:
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                self.resolve(devices, runtimes, device_id=destination)

    def testRuntimeRequiresUniqueAvailableModernIOSIdentityExactBuildAndArm64Support(self):
        devices, runtimes = self.fixtures()
        self.resolve(devices, runtimes)
        variants = []
        for field, value in [("identifier", "com.apple.CoreSimulator.SimRuntime.iOS-26-5"),
                             ("version", "25.9"), ("version", "26"), ("version", "26.6\n"),
                             ("buildversion", ""), ("buildversion", "23A123/foreign"),
                             ("buildversion", "A" * 33), ("isAvailable", False),
                             ("isAvailable", 1), ("supportedArchitectures", ["x86_64"]),
                             ("supportedArchitectures", "arm64")]:
            altered = copy.deepcopy(runtimes)
            altered["runtimes"][0][field] = value
            variants.append((field + "=" + str(value), devices, altered))
        for field in ("version", "buildversion", "isAvailable", "supportedArchitectures"):
            altered = copy.deepcopy(runtimes)
            altered["runtimes"][0].pop(field)
            variants.append(("missing " + field, devices, altered))
        altered = copy.deepcopy(runtimes)
        altered["runtimes"].append(copy.deepcopy(altered["runtimes"][0]))
        variants.append(("duplicated runtime", devices, altered))
        variants.extend([("missing runtimes", devices, {}), ("runtimes not a list", devices, {"runtimes": {}}),
                         ("no matching runtime", devices, {"runtimes": []})])
        for identifier in ("com.apple.CoreSimulator.SimRuntime.tvOS-26-6", self.runtime_id + "/escape"):
            altered_devices, altered_runtimes = copy.deepcopy((devices, runtimes))
            altered_devices["devices"][identifier] = altered_devices["devices"].pop(self.runtime_id)
            altered_runtimes["runtimes"][0]["identifier"] = identifier
            variants.append(("foreign identifier " + identifier, altered_devices, altered_runtimes))
        for label, altered_devices, altered_runtimes in variants:
            with self.subTest(label=label), self.assertRaises(ValueError):
                self.resolve(altered_devices, altered_runtimes)

    def testActualHostArchitectureMustBeExactlyArm64(self):
        devices, runtimes = self.fixtures()
        self.resolve(devices, runtimes)
        for architecture in ("x86_64", "arm64e", "arm64\nx86_64", "", "ARM64"):
            with self.subTest(architecture=architecture), self.assertRaises(ValueError):
                self.resolve(devices, runtimes, architecture=architecture)


class IdentityTests(unittest.TestCase):
    def fixture(self):
        return {"sourceCommit": "a" * 40, "runId": "123456", "runAttempt": "2",
                "toolchain": {"xcodebuild": "Xcode 26.0\nBuild version 17A123", "architecture": "arm64"},
                "simulatorRuntime": {"identifier": "com.apple.CoreSimulator.SimRuntime.iOS-26-6",
                                     "version": "26.6", "buildVersion": "23A123", "architecture": "arm64"},
                "sourceInputs": {"figma-ui/pnpm-lock.yaml": {"bytes": 12, "sha256": "b" * 64}}}

    def testExactlyMatchingFiveIdentityFieldsAreAccepted(self):
        expected = self.fixture()
        self.assertIsNone(products.assert_identity(copy.deepcopy(expected), expected))

    def testWrongSHAOrRunAttemptOrToolchainOrSourceLockIsRejected(self):
        for field in products.IDENTITY_FIELDS:
            expected = self.fixture()
            actual = copy.deepcopy(expected)
            actual[field] = "wrong" if not isinstance(actual[field], dict) else {"changed": True}
            with self.subTest(field=field), self.assertRaises(ValueError):
                products.assert_identity(actual, expected)

    def testMissingIdentityFieldsOnEitherSideAndInvalidRootsAreRejected(self):
        for field in products.IDENTITY_FIELDS:
            expected = self.fixture()
            absent = copy.deepcopy(expected)
            absent.pop(field)
            for actual, reference in [(absent, expected), (expected, absent)]:
                with self.subTest(field=field), self.assertRaises(ValueError):
                    products.assert_identity(actual, reference)
        for actual, reference in [([], self.fixture()), (self.fixture(), [])]:
            with self.assertRaises(ValueError):
                products.assert_identity(actual, reference)

    def testNestedToolchainAndSourceInputMutationsAreRejected(self):
        for key, value in [("architecture", "x86_64"), ("xcodebuild", "Xcode 25.0")]:
            expected = self.fixture()
            actual = copy.deepcopy(expected)
            actual["toolchain"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                products.assert_identity(actual, expected)
        for key, value in [("bytes", 13), ("sha256", "c" * 64)]:
            expected = self.fixture()
            actual = copy.deepcopy(expected)
            actual["sourceInputs"]["figma-ui/pnpm-lock.yaml"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                products.assert_identity(actual, expected)

    def testEachSimulatorRuntimeIdentityFieldMustMatchTheProducerExactly(self):
        for field, value in [("identifier", "com.apple.CoreSimulator.SimRuntime.iOS-26-5"),
                             ("version", "26.5"), ("buildVersion", "23A124"),
                             ("architecture", "x86_64")]:
            expected = self.fixture()
            actual = copy.deepcopy(expected)
            self.assertIsNone(products.assert_identity(actual, expected))
            actual["simulatorRuntime"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                products.assert_identity(actual, expected)


if __name__ == "__main__":
    unittest.main()
