"""Product transport boundary tests; these do not run native XCTest."""
import copy
import hashlib
import io
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
        self.base = Path(self.temporary.name)
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
