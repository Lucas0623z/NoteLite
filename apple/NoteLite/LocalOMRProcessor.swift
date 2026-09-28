import AudiverisCore
import CoreGraphics
import Foundation
import ImageIO
import PDFKit
import UniformTypeIdentifiers

/// Device-side input adapter for the first Audiveris port. It produces a binary
/// raster and foreground runs, not recognized notes or a playable score.
struct LocalOMRLimits: Sendable {
    var maxFileBytes = 50 * 1024 * 1024
    var maxDimension = 2_400
    var maxPixelCount = 4_000_000
    var pdfPixelsPerPoint: Double = 2
    static let `default` = LocalOMRLimits()

    fileprivate func validate() throws {
        guard maxFileBytes > 0, maxDimension > 0, maxDimension <= 8_192,
              maxPixelCount > 0, maxPixelCount <= 16_000_000,
              pdfPixelsPerPoint.isFinite, pdfPixelsPerPoint > 0 else {
            throw LocalOMRError.invalidLimits
        }
    }
}

struct LocalOMRSourceInfo: Equatable, Sendable {
    enum Kind: String, Sendable { case pdf, image }
    let kind: Kind
    let pageCount: Int
}

struct LocalOMRRaster: Sendable {
    let image: GrayImage
    let source: LocalOMRSourceInfo
    let pageIndex: Int
}

struct LocalOMRPageResult: Sendable {
    let processing: PreprocessingResult
    let source: LocalOMRSourceInfo
    let pageIndex: Int

    func previewImage() -> CGImage? {
        let image = processing.binaryImage
        guard let provider = CGDataProvider(data: Data(image.pixels) as CFData) else { return nil }
        return CGImage(width: image.width, height: image.height, bitsPerComponent: 8,
                       bitsPerPixel: 8, bytesPerRow: image.width,
                       space: CGColorSpaceCreateDeviceGray(), bitmapInfo: CGBitmapInfo(rawValue: 0),
                       provider: provider, decode: nil, shouldInterpolate: false,
                       intent: .defaultIntent)
    }
}

enum LocalOMRError: LocalizedError, Equatable {
    case invalidLimits, invalidSource, unsupportedSource, encryptedPDF, emptyDocument
    case fileTooLarge, invalidDimensions, pageOutOfRange(index: Int, count: Int), renderingFailed

    var errorDescription: String? {
        switch self {
        case .invalidLimits: return "本地处理的资源限制无效。"
        case .invalidSource: return "无法读取这个本地文件。"
        case .unsupportedSource: return "请选择 PDF、PNG、JPEG 或 TIFF 文件。"
        case .encryptedPDF: return "请先解锁 PDF，再导入本地测试。"
        case .emptyDocument: return "这个文件没有可处理的页面。"
        case .fileTooLarge: return "文件超过本地测试的大小限制。"
        case .invalidDimensions: return "页面尺寸无效或超过本地处理限制。"
        case .pageOutOfRange(_, let count): return "请选择 1 至 \(count) 页中的一页。"
        case .renderingFailed: return "无法将这一页转换为本地图像。"
        }
    }
}

enum LocalOMRProcessor {
    static func inspect(url: URL, limits: LocalOMRLimits = .default) async throws -> LocalOMRSourceInfo {
        try Task.checkCancellation()
        let worker = Task.detached(priority: .userInitiated) {
            try withSource(url: url, limits: limits) { source in source.info }
        }
        return try await withTaskCancellationHandler(operation: {
            let result = try await worker.value
            try Task.checkCancellation()
            return result
        }, onCancel: { worker.cancel() })
    }

    /// The page is required even for a single-page document. A result always
    /// identifies the selected page and total page count; it is never a full-document result.
    static func preprocess(url: URL, pageIndex: Int, limits: LocalOMRLimits = .default,
                           configuration: PreprocessingConfiguration = .default) async throws -> LocalOMRPageResult {
        try Task.checkCancellation()
        let worker = Task.detached(priority: .userInitiated) {
            let raster = try rasterizeSynchronously(url: url, pageIndex: pageIndex, limits: limits)
            let processing = try AudiverisPreprocessor.preprocess(raster.image, configuration: configuration,
                                                                 cancellationCheck: { try Task.checkCancellation() })
            try Task.checkCancellation()
            return LocalOMRPageResult(processing: processing, source: raster.source, pageIndex: pageIndex)
        }
        return try await withTaskCancellationHandler(operation: {
            let result = try await worker.value
            try Task.checkCancellation()
            return result
        }, onCancel: { worker.cancel() })
    }

    // Internal synchronous entry permits deterministic raster/cancellation tests.
    // Application callers use the async methods above, which never rasterize on the main actor.
    static func rasterizeSynchronously(url: URL, pageIndex: Int, limits: LocalOMRLimits = .default,
                                      cancellationCheck: () throws -> Void = { try Task.checkCancellation() }) throws -> LocalOMRRaster {
        try cancellationCheck()
        return try withSource(url: url, limits: limits) { source in
            guard (0..<source.info.pageCount).contains(pageIndex) else {
                throw LocalOMRError.pageOutOfRange(index: pageIndex, count: source.info.pageCount)
            }
            try cancellationCheck()
            let image: GrayImage
            switch source {
            case .pdf(let document):
                guard let page = document.page(at: pageIndex)?.pageRef else { throw LocalOMRError.renderingFailed }
                // Quartz's drawing transform accounts for CropBox origin and the
                // page's own /Rotate. Passing that rotation again would rotate twice.
                let crop = page.getBoxRect(.cropBox).intersection(page.getBoxRect(.mediaBox))
                let angle = ((Int(page.rotationAngle) % 360) + 360) % 360
                let swapsAxes = angle == 90 || angle == 270
                let width = Double(swapsAxes ? crop.height : crop.width) * limits.pdfPixelsPerPoint
                let height = Double(swapsAxes ? crop.width : crop.height) * limits.pdfPixelsPerPoint
                let size = try boundedSize(width: width, height: height, limits: limits)
                image = try grayscale(width: size.width, height: size.height, cancellationCheck: cancellationCheck) { context in
                    let target = CGRect(x: 0, y: 0, width: size.width, height: size.height)
                    context.clip(to: target)
                    context.concatenate(page.getDrawingTransform(.cropBox, rect: target, rotate: 0, preserveAspectRatio: true))
                    context.drawPDFPage(page)
                }
            case .image(let source):
                guard let properties = CGImageSourceCopyPropertiesAtIndex(source, pageIndex, nil) as? [CFString: Any],
                      let width = properties[kCGImagePropertyPixelWidth] as? NSNumber,
                      let height = properties[kCGImagePropertyPixelHeight] as? NSNumber else {
                    throw LocalOMRError.invalidDimensions
                }
                let size = try boundedSize(width: width.doubleValue, height: height.doubleValue, limits: limits)
                let options: [CFString: Any] = [
                    kCGImageSourceCreateThumbnailFromImageAlways: true,
                    kCGImageSourceCreateThumbnailWithTransform: true,
                    kCGImageSourceThumbnailMaxPixelSize: max(size.width, size.height),
                    kCGImageSourceShouldCacheImmediately: true
                ]
                try cancellationCheck()
                // ImageIO applies all EXIF orientations (including mirrored ones)
                // while decoding at the bounded size, avoiding a full-size bitmap.
                guard let thumbnail = CGImageSourceCreateThumbnailAtIndex(source, pageIndex, options as CFDictionary) else {
                    throw LocalOMRError.renderingFailed
                }
                guard thumbnail.width > 0, thumbnail.height > 0,
                      thumbnail.width <= limits.maxDimension, thumbnail.height <= limits.maxDimension else {
                    throw LocalOMRError.invalidDimensions
                }
                // ImageIO can round the shorter edge up by one pixel. Reapply
                // the pixel budget after orientation/decoder rounding.
                let output = try boundedSize(width: Double(thumbnail.width), height: Double(thumbnail.height), limits: limits)
                image = try grayscale(width: output.width, height: output.height, cancellationCheck: cancellationCheck) { context in
                    context.draw(thumbnail, in: CGRect(x: 0, y: 0, width: output.width, height: output.height))
                }
            }
            try cancellationCheck()
            return LocalOMRRaster(image: image, source: source.info, pageIndex: pageIndex)
        }
    }

    private enum Source {
        case pdf(PDFDocument), image(CGImageSource)
        var info: LocalOMRSourceInfo {
            switch self {
            case .pdf(let pdf): return LocalOMRSourceInfo(kind: .pdf, pageCount: pdf.pageCount)
            case .image(let image): return LocalOMRSourceInfo(kind: .image, pageCount: CGImageSourceGetCount(image))
            }
        }
    }

    private static func withSource<T>(url: URL, limits: LocalOMRLimits, body: (Source) throws -> T) throws -> T {
        try limits.validate()
        try Task.checkCancellation()
        guard url.isFileURL else { throw LocalOMRError.invalidSource }
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        let attributes = try url.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey])
        guard attributes.isRegularFile == true, let bytes = attributes.fileSize, bytes > 0 else {
            throw LocalOMRError.invalidSource
        }
        guard bytes <= limits.maxFileBytes else { throw LocalOMRError.fileTooLarge }
        let source: Source
        if url.pathExtension.lowercased() == "pdf" {
            guard let pdf = PDFDocument(url: url) else { throw LocalOMRError.invalidSource }
            guard !pdf.isLocked else { throw LocalOMRError.encryptedPDF }
            source = .pdf(pdf)
        } else {
            guard let image = CGImageSourceCreateWithURL(url as CFURL, [kCGImageSourceShouldCache: false] as CFDictionary),
                  let identifier = CGImageSourceGetType(image),
                  [UTType.png.identifier, UTType.jpeg.identifier, UTType.tiff.identifier].contains(identifier as String) else {
                throw LocalOMRError.unsupportedSource
            }
            source = .image(image)
        }
        guard source.info.pageCount > 0 else { throw LocalOMRError.emptyDocument }
        try Task.checkCancellation()
        return try body(source)
    }

    private static func boundedSize(width: Double, height: Double, limits: LocalOMRLimits) throws -> (width: Int, height: Int) {
        guard width.isFinite, height.isFinite, width > 0, height > 0,
              (width * height).isFinite else { throw LocalOMRError.invalidDimensions }
        let scale = min(1, Double(limits.maxDimension) / max(width, height),
                        sqrt(Double(limits.maxPixelCount) / (width * height)))
        let w = max(1, Int((width * scale).rounded(.down)))
        let h = max(1, Int((height * scale).rounded(.down)))
        guard w <= limits.maxDimension, h <= limits.maxDimension,
              w <= limits.maxPixelCount / h else { throw LocalOMRError.invalidDimensions }
        return (w, h)
    }

    private static func grayscale(width: Int, height: Int, cancellationCheck: () throws -> Void,
                                  draw: (CGContext) -> Void) throws -> GrayImage {
        try cancellationCheck()
        var pixels = [UInt8](repeating: 255, count: width * height)
        try pixels.withUnsafeMutableBytes { bytes in
            guard let context = CGContext(data: bytes.baseAddress, width: width, height: height,
                                          bitsPerComponent: 8, bytesPerRow: width,
                                          space: CGColorSpaceCreateDeviceGray(),
                                          bitmapInfo: CGImageAlphaInfo.none.rawValue) else {
                throw LocalOMRError.renderingFailed
            }
            // Opaque white makes transparent scans white, not black. Color input
            // is converted to device gray by Quartz during source-over drawing.
            context.setFillColor(gray: 1, alpha: 1)
            context.fill(CGRect(x: 0, y: 0, width: width, height: height))
            context.interpolationQuality = .high
            draw(context)
        }
        try cancellationCheck()
        return try GrayImage(width: width, height: height, pixels: pixels)
    }
}
