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


class IdentityTests(unittest.TestCase):
    def fixture(self):
        return {"sourceCommit": "a" * 40, "runId": "123456", "runAttempt": "2",
                "toolchain": {"xcodebuild": "Xcode 26.0\nBuild version 17A123", "architecture": "arm64"},
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


if __name__ == "__main__":
    unittest.main()
