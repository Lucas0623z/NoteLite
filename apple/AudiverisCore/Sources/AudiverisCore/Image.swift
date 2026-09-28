// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 NoteLite contributors.

/// Resource limits checked before buffers are allocated or runs are appended.
/// `maxRunCount` applies to both orientations combined in `preprocess`, or to the
/// single table when calling `retrieveRuns` directly.
public struct ProcessingLimits: Equatable, Sendable {
    public let maxDimension: Int
    public let maxPixelCount: Int
    public let maxIntegralBytes: Int
    public let maxRunCount: Int

    public init(
        maxDimension: Int = 8192,
        maxPixelCount: Int = 16_000_000,
        maxIntegralBytes: Int = 32 * 1024 * 1024,
        maxRunCount: Int = 2_000_000
    ) {
        self.maxDimension = maxDimension
        self.maxPixelCount = maxPixelCount
        self.maxIntegralBytes = maxIntegralBytes
        self.maxRunCount = maxRunCount
    }

    public static let `default` = ProcessingLimits()

    func validate() throws {
        guard maxDimension > 0, maxPixelCount > 0,
              maxIntegralBytes >= 0, maxRunCount >= 0 else {
            throw PreprocessingError.invalidConfiguration
        }
    }

    func validateDimensions(width: Int, height: Int) throws -> Int {
        try validate()
        guard width > 0, height > 0 else { throw PreprocessingError.invalidDimensions }
        let (count, overflow) = width.multipliedReportingOverflow(by: height)
        guard !overflow else { throw PreprocessingError.arithmeticOverflow }
        guard width <= maxDimension, height <= maxDimension else {
            throw PreprocessingError.dimensionLimitExceeded(limit: maxDimension)
        }
        guard count <= maxPixelCount else {
            throw PreprocessingError.pixelLimitExceeded(limit: maxPixelCount)
        }
        // Both (a + d) and (pixel + left + top) must fit in signed Java long / Int64.
        guard UInt64(count) <= UInt64(Int64.max / (2 * 255 * 255)) else {
            throw PreprocessingError.arithmeticOverflow
        }
        return count
    }
}

public enum PreprocessingError: Error, Equatable, Sendable {
    case invalidDimensions
    case pixelCountMismatch(expected: Int, actual: Int)
    case nonBinaryPixel(index: Int, value: UInt8)
    case invalidConfiguration
    case arithmeticOverflow
    case dimensionLimitExceeded(limit: Int)
    case pixelLimitExceeded(limit: Int)
    case integralMemoryLimitExceeded(requiredBytes: Int, limit: Int)
    case runLimitExceeded(limit: Int)
}

/// Immutable, row-major 8-bit luminance. Zero is black; 255 is white.
public struct GrayImage: Equatable, Sendable {
    public let width: Int
    public let height: Int
    public let pixels: [UInt8]

    public init(
        width: Int,
        height: Int,
        pixels: [UInt8],
        limits: ProcessingLimits = .default
    ) throws {
        let count = try limits.validateDimensions(width: width, height: height)
        guard pixels.count == count else {
            throw PreprocessingError.pixelCountMismatch(expected: count, actual: pixels.count)
        }
        self.width = width
        self.height = height
        self.pixels = pixels
    }
}

/// Immutable, row-major Audiveris binary pixels: foreground=0, background=255.
public struct BinaryImage: Equatable, Sendable {
    public let width: Int
    public let height: Int
    public let pixels: [UInt8]

    public init(
        width: Int,
        height: Int,
        pixels: [UInt8],
        limits: ProcessingLimits = .default,
        cancellationCheck: () throws -> Void = { try Task.checkCancellation() }
    ) throws {
        try cancellationCheck()
        let count = try limits.validateDimensions(width: width, height: height)
        guard pixels.count == count else {
            throw PreprocessingError.pixelCountMismatch(expected: count, actual: pixels.count)
        }
        for (index, pixel) in pixels.enumerated() {
            if index & 4095 == 0 { try cancellationCheck() }
            guard pixel == 0 || pixel == 255 else {
                throw PreprocessingError.nonBinaryPixel(index: index, value: pixel)
            }
        }
        self.init(validatedWidth: width, height: height, pixels: pixels)
    }

    // All producers in the module already validate dimensions and write only 0/255.
    init(validatedWidth width: Int, height: Int, pixels: [UInt8]) {
        self.width = width
        self.height = height
        self.pixels = pixels
    }
}
