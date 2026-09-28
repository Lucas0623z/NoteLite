import AudiverisCore
import CoreGraphics
import ImageIO
import PDFKit
import UniformTypeIdentifiers
import XCTest
@testable import NoteLite

final class LocalOMRTests: XCTestCase {
    private var root: URL!

    override func setUpWithError() throws {
        root = FileManager.default.temporaryDirectory.appendingPathComponent("local-omr-tests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try FileManager.default.removeItem(at: root)
    }

    func testPNGTransparencyIsCompositedOntoWhite() throws {
        let url = root.appendingPathComponent("transparent.png")
        var pixels = [UInt8](repeating: 0, count: 12 * 8 * 4)
        for y in 2..<5 {
            for x in 3..<7 { pixels[(y * 12 + x) * 4 + 3] = 255 }
        }
        try writeImage(url: url, width: 12, height: 8, pixels: pixels, type: .png)
        let raster = try LocalOMRProcessor.rasterizeSynchronously(url: url, pageIndex: 0)
        XCTAssertEqual(raster.image.width, 12)
        XCTAssertEqual(raster.image.height, 8)
        XCTAssertEqual(raster.image.pixels.filter { $0 == 0 }.count, 12)
        XCTAssertEqual(raster.image.pixels.filter { $0 == 255 }.count, 84)
        XCTAssertEqual(raster.image.pixels[3 * 12 + 4], 0)
        XCTAssertEqual(raster.image.pixels[0], 255)
    }

    func testTIFFAppliesAllEightEXIFOrientations() throws {
        let width = 40, height = 24, sampleX = 4, sampleY = 3
        let pixels = rgba(width: width, height: height) { x, y in x < 10 && y < 8 ? 0 : 255 }
        let positions = [(4, 3), (35, 3), (35, 20), (4, 20), (3, 4), (20, 4), (20, 35), (3, 35)]
        XCTAssertEqual(positions[0].0, sampleX)
        XCTAssertEqual(positions[0].1, sampleY)
        for orientation in 1...8 {
            let url = root.appendingPathComponent("orientation-\(orientation).tiff")
            try writeImage(url: url, width: width, height: height, pixels: pixels, type: .tiff, orientation: orientation)
            let image = try LocalOMRProcessor.rasterizeSynchronously(url: url, pageIndex: 0).image
            XCTAssertEqual(image.width, orientation <= 4 ? width : height, "orientation \(orientation)")
            XCTAssertEqual(image.height, orientation <= 4 ? height : width, "orientation \(orientation)")
            let expected = positions[orientation - 1]
            XCTAssertLessThan(image.pixels[expected.1 * image.width + expected.0], 40, "orientation \(orientation)")
            XCTAssertEqual(image.pixels.filter { $0 < 40 }.count, 80, "orientation \(orientation)")
        }
    }

    func testJPEGColorInputBecomesLuminance() throws {
        let url = root.appendingPathComponent("scan.jpg")
        try writeImage(url: url, width: 48, height: 32,
                       pixels: rgba(width: 48, height: 32) { x, _ in x < 24 ? 0 : 255 }, type: .jpeg)
        let image = try LocalOMRProcessor.rasterizeSynchronously(url: url, pageIndex: 0).image
        XCTAssertEqual(image.width, 48)
        XCTAssertLessThan(image.pixels[16 * 48 + 4], 20)
        XCTAssertGreaterThan(image.pixels[16 * 48 + 44], 235)
    }

    func testPDFSelectionProcessesExactlyRequestedPage() async throws {
        let url = root.appendingPathComponent("two-pages.pdf")
        try writePDF(url: url, pageCount: 2) { context, page in
            context.setFillColor(gray: page == 0 ? 1 : 0, alpha: 1)
            context.fill(CGRect(x: 0, y: 0, width: 200, height: 100))
        }
        let info = try await LocalOMRProcessor.inspect(url: url)
        XCTAssertEqual(info, LocalOMRSourceInfo(kind: .pdf, pageCount: 2))
        let first = try await LocalOMRProcessor.preprocess(url: url, pageIndex: 0)
        let second = try await LocalOMRProcessor.preprocess(url: url, pageIndex: 1)
        XCTAssertEqual(first.pageIndex, 0)
        XCTAssertEqual(second.pageIndex, 1)
        XCTAssertEqual(second.source.pageCount, 2)
        XCTAssertEqual(first.processing.foregroundPixelCount, 0)
        XCTAssertEqual(second.processing.foregroundPixelCount, 400 * 200)
        for index in [-1, 2, Int.max] {
            XCTAssertThrowsError(try LocalOMRProcessor.rasterizeSynchronously(url: url, pageIndex: index)) {
                XCTAssertEqual($0 as? LocalOMRError, .pageOutOfRange(index: index, count: 2))
            }
        }
    }

    func testMultiPageTIFFDoesNotSilentlyChooseFirstFrame() async throws {
        let url = root.appendingPathComponent("two-pages.tiff")
        let first = try image(width: 20, height: 10, pixels: rgba(width: 20, height: 10) { _, _ in 255 })
        let second = try image(width: 20, height: 10, pixels: rgba(width: 20, height: 10) { _, _ in 0 })
        let destination = try XCTUnwrap(CGImageDestinationCreateWithURL(url as CFURL, UTType.tiff.identifier as CFString, 2, nil))
        CGImageDestinationAddImage(destination, first, nil)
        CGImageDestinationAddImage(destination, second, nil)
        XCTAssertTrue(CGImageDestinationFinalize(destination))
        let info = try await LocalOMRProcessor.inspect(url: url)
        XCTAssertEqual(info.pageCount, 2)
        let raster = try LocalOMRProcessor.rasterizeSynchronously(url: url, pageIndex: 1)
        XCTAssertEqual(raster.pageIndex, 1)
        XCTAssertEqual(Set(raster.image.pixels), [0])
        XCTAssertThrowsError(try LocalOMRProcessor.rasterizeSynchronously(url: url, pageIndex: 2))
    }

    func testPDFCropOriginAndRotationAreAppliedOnce() throws {
        let input = root.appendingPathComponent("uncropped.pdf")
        let url = root.appendingPathComponent("cropped.pdf")
        try writePDF(url: input, pageCount: 1) { context, _ in
            context.setFillColor(gray: 0, alpha: 1)
            // This rectangle is outside the crop and must be absent.
            context.fill(CGRect(x: 0, y: 0, width: 40, height: 100))
            context.fill(CGRect(x: 60, y: 25, width: 10, height: 10))
        }
        let document = try XCTUnwrap(PDFDocument(url: input))
        let page = try XCTUnwrap(document.page(at: 0))
        page.setBounds(CGRect(x: 50, y: 20, width: 80, height: 40), for: .cropBox)
        var limits = LocalOMRLimits.default
        limits.pdfPixelsPerPoint = 1
        for (rotation, width, height, x, y) in [(0, 80, 40, 15, 30), (90, 40, 80, 10, 15),
                                                (180, 80, 40, 65, 10), (270, 40, 80, 30, 65)] {
            page.rotation = rotation
            XCTAssertTrue(document.write(to: url))
            let raster = try LocalOMRProcessor.rasterizeSynchronously(url: url, pageIndex: 0, limits: limits)
            XCTAssertEqual(raster.image.width, width, "rotation \(rotation)")
            XCTAssertEqual(raster.image.height, height, "rotation \(rotation)")
            XCTAssertEqual(raster.image.pixels[y * width + x], 0, "rotation \(rotation)")
            XCTAssertEqual(raster.image.pixels.filter { $0 < 128 }.count, 100, "rotation \(rotation)")
        }
    }

    func testRasterLimitsDownsampleAndFileLimitFailsBeforeDecode() throws {
        let url = root.appendingPathComponent("large.png")
        try writeImage(url: url, width: 100, height: 80,
                       pixels: rgba(width: 100, height: 80) { _, _ in 255 }, type: .png)
        var limits = LocalOMRLimits.default
        limits.maxDimension = 40
        limits.maxPixelCount = 600
        let image = try LocalOMRProcessor.rasterizeSynchronously(url: url, pageIndex: 0, limits: limits).image
        XCTAssertLessThanOrEqual(max(image.width, image.height), 40)
        XCTAssertLessThanOrEqual(image.pixels.count, 600)
        XCTAssertGreaterThan(image.pixels.count, 400)
        limits.maxFileBytes = 1
        XCTAssertThrowsError(try LocalOMRProcessor.rasterizeSynchronously(url: url, pageIndex: 0, limits: limits)) {
            XCTAssertEqual($0 as? LocalOMRError, .fileTooLarge)
        }
        limits.maxDimension = 0
        XCTAssertThrowsError(try LocalOMRProcessor.rasterizeSynchronously(url: url, pageIndex: 0, limits: limits)) {
            XCTAssertEqual($0 as? LocalOMRError, .invalidLimits)
        }
    }

    func testCancellationAtRasterBoundaryAndAsyncEntry() async throws {
        let url = root.appendingPathComponent("cancel.png")
        try writeImage(url: url, width: 40, height: 24,
                       pixels: rgba(width: 40, height: 24) { _, _ in 255 }, type: .png)
        var checks = 0
        XCTAssertThrowsError(try LocalOMRProcessor.rasterizeSynchronously(url: url, pageIndex: 0, cancellationCheck: {
            checks += 1
            if checks == 4 { throw CancellationError() }
        })) { XCTAssertTrue($0 is CancellationError) }
        XCTAssertEqual(checks, 4)
        let operation = Task {
            withUnsafeCurrentTask { $0?.cancel() }
            return try await LocalOMRProcessor.preprocess(url: url, pageIndex: 0)
        }
        do {
            _ = try await operation.value
            XCTFail("A cancelled caller must not publish a page result")
        } catch { XCTAssertTrue(error is CancellationError) }
    }

    func testRejectsRemoteURLsAndMalformedFiles() async throws {
        do {
            _ = try await LocalOMRProcessor.inspect(url: try XCTUnwrap(URL(string: "https://example.invalid/score.pdf")))
            XCTFail("Local adapter must not accept a network input")
        } catch { XCTAssertEqual(error as? LocalOMRError, .invalidSource) }
        let url = root.appendingPathComponent("broken.png")
        try Data("not an image".utf8).write(to: url)
        XCTAssertThrowsError(try LocalOMRProcessor.rasterizeSynchronously(url: url, pageIndex: 0))
    }

    #if DEBUG
    func testGeneratedStaffPDFRunsCompleteLocalPreprocessingPipeline() async throws {
        let url = root.appendingPathComponent("synthetic-staff.pdf")
        try LocalOMRDebugFixture.writeStaffPDF(to: url)
        let result = try await LocalOMRProcessor.preprocess(url: url, pageIndex: 0)
        let processing = result.processing
        XCTAssertEqual(processing.binaryImage.width, 800)
        XCTAssertEqual(processing.binaryImage.height, 400)
        XCTAssertGreaterThan(processing.foregroundPixelCount, 6_000)
        XCTAssertLessThan(processing.foregroundPixelCount, 15_000)
        XCTAssertEqual(processing.horizontalRuns.foregroundPixelCount, processing.verticalRuns.foregroundPixelCount)
        XCTAssertGreaterThanOrEqual(processing.horizontalRuns.sequences.flatMap { $0 }.filter { $0.length >= 670 }.count, 10)
        XCTAssertNotNil(result.previewImage())
        XCTAssertEqual(result.source.pageCount, 1)
        let repeated = try await LocalOMRProcessor.preprocess(url: url, pageIndex: 0)
        XCTAssertEqual(processing, repeated.processing, "Repeated local runs must be deterministic")
    }
    #endif

    private func rgba(width: Int, height: Int, value: (Int, Int) -> UInt8) -> [UInt8] {
        var pixels = [UInt8]()
        pixels.reserveCapacity(width * height * 4)
        for y in 0..<height {
            for x in 0..<width {
                let gray = value(x, y)
                pixels.append(contentsOf: [gray, gray, gray, 255])
            }
        }
        return pixels
    }

    private func image(width: Int, height: Int, pixels: [UInt8]) throws -> CGImage {
        let provider = try XCTUnwrap(CGDataProvider(data: Data(pixels) as CFData))
        return try XCTUnwrap(CGImage(width: width, height: height, bitsPerComponent: 8, bitsPerPixel: 32,
                                    bytesPerRow: width * 4, space: CGColorSpaceCreateDeviceRGB(),
                                    bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.last.rawValue),
                                    provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent))
    }

    private func writeImage(url: URL, width: Int, height: Int, pixels: [UInt8], type: UTType,
                            orientation: Int = 1) throws {
        let destination = try XCTUnwrap(CGImageDestinationCreateWithURL(url as CFURL, type.identifier as CFString, 1, nil))
        let properties: [CFString: Any] = [kCGImagePropertyOrientation: orientation,
                                           kCGImageDestinationLossyCompressionQuality: 1.0]
        CGImageDestinationAddImage(destination, try image(width: width, height: height, pixels: pixels), properties as CFDictionary)
        XCTAssertTrue(CGImageDestinationFinalize(destination))
    }

    private func writePDF(url: URL, pageCount: Int, draw: (CGContext, Int) -> Void) throws {
        var box = CGRect(x: 0, y: 0, width: 200, height: 100)
        let consumer = try XCTUnwrap(CGDataConsumer(url: url as CFURL))
        let context = try XCTUnwrap(CGContext(consumer: consumer, mediaBox: &box, nil))
        for page in 0..<pageCount {
            context.beginPDFPage(nil)
            context.setFillColor(gray: 1, alpha: 1)
            context.fill(box)
            draw(context, page)
            context.endPDFPage()
        }
        context.closePDF()
    }
}
