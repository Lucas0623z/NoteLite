import XCTest
import zlib
@testable import NoteLite

final class CloudResultValidationTests: XCTestCase {
    private let validScore = Data("""
    <?xml version="1.0"?><score-partwise version="4.0"><part-list><score-part id="P1">
    <part-name>Piano</part-name></score-part></part-list><part id="P1"><measure number="1">
    <attributes><divisions>1</divisions></attributes><note><pitch><step>C</step><octave>4</octave>
    </pitch><duration>1</duration><type>quarter</type></note></measure></part></score-partwise>
    """.utf8)

    func testRejectsHTMLMalformedXMLAndEmptyScores() throws {
        XCTAssertNoThrow(try CloudResultValidation.validateMusicXML(validScore))
        for value in ["<html><body>Error</body></html>", "<score-partwise>",
                      "<score-partwise><part><measure/></part></score-partwise>",
                      "<!DOCTYPE score-partwise [<!ENTITY payload 'x'>]><score-partwise>&payload;</score-partwise>"] {
            XCTAssertThrowsError(try CloudResultValidation.validateMusicXML(Data(value.utf8)))
        }
    }

    func testRejectsDuplicateOrNonPracticeManifest() {
        func artifact(_ name: String) -> JobArtifact { JobArtifact(name: name, path: "https://untrusted.example/ignored") }
        XCTAssertThrowsError(try CloudResultValidation.validateManifest([]))
        XCTAssertThrowsError(try CloudResultValidation.validateManifest([artifact("score.mid")]))
        XCTAssertThrowsError(try CloudResultValidation.validateManifest([artifact("../score.mxl")]))
        XCTAssertThrowsError(try CloudResultValidation.validateManifest([artifact("Score.mxl"), artifact("score.mxl")]))
        XCTAssertNoThrow(try CloudResultValidation.validateManifest([artifact("score.musicxml"), artifact("score.mid")]))
    }

    func testValidMXLContainerAndDeflatedScore() throws {
        let container = Data("<container><rootfiles><rootfile full-path='score.xml' media-type='application/vnd.recordare.musicxml+xml'/></rootfiles></container>".utf8)
        let data = try zip([("META-INF/container.xml", container), ("score.xml", validScore)], deflated: true)
        XCTAssertNoThrow(try CloudResultValidation.validateMusicXML(data))
        XCTAssertNoThrow(try CloudResultValidation.validateMusicXML(zip([("META-INF/container.xml", container), ("score.xml", validScore)])))
        XCTAssertThrowsError(try CloudResultValidation.validateMusicXML(zip([("score.xml", validScore)]))) { error in
            XCTAssertTrue(error.localizedDescription.contains("container.xml"))
        }
    }

    func testMXLRejectsUnsafePathsMissingRootAndCorruptPayload() throws {
        XCTAssertThrowsError(try CloudResultValidation.validateMusicXML(zip([("../score.xml", validScore)])))
        let container = Data("<container><rootfiles><rootfile full-path='missing.xml'/></rootfiles></container>".utf8)
        XCTAssertThrowsError(try CloudResultValidation.validateMusicXML(zip([("META-INF/container.xml", container), ("score.xml", validScore)])))
        let validContainer = Data("<container><rootfiles><rootfile full-path='score.xml'/></rootfiles></container>".utf8)
        var corrupted = try zip([("score.xml", validScore), ("META-INF/container.xml", validContainer)])
        corrupted[30 + "score.xml".utf8.count + 1] ^= 1
        XCTAssertThrowsError(try CloudResultValidation.validateMusicXML(corrupted)) { error in
            XCTAssertTrue(error.localizedDescription.contains("校验失败"), "Valid container must reach the corrupted score's CRC check")
        }
        XCTAssertThrowsError(try CloudResultValidation.validateMusicXML(Data([80, 75, 3, 4])))
    }

    func testInvalidStructuredImportRemovesItsOwnedCopy() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let storage = try DocumentStorage(root: root.appendingPathComponent("library"))
        let file = root.appendingPathComponent("invalid.musicxml")
        try Data("<html>expired download</html>".utf8).write(to: file)
        XCTAssertThrowsError(try storage.importFile(file))
        XCTAssertTrue(try FileManager.default.contentsOfDirectory(atPath: storage.root.path).isEmpty)
        let handle = try FileHandle(forWritingTo: file)
        try handle.truncate(atOffset: UInt64(CloudResultValidation.maximumPracticeBytes + 1))
        try handle.close()
        XCTAssertThrowsError(try storage.importFile(file))
        XCTAssertTrue(try FileManager.default.contentsOfDirectory(atPath: storage.root.path).isEmpty)
    }

    /// Small independent ZIP fixtures cover both supported compression methods and CRC handling.
    private func zip(_ files: [(String, Data)], deflated: Bool = false) throws -> Data {
        var output = Data(), directory = Data()
        func append(_ value: Int, bytes: Int, to target: inout Data) {
            for offset in 0..<bytes { target.append(UInt8(truncatingIfNeeded: value >> (8 * offset))) }
        }
        for (name, source) in files {
            let encoded = Data(name.utf8), offset = output.count
            let checksum = source.withUnsafeBytes { crc32(0, $0.bindMemory(to: Bytef.self).baseAddress, uInt(source.count)) }
            let packed: Data
            if deflated {
                var stream = z_stream()
                XCTAssertEqual(deflateInit2_(&stream, Z_DEFAULT_COMPRESSION, Z_DEFLATED, -MAX_WBITS, 8, Z_DEFAULT_STRATEGY,
                                             ZLIB_VERSION, Int32(MemoryLayout<z_stream>.size)), Z_OK)
                defer { deflateEnd(&stream) }
                var buffer = Data(count: Int(compressBound(uLong(source.count))))
                let status = source.withUnsafeBytes { input in
                    buffer.withUnsafeMutableBytes { result -> Int32 in
                        stream.next_in = UnsafeMutablePointer<Bytef>(mutating: input.bindMemory(to: Bytef.self).baseAddress)
                        stream.avail_in = uInt(source.count)
                        stream.next_out = result.bindMemory(to: Bytef.self).baseAddress
                        stream.avail_out = uInt(result.count)
                        return deflate(&stream, Z_FINISH)
                    }
                }
                XCTAssertEqual(status, Z_STREAM_END)
                buffer.count = Int(stream.total_out)
                packed = buffer
            } else { packed = source }
            append(0x04034b50, bytes: 4, to: &output)
            for value in [20, 0, deflated ? 8 : 0, 0, 0] { append(value, bytes: 2, to: &output) }
            for value in [Int(checksum), packed.count, source.count] { append(value, bytes: 4, to: &output) }
            append(encoded.count, bytes: 2, to: &output); append(0, bytes: 2, to: &output)
            output.append(encoded); output.append(packed)
            append(0x02014b50, bytes: 4, to: &directory)
            for value in [20, 20, 0, deflated ? 8 : 0, 0, 0] { append(value, bytes: 2, to: &directory) }
            for value in [Int(checksum), packed.count, source.count] { append(value, bytes: 4, to: &directory) }
            for value in [encoded.count, 0, 0, 0, 0] { append(value, bytes: 2, to: &directory) }
            append(0, bytes: 4, to: &directory); append(offset, bytes: 4, to: &directory); directory.append(encoded)
        }
        let directoryOffset = output.count
        output.append(directory)
        append(0x06054b50, bytes: 4, to: &output)
        for value in [0, 0, files.count, files.count] { append(value, bytes: 2, to: &output) }
        append(directory.count, bytes: 4, to: &output); append(directoryOffset, bytes: 4, to: &output)
        append(0, bytes: 2, to: &output)
        return output
    }
}
