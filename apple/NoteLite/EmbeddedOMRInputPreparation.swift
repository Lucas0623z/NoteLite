import CoreGraphics
import Foundation
import ImageIO
import PDFKit
import UniformTypeIdentifiers

struct EmbeddedOMRInputLimits: Sendable {
    var maxFileBytes = 50 * 1024 * 1024
    var maxPreparedFileBytes = 128 * 1024 * 1024
    var maxPageCount = 64
    var maxSourcePixelsPerPage = 100_000_000
    var maxDimension = 8_192
    var maxPixelsPerPage = 16_000_000
    var maxTotalImagePixels = 64_000_000
    static let `default` = EmbeddedOMRInputLimits()
}

struct EmbeddedOMRPreparedInput: Sendable {
    let url: URL
    let pageCount: Int
    let normalized: Bool
    let downsampled: Bool
    let preservedOriginalBytes: Bool
}

enum EmbeddedOMRInputError: LocalizedError, Equatable {
    case invalidLimits, invalidFile, unsupportedFormat, lockedPDF, invalidImage
    case fileTooLarge, tooManyPages, imageTooLarge, preparedFileTooLarge, encodingFailed

    var errorDescription: String? {
        switch self {
        case .invalidLimits: return "本地识谱的输入限制无效。"
        case .invalidFile: return "无法读取这份本地乐谱。"
        case .unsupportedFormat: return "本地识谱支持 PDF、PNG、JPEG 和 TIFF。"
        case .lockedPDF: return "请先解锁 PDF，再开始本地识谱。"
        case .invalidImage: return "图片损坏，或包含无效的尺寸、方向信息。"
        case .fileTooLarge: return "原稿超过本地识谱的文件大小限制。"
        case .tooManyPages: return "原稿页数超过本地识谱的限制，请拆分后导入。"
        case .imageTooLarge: return "图片像素总量超过本地识谱的限制，请缩小或拆分后导入。"
        case .preparedFileTooLarge: return "校正后的图片超过本地识谱的文件大小限制。"
        case .encodingFailed: return "无法生成完整的本地识谱输入文件。"
        }
    }
}

/// Call on the engine worker, never on the UI actor. This stages a complete
/// document; unlike the debug preprocessing harness, it has no selected-page API.
enum EmbeddedOMRInputPreparer {
    static func prepare(source: URL, in directory: URL, limits: EmbeddedOMRInputLimits = .default,
                        cancellationCheck: () throws -> Void = { try Task.checkCancellation() }) throws -> EmbeddedOMRPreparedInput {
        guard limits.maxFileBytes > 0, limits.maxPreparedFileBytes > 0, limits.maxPageCount > 0,
              limits.maxSourcePixelsPerPage > 0, limits.maxDimension > 0, limits.maxDimension <= 32_768,
              limits.maxPixelsPerPage > 0, limits.maxPixelsPerPage <= 64_000_000,
              limits.maxTotalImagePixels > 0 else { throw EmbeddedOMRInputError.invalidLimits }
        try cancellationCheck()
        guard source.isFileURL, directory.isFileURL else { throw EmbeddedOMRInputError.invalidFile }
        let scoped = source.startAccessingSecurityScopedResource()
        defer { if scoped { source.stopAccessingSecurityScopedResource() } }
        let attributes = try source.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey])
        guard attributes.isRegularFile == true, let bytes = attributes.fileSize, bytes > 0 else {
            throw EmbeddedOMRInputError.invalidFile
        }
        guard bytes <= limits.maxFileBytes else { throw EmbeddedOMRInputError.fileTooLarge }
        let handle = try FileHandle(forReadingFrom: source)
        let header: Data
        do { header = try handle.read(upToCount: 1_024) ?? Data(); try handle.close() }
        catch { try? handle.close(); throw error }
        if header.range(of: Data("%PDF-".utf8)) != nil, let pdf = PDFDocument(url: source) {
            guard !pdf.isLocked else { throw EmbeddedOMRInputError.lockedPDF }
            guard pdf.pageCount > 0 else { throw EmbeddedOMRInputError.invalidFile }
            guard pdf.pageCount <= limits.maxPageCount else { throw EmbeddedOMRInputError.tooManyPages }
            try preflightPDF(pdf, limits: limits, cancellationCheck: cancellationCheck)
            // PDFBox receives all pages, vector content, crops and rotations unchanged.
            let url = try stage(in: directory, fileExtension: "pdf", limits: limits, cancellationCheck: cancellationCheck) { temporary in
                try FileManager.default.copyItem(at: source, to: temporary)
            }
            return EmbeddedOMRPreparedInput(url: url, pageCount: pdf.pageCount, normalized: false,
                                             downsampled: false, preservedOriginalBytes: true)
        }
        guard let images = CGImageSourceCreateWithURL(source as CFURL, [kCGImageSourceShouldCache: false] as CFDictionary),
              let identifier = CGImageSourceGetType(images) else { throw EmbeddedOMRInputError.unsupportedFormat }
        let sourceExtension: String
        switch identifier as String {
        case UTType.png.identifier: sourceExtension = "png"
        case UTType.jpeg.identifier: sourceExtension = "jpg"
        case UTType.tiff.identifier: sourceExtension = "tiff"
        default: throw EmbeddedOMRInputError.unsupportedFormat
        }
        let count = CGImageSourceGetCount(images)
        guard count > 0 else { throw EmbeddedOMRInputError.invalidImage }
        guard count <= limits.maxPageCount else { throw EmbeddedOMRInputError.tooManyPages }
        // Animated PNG and multi-picture JPEG must not be silently flattened.
        guard count == 1 || sourceExtension == "tiff" else { throw EmbeddedOMRInputError.unsupportedFormat }
        var plans = [PagePlan]()
        var totalPixels = 0
        for index in 0..<count {
            try cancellationCheck()
            let plan = try autoreleasepool {
                try planPage(source: images, index: index, limits: limits, cancellationCheck: cancellationCheck)
            }
            guard plan.width <= (limits.maxTotalImagePixels - totalPixels) / plan.height else {
                throw EmbeddedOMRInputError.imageTooLarge
            }
            totalPixels += plan.width * plan.height
            plans.append(plan)
        }
        let changed = plans.contains { $0.orientation != 1 || $0.downsampled || $0.transparent }
        if !changed {
            let url = try stage(in: directory, fileExtension: sourceExtension, limits: limits, cancellationCheck: cancellationCheck) { temporary in
                try FileManager.default.copyItem(at: source, to: temporary)
            }
            return EmbeddedOMRPreparedInput(url: url, pageCount: count, normalized: false,
                                             downsampled: false, preservedOriginalBytes: true)
        }
        let outputType = sourceExtension == "tiff" ? UTType.tiff : UTType.png
        let url = try stage(in: directory, fileExtension: outputType == .tiff ? "tiff" : "png",
                            limits: limits, cancellationCheck: cancellationCheck) { temporary in
            guard let destination = CGImageDestinationCreateWithURL(temporary as CFURL, outputType.identifier as CFString, count, nil) else {
                throw EmbeddedOMRInputError.encodingFailed
            }
            for (index, plan) in plans.enumerated() {
                try cancellationCheck()
                try autoreleasepool {
                    let image = try normalizedImage(source: images, index: index, plan: plan, cancellationCheck: cancellationCheck)
                    var properties: [CFString: Any] = [kCGImagePropertyOrientation: 1]
                    if let dpiX = plan.dpiX { properties[kCGImagePropertyDPIWidth] = dpiX }
                    if let dpiY = plan.dpiY { properties[kCGImagePropertyDPIHeight] = dpiY }
                    if outputType == .tiff {
                        // TIFF LZW is lossless; every page is appended in original order.
                        properties[kCGImagePropertyTIFFDictionary] = [kCGImagePropertyTIFFCompression: 5,
                                                                     kCGImagePropertyTIFFOrientation: 1]
                    }
                    CGImageDestinationAddImage(destination, image, properties as CFDictionary)
                }
            }
            try cancellationCheck()
            guard CGImageDestinationFinalize(destination),
                  let check = CGImageSourceCreateWithURL(temporary as CFURL, nil),
                  CGImageSourceGetCount(check) == count else { throw EmbeddedOMRInputError.encodingFailed }
        }
        return EmbeddedOMRPreparedInput(url: url, pageCount: count, normalized: true,
                                         downsampled: plans.contains { $0.downsampled }, preservedOriginalBytes: false)
    }

    private struct PagePlan {
        let orientation: Int
        let width: Int
        let height: Int
        let downsampled: Bool
        let transparent: Bool
        let dpiX: Double?
        let dpiY: Double?
    }

    private static func preflightPDF(_ document: PDFDocument, limits: EmbeddedOMRInputLimits,
                                     cancellationCheck: () throws -> Void) throws {
        // ImageLoading.pdfResolution defaults to 300 DPI. The embedded engine
        // does not expose a resolution override: keep this in sync if it gains one.
        // PDFBox 3.0.6 PDFRenderer uses Float arithmetic, floors each dimension,
        // and swaps the raster dimensions for 90/270-degree page rotation.
        let scale: Float = 300 / 72
        var totalPixels = 0
        for index in 0..<document.pageCount {
            try cancellationCheck()
            guard let page = document.page(at: index)?.pageRef else { throw EmbeddedOMRInputError.invalidFile }
            let media = page.getBoxRect(.mediaBox)
            let crop = page.getBoxRect(.cropBox)
            guard [media.minX, media.minY, media.maxX, media.maxY,
                   crop.minX, crop.minY, crop.maxX, crop.maxY].allSatisfy({ $0.isFinite }) else {
                throw EmbeddedOMRInputError.imageTooLarge
            }
            // PDPage.getCropBox clips its inherited crop to the media box.
            let effectiveCrop = crop.intersection(media)
            guard !effectiveCrop.isNull, !effectiveCrop.isEmpty else { throw EmbeddedOMRInputError.invalidFile }
            let width = max(1, (Float(effectiveCrop.width) * scale).rounded(.down))
            let height = max(1, (Float(effectiveCrop.height) * scale).rounded(.down))
            guard width.isFinite, height.isFinite,
                  width <= Float(limits.maxDimension), height <= Float(limits.maxDimension) else {
                throw EmbeddedOMRInputError.imageTooLarge
            }
            let rotation = (page.rotationAngle % 360 + 360) % 360
            let pixelWidth = Int(rotation == 90 || rotation == 270 ? height : width)
            let pixelHeight = Int(rotation == 90 || rotation == 270 ? width : height)
            guard pixelWidth <= limits.maxPixelsPerPage / pixelHeight,
                  pixelWidth <= (limits.maxTotalImagePixels - totalPixels) / pixelHeight else {
                throw EmbeddedOMRInputError.imageTooLarge
            }
            totalPixels += pixelWidth * pixelHeight
        }
    }

    private static func planPage(source: CGImageSource, index: Int, limits: EmbeddedOMRInputLimits,
                                 cancellationCheck: () throws -> Void) throws -> PagePlan {
        guard let properties = CGImageSourceCopyPropertiesAtIndex(source, index, nil) as? [CFString: Any],
              let w = properties[kCGImagePropertyPixelWidth] as? NSNumber,
              let h = properties[kCGImagePropertyPixelHeight] as? NSNumber,
              w.doubleValue.isFinite, h.doubleValue.isFinite,
              w.doubleValue >= 1, h.doubleValue >= 1,
              w.doubleValue <= Double(limits.maxSourcePixelsPerPage),
              h.doubleValue <= Double(limits.maxSourcePixelsPerPage) else { throw EmbeddedOMRInputError.invalidImage }
        let width = w.intValue, height = h.intValue
        guard width > 0, height > 0 else { throw EmbeddedOMRInputError.invalidImage }
        guard width <= limits.maxSourcePixelsPerPage / height else { throw EmbeddedOMRInputError.imageTooLarge }
        let orientation = (properties[kCGImagePropertyOrientation] as? NSNumber)?.intValue ?? 1
        guard (1...8).contains(orientation) else { throw EmbeddedOMRInputError.invalidImage }
        let orientedWidth = orientation >= 5 ? height : width
        let orientedHeight = orientation >= 5 ? width : height
        let scale = min(1, Double(limits.maxDimension) / Double(max(width, height)),
                        sqrt(Double(limits.maxPixelsPerPage) / (Double(width) * Double(height))))
        let outputWidth = max(1, Int((Double(orientedWidth) * scale).rounded(.down)))
        let outputHeight = max(1, Int((Double(orientedHeight) * scale).rounded(.down)))
        guard outputWidth <= limits.maxPixelsPerPage / outputHeight else { throw EmbeddedOMRInputError.imageTooLarge }
        let downsampled = outputWidth != orientedWidth || outputHeight != orientedHeight
        var transparent = false
        if (properties[kCGImagePropertyHasAlpha] as? NSNumber)?.boolValue == true {
            if orientation != 1 || downsampled {
                transparent = true // Already re-encoding; flatten any alpha onto white.
            } else {
                guard let image = CGImageSourceCreateImageAtIndex(source, index, nil) else { throw EmbeddedOMRInputError.invalidImage }
                // Opaque RGBA PNGs keep their exact original bytes. Only actual
                // transparency requires repair because Audiveris discards alpha.
                transparent = try hasTransparency(image, cancellationCheck: cancellationCheck)
            }
        }
        func dpi(_ key: CFString, output: Int, original: Int) -> Double? {
            guard let value = properties[key] as? NSNumber, value.doubleValue.isFinite, value.doubleValue > 0 else { return nil }
            return value.doubleValue * Double(output) / Double(original)
        }
        return PagePlan(orientation: orientation, width: outputWidth, height: outputHeight,
                        downsampled: downsampled, transparent: transparent,
                        dpiX: dpi(orientation >= 5 ? kCGImagePropertyDPIHeight : kCGImagePropertyDPIWidth,
                                  output: outputWidth, original: orientedWidth),
                        dpiY: dpi(orientation >= 5 ? kCGImagePropertyDPIWidth : kCGImagePropertyDPIHeight,
                                  output: outputHeight, original: orientedHeight))
    }

    private static func normalizedImage(source: CGImageSource, index: Int, plan: PagePlan,
                                        cancellationCheck: () throws -> Void) throws -> CGImage {
        try cancellationCheck()
        let decoded: CGImage?
        if plan.orientation != 1 || plan.downsampled {
            decoded = CGImageSourceCreateThumbnailAtIndex(source, index, [
                kCGImageSourceCreateThumbnailFromImageAlways: true,
                kCGImageSourceCreateThumbnailWithTransform: true,
                kCGImageSourceThumbnailMaxPixelSize: max(plan.width, plan.height),
                kCGImageSourceShouldCacheImmediately: true
            ] as CFDictionary)
        } else { decoded = CGImageSourceCreateImageAtIndex(source, index, nil) }
        guard let image = decoded else { throw EmbeddedOMRInputError.invalidImage }
        if !plan.transparent, image.width == plan.width, image.height == plan.height { return image }
        // Also handles the decoder rounding the shorter thumbnail edge up by one.
        guard let context = CGContext(data: nil, width: plan.width, height: plan.height,
                                      bitsPerComponent: 8, bytesPerRow: plan.width * 4,
                                      space: CGColorSpaceCreateDeviceRGB(),
                                      bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else {
            throw EmbeddedOMRInputError.encodingFailed
        }
        context.setFillColor(gray: 1, alpha: 1)
        context.fill(CGRect(x: 0, y: 0, width: plan.width, height: plan.height))
        context.interpolationQuality = .high
        context.draw(image, in: CGRect(x: 0, y: 0, width: plan.width, height: plan.height))
        try cancellationCheck()
        guard let output = context.makeImage() else { throw EmbeddedOMRInputError.encodingFailed }
        return output
    }

    private static func hasTransparency(_ image: CGImage, cancellationCheck: () throws -> Void) throws -> Bool {
        let count = image.width * image.height
        var rgba = [UInt8](repeating: 0, count: count * 4)
        return try rgba.withUnsafeMutableBytes { bytes in
            guard let context = CGContext(data: bytes.baseAddress, width: image.width, height: image.height,
                                          bitsPerComponent: 8, bytesPerRow: image.width * 4,
                                          space: CGColorSpaceCreateDeviceRGB(),
                                          bitmapInfo: CGBitmapInfo.byteOrder32Big.rawValue | CGImageAlphaInfo.premultipliedLast.rawValue) else {
                throw EmbeddedOMRInputError.encodingFailed
            }
            context.setBlendMode(.copy)
            context.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))
            for index in 0..<count {
                if index & 4095 == 0 { try cancellationCheck() }
                if bytes[index * 4 + 3] != 255 { return true }
            }
            return false
        }
    }

    private static func stage(in directory: URL, fileExtension suffix: String, limits: EmbeddedOMRInputLimits,
                              cancellationCheck: () throws -> Void, write: (URL) throws -> Void) throws -> URL {
        let files = FileManager.default
        try files.createDirectory(at: directory, withIntermediateDirectories: true)
        let token = UUID().uuidString
        // ImageIO can create private sibling files before finalizing TIFF output.
        // Own an entire temporary directory so cancellation also removes those.
        let staging = directory.appendingPathComponent(".preparing-\(token)", isDirectory: true)
        try files.createDirectory(at: staging, withIntermediateDirectories: false)
        let temporary = staging.appendingPathComponent("source.\(suffix)")
        let output = directory.appendingPathComponent("source-\(token).\(suffix)")
        defer { try? files.removeItem(at: staging) }
        try cancellationCheck()
        try write(temporary)
        try cancellationCheck()
        let size = try temporary.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        guard size > 0 else { throw EmbeddedOMRInputError.encodingFailed }
        guard size <= limits.maxPreparedFileBytes else { throw EmbeddedOMRInputError.preparedFileTooLarge }
        try files.moveItem(at: temporary, to: output)
        return output
    }
}
