import CoreGraphics
import ImageIO
import PDFKit
import UniformTypeIdentifiers
import XCTest
@testable import NoteLite

final class EmbeddedOMRInputPreparationTests: XCTestCase {
    private var root: URL!
    private var staged: URL { root.appendingPathComponent("staged") }

    override func setUpWithError() throws {
        root = FileManager.default.temporaryDirectory.appendingPathComponent("engine-input-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws { try FileManager.default.removeItem(at: root) }

    func testOrdinaryPNGAndJPEGKeepExactSourceBytesIncludingOpaqueAlpha() throws {
        for type in [UTType.png, .jpeg] {
            let source = root.appendingPathComponent(UUID().uuidString + "." + type.preferredFilenameExtension!)
            try writeImage(source, type: type, orientations: [1])
            let original = try Data(contentsOf: source)
            let prepared = try EmbeddedOMRInputPreparer.prepare(source: source, in: staged)
            XCTAssertTrue(prepared.preservedOriginalBytes)
            XCTAssertFalse(prepared.normalized)
            XCTAssertFalse(prepared.downsampled)
            XCTAssertEqual(prepared.pageCount, 1)
            XCTAssertNotEqual(source, prepared.url)
            XCTAssertEqual(try Data(contentsOf: prepared.url), original)
            XCTAssertEqual(try Data(contentsOf: source), original)
        }
    }

    func testJPEGWithEXIFRotationStagesLosslessPNG() throws {
        let source = root.appendingPathComponent("rotated.jpg")
        try writeImage(source, type: .jpeg, orientations: [6])
        let original = try Data(contentsOf: source)
        let result = try EmbeddedOMRInputPreparer.prepare(source: source, in: staged)
        XCTAssertEqual(result.url.pathExtension, "png")
        XCTAssertTrue(result.normalized)
        XCTAssertFalse(result.downsampled)
        XCTAssertFalse(result.preservedOriginalBytes)
        let pixels = try LocalOMRProcessor.rasterizeSynchronously(url: result.url, pageIndex: 0).image
        XCTAssertEqual(pixels.width, 24)
        XCTAssertEqual(pixels.height, 40)
        XCTAssertLessThan(pixels.pixels[4 * 24 + 20], 40)
        XCTAssertEqual(try Data(contentsOf: source), original)
    }

    func testEveryTIFFPageAndAllEightOrientationsSurviveNormalization() throws {
        let source = root.appendingPathComponent("eight-pages.tiff")
        try writeImage(source, type: .tiff, orientations: Array(1...8))
        let result = try EmbeddedOMRInputPreparer.prepare(source: source, in: staged)
        XCTAssertEqual(result.pageCount, 8)
        XCTAssertEqual(result.url.pathExtension, "tiff")
        let images = try XCTUnwrap(CGImageSourceCreateWithURL(result.url as CFURL, nil))
        XCTAssertEqual(CGImageSourceGetCount(images), 8)
        let points = [(4, 3), (35, 3), (35, 20), (4, 20), (3, 4), (20, 4), (20, 35), (3, 35)]
        for index in 0..<8 {
            let properties = try XCTUnwrap(CGImageSourceCopyPropertiesAtIndex(images, index, nil) as? [CFString: Any])
            XCTAssertEqual((properties[kCGImagePropertyOrientation] as? NSNumber)?.intValue ?? 1, 1)
            let image = try LocalOMRProcessor.rasterizeSynchronously(url: result.url, pageIndex: index).image
            XCTAssertEqual(image.width, index < 4 ? 40 : 24)
            XCTAssertEqual(image.height, index < 4 ? 24 : 40)
            XCTAssertEqual(image.pixels[points[index].1 * image.width + points[index].0], 0)
            XCTAssertEqual(image.pixels.filter { $0 == 0 }.count, 80)
        }
    }

    func testUnchangedMultiPageTIFFIsCopiedWithoutReencoding() throws {
        let source = root.appendingPathComponent("unchanged.tiff")
        try writeImage(source, type: .tiff, orientations: [1, 1, 1])
        let result = try EmbeddedOMRInputPreparer.prepare(source: source, in: staged)
        XCTAssertEqual(result.pageCount, 3)
        XCTAssertTrue(result.preservedOriginalBytes)
        XCTAssertEqual(try Data(contentsOf: source), try Data(contentsOf: result.url))
    }

    func testTransparentBlackPixelsBecomeWhiteForEngineThatDiscardsAlpha() throws {
        let source = root.appendingPathComponent("transparent.png")
        try writeImage(source, type: .png, orientations: [1], transparent: true)
        let result = try EmbeddedOMRInputPreparer.prepare(source: source, in: staged)
        XCTAssertTrue(result.normalized)
        XCTAssertFalse(result.preservedOriginalBytes)
        let images = try XCTUnwrap(CGImageSourceCreateWithURL(result.url as CFURL, nil))
        let decoded = try XCTUnwrap(CGImageSourceCreateImageAtIndex(images, 0, nil))
        XCTAssertTrue([CGImageAlphaInfo.none, .noneSkipFirst, .noneSkipLast].contains(decoded.alphaInfo))
        let pixels = try LocalOMRProcessor.rasterizeSynchronously(url: result.url, pageIndex: 0).image.pixels
        XCTAssertEqual(pixels.filter { $0 == 0 }.count, 80)
        XCTAssertEqual(pixels.filter { $0 == 255 }.count, 40 * 24 - 80)
    }

    func testOversizedImagesAreDownsampledAndTIFFPageCountIsUnchanged() throws {
        let source = root.appendingPathComponent("large.tiff")
        try writeImage(source, type: .tiff, orientations: [1, 6])
        var limits = EmbeddedOMRInputLimits.default
        limits.maxDimension = 20
        limits.maxPixelsPerPage = 200
        let result = try EmbeddedOMRInputPreparer.prepare(source: source, in: staged, limits: limits)
        XCTAssertTrue(result.downsampled)
        XCTAssertEqual(result.pageCount, 2)
        for page in 0..<2 {
            let image = try LocalOMRProcessor.rasterizeSynchronously(url: result.url, pageIndex: page).image
            XCTAssertLessThanOrEqual(max(image.width, image.height), 20)
            XCTAssertLessThanOrEqual(image.pixels.count, 200)
        }
    }

    func testWholePDFAndRotationsAreCopiedByteForByte() throws {
        let source = root.appendingPathComponent("two-pages.pdf")
        var box = CGRect(x: 0, y: 0, width: 200, height: 100)
        let consumer = try XCTUnwrap(CGDataConsumer(url: source as CFURL))
        let context = try XCTUnwrap(CGContext(consumer: consumer, mediaBox: &box, nil))
        for _ in 0..<2 { context.beginPDFPage(nil); context.endPDFPage() }
        context.closePDF()
        let pdf = try XCTUnwrap(PDFDocument(url: source))
        let secondPage = try XCTUnwrap(pdf.page(at: 1))
        secondPage.rotation = 90
        XCTAssertTrue(pdf.write(to: source))
        let result = try EmbeddedOMRInputPreparer.prepare(source: source, in: staged)
        XCTAssertEqual(result.pageCount, 2)
        XCTAssertTrue(result.preservedOriginalBytes)
        XCTAssertEqual(try Data(contentsOf: source), try Data(contentsOf: result.url))
        XCTAssertEqual(PDFDocument(url: result.url)?.page(at: 1)?.rotation, 90)
    }

    func testLimitsRejectEntireDocumentAndLeaveNoPartialStage() throws {
        let source = root.appendingPathComponent("pages.tiff")
        try writeImage(source, type: .tiff, orientations: [1, 6])
        var limits = EmbeddedOMRInputLimits.default
        limits.maxPageCount = 1
        XCTAssertThrowsError(try EmbeddedOMRInputPreparer.prepare(source: source, in: staged, limits: limits)) {
            XCTAssertEqual($0 as? EmbeddedOMRInputError, .tooManyPages)
        }
        limits = .default
        limits.maxTotalImagePixels = 1_000
        XCTAssertThrowsError(try EmbeddedOMRInputPreparer.prepare(source: source, in: staged, limits: limits)) {
            XCTAssertEqual($0 as? EmbeddedOMRInputError, .imageTooLarge)
        }
        limits = .default
        limits.maxSourcePixelsPerPage = 500
        XCTAssertThrowsError(try EmbeddedOMRInputPreparer.prepare(source: source, in: staged, limits: limits)) {
            XCTAssertEqual($0 as? EmbeddedOMRInputError, .imageTooLarge)
        }
        limits = .default
        limits.maxFileBytes = 1
        XCTAssertThrowsError(try EmbeddedOMRInputPreparer.prepare(source: source, in: staged, limits: limits)) {
            XCTAssertEqual($0 as? EmbeddedOMRInputError, .fileTooLarge)
        }
        XCTAssertFalse(FileManager.default.fileExists(atPath: staged.path))
        limits = .default
        limits.maxPreparedFileBytes = 1
        XCTAssertThrowsError(try EmbeddedOMRInputPreparer.prepare(source: source, in: staged, limits: limits)) {
            XCTAssertEqual($0 as? EmbeddedOMRInputError, .preparedFileTooLarge)
        }
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: staged.path), [])
    }

    func testPDFRasterLimitsRejectWholeDocumentBeforeStaging() throws {
        // The second page alone exceeds 16M pixels at the engine's 300 DPI,
        // despite a tiny file and both raster edges being below 8192 pixels.
        for dimensions in [CGSize(width: 1_000, height: 1_000), CGSize(width: 5_000, height: 100)] {
            let source = root.appendingPathComponent(UUID().uuidString + ".pdf")
            try writePDF(source, sizes: [CGSize(width: 200, height: 100), dimensions])
            XCTAssertThrowsError(try EmbeddedOMRInputPreparer.prepare(source: source, in: staged)) {
                XCTAssertEqual($0 as? EmbeddedOMRInputError, .imageTooLarge)
            }
            XCTAssertFalse(FileManager.default.fileExists(atPath: staged.path))
            XCTAssertEqual(PDFDocument(url: source)?.pageCount, 2)
        }
        let source = root.appendingPathComponent("aggregate.pdf")
        try writePDF(source, sizes: Array(repeating: CGSize(width: 200, height: 100), count: 2))
        var limits = EmbeddedOMRInputLimits.default
        limits.maxTotalImagePixels = 500_000 // Each page is 833 x 416; both exceed the total.
        XCTAssertThrowsError(try EmbeddedOMRInputPreparer.prepare(source: source, in: staged, limits: limits)) {
            XCTAssertEqual($0 as? EmbeddedOMRInputError, .imageTooLarge)
        }
        XCTAssertFalse(FileManager.default.fileExists(atPath: staged.path))
    }

    func testPDFUsesEffectiveCropAtEngineResolutionAndPreservesRotation() throws {
        let source = root.appendingPathComponent("large-media-small-crop.pdf")
        try writePDF(source, sizes: [CGSize(width: 10_000, height: 10_000)])
        let document = try XCTUnwrap(PDFDocument(url: source))
        let page = try XCTUnwrap(document.page(at: 0))
        page.setBounds(CGRect(x: 300, y: 400, width: 200, height: 100), for: .cropBox)
        page.rotation = 270
        XCTAssertTrue(document.write(to: source))
        let original = try Data(contentsOf: source)
        var limits = EmbeddedOMRInputLimits.default
        limits.maxDimension = 833
        limits.maxPixelsPerPage = 833 * 416 // Exactly PDFBox's Float/floor dimensions.
        let result = try EmbeddedOMRInputPreparer.prepare(source: source, in: staged, limits: limits)
        XCTAssertTrue(result.preservedOriginalBytes)
        XCTAssertEqual(try Data(contentsOf: result.url), original)
        XCTAssertEqual(PDFDocument(url: result.url)?.page(at: 0)?.rotation, 270)
        limits.maxPixelsPerPage -= 1
        XCTAssertThrowsError(try EmbeddedOMRInputPreparer.prepare(source: source, in: staged, limits: limits)) {
            XCTAssertEqual($0 as? EmbeddedOMRInputError, .imageTooLarge)
        }
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: staged.path), [result.url.lastPathComponent])
    }

    func testCancellationDuringMultiPageEncodingRemovesTemporaryFile() throws {
        let source = root.appendingPathComponent("cancel.tiff")
        try writeImage(source, type: .tiff, orientations: [6, 6, 6])
        var sawPartialFile = false
        XCTAssertThrowsError(try EmbeddedOMRInputPreparer.prepare(source: source, in: staged, cancellationCheck: {
            if let items = FileManager.default.enumerator(at: self.staged, includingPropertiesForKeys: [.isRegularFileKey]) {
                for case let file as URL in items {
                    if try file.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile == true {
                        sawPartialFile = true
                        throw CancellationError()
                    }
                }
            }
        })) { XCTAssertTrue($0 is CancellationError) }
        XCTAssertTrue(sawPartialFile)
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: staged.path), [])
        XCTAssertTrue(FileManager.default.fileExists(atPath: source.path))
    }

    func testRemoteAndMalformedInputsDoNotCreateStagedFiles() throws {
        let remote = try XCTUnwrap(URL(string: "https://example.invalid/score.pdf"))
        XCTAssertThrowsError(try EmbeddedOMRInputPreparer.prepare(source: remote, in: staged)) {
            XCTAssertEqual($0 as? EmbeddedOMRInputError, .invalidFile)
        }
        let malformed = root.appendingPathComponent("broken.png")
        try Data("broken image".utf8).write(to: malformed)
        XCTAssertThrowsError(try EmbeddedOMRInputPreparer.prepare(source: malformed, in: staged))
        XCTAssertFalse(FileManager.default.fileExists(atPath: staged.path))
    }

    private func writePDF(_ url: URL, sizes: [CGSize]) throws {
        var box = CGRect(origin: .zero, size: sizes[0])
        let consumer = try XCTUnwrap(CGDataConsumer(url: url as CFURL))
        let context = try XCTUnwrap(CGContext(consumer: consumer, mediaBox: &box, nil))
        for size in sizes {
            var pageBox = CGRect(origin: .zero, size: size)
            let data = Data(bytes: &pageBox, count: MemoryLayout<CGRect>.size)
            context.beginPDFPage([kCGPDFContextMediaBox as String: data] as CFDictionary)
            context.endPDFPage()
        }
        context.closePDF()
    }

    private func writeImage(_ url: URL, type: UTType, orientations: [Int], transparent: Bool = false) throws {
        var rgba = [UInt8]()
        for y in 0..<24 {
            for x in 0..<40 {
                let black = x < 10 && y < 8
                let value: UInt8 = black || transparent ? 0 : 255
                rgba.append(contentsOf: [value, value, value, black || !transparent ? 255 : 0])
            }
        }
        let provider = try XCTUnwrap(CGDataProvider(data: Data(rgba) as CFData))
        let image = try XCTUnwrap(CGImage(width: 40, height: 24, bitsPerComponent: 8, bitsPerPixel: 32,
                                        bytesPerRow: 40 * 4, space: CGColorSpaceCreateDeviceRGB(),
                                        bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.last.rawValue),
                                        provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent))
        let destination = try XCTUnwrap(CGImageDestinationCreateWithURL(url as CFURL, type.identifier as CFString, orientations.count, nil))
        for orientation in orientations {
            CGImageDestinationAddImage(destination, image, [kCGImagePropertyOrientation: orientation,
                                                          kCGImageDestinationLossyCompressionQuality: 1.0] as CFDictionary)
        }
        XCTAssertTrue(CGImageDestinationFinalize(destination))
    }
}
