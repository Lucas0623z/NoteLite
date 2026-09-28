// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) Audiveris 2026; NoteLite contributors 2026.
// Swift adaptation of AdaptiveFilter, VerticalFilter and GlobalFilter.
// Original authors: ryo/twitter @xiaot_Tag and Hervé Bitteur.
// This program comes WITHOUT ANY WARRANTY. See LICENSE and NOTICE.md.

public enum BinarizationMethod: Equatable, Sendable {
    case global(threshold: Int)
    case adaptive(
        meanCoefficient: Double = 0.7,
        standardDeviationCoefficient: Double = 0.9,
        halfWindowSize: Int = 18
    )
}

public struct PreprocessingConfiguration: Equatable, Sendable {
    public let method: BinarizationMethod
    public let limits: ProcessingLimits

    public init(method: BinarizationMethod = .adaptive(), limits: ProcessingLimits = .default) {
        self.method = method
        self.limits = limits
    }

    public static let `default` = PreprocessingConfiguration()
}

public struct PreprocessingResult: Equatable, Sendable {
    public let binaryImage: BinaryImage
    public let horizontalRuns: RunTable
    public let verticalRuns: RunTable

    public var foregroundPixelCount: Int { horizontalRuns.foregroundPixelCount }
}

/// The first native Audiveris stages: binarization and foreground run extraction.
/// This does not recognize musical symbols or produce a score.
public enum AudiverisPreprocessor {
    public static func preprocess(
        _ image: GrayImage,
        configuration: PreprocessingConfiguration = .default,
        cancellationCheck: () throws -> Void = { try Task.checkCancellation() }
    ) throws -> PreprocessingResult {
        let binary = try binarize(image, configuration: configuration, cancellationCheck: cancellationCheck)
        let horizontal = try retrieveRuns(
            binary, orientation: .horizontal,
            limits: configuration.limits, cancellationCheck: cancellationCheck
        )
        let limits = configuration.limits
        let remainingLimits = ProcessingLimits(
            maxDimension: limits.maxDimension, maxPixelCount: limits.maxPixelCount,
            maxIntegralBytes: limits.maxIntegralBytes,
            maxRunCount: limits.maxRunCount - horizontal.runCount
        )
        let vertical: RunTable
        do {
            vertical = try retrieveRuns(
                binary, orientation: .vertical,
                limits: remainingLimits, cancellationCheck: cancellationCheck
            )
        } catch PreprocessingError.runLimitExceeded {
            throw PreprocessingError.runLimitExceeded(limit: limits.maxRunCount)
        }
        try cancellationCheck()
        return PreprocessingResult(binaryImage: binary, horizontalRuns: horizontal, verticalRuns: vertical)
    }

    public static func binarize(
        _ image: GrayImage,
        configuration: PreprocessingConfiguration = .default,
        cancellationCheck: () throws -> Void = { try Task.checkCancellation() }
    ) throws -> BinaryImage {
        try cancellationCheck()
        let count = try configuration.limits.validateDimensions(width: image.width, height: image.height)
        switch configuration.method {
        case .global(let threshold):
            guard (0...255).contains(threshold) else { throw PreprocessingError.invalidConfiguration }
            var pixels = [UInt8](repeating: 255, count: count)
            for index in 0..<count {
                if index & 4095 == 0 { try cancellationCheck() }
                // Audiveris includes pixels exactly equal to the threshold.
                if Int(image.pixels[index]) <= threshold { pixels[index] = 0 }
            }
            try cancellationCheck()
            return BinaryImage(validatedWidth: image.width, height: image.height, pixels: pixels)

        case .adaptive(let meanCoefficient, let standardDeviationCoefficient, let radius):
            guard meanCoefficient.isFinite, standardDeviationCoefficient.isFinite,
                  (0...1.5).contains(meanCoefficient),
                  (0...1.5).contains(standardDeviationCoefficient), radius >= 0 else {
                throw PreprocessingError.invalidConfiguration
            }
            let (twiceRadius, overflow1) = radius.multipliedReportingOverflow(by: 2)
            let (tileWidth, overflow2) = twiceRadius.addingReportingOverflow(2)
            guard !overflow1, !overflow2 else { throw PreprocessingError.arithmeticOverflow }
            let (entries, overflow3) = tileWidth.multipliedReportingOverflow(by: image.height)
            let (bytes, overflow4) = entries.multipliedReportingOverflow(by: 2 * MemoryLayout<Int64>.stride)
            guard !overflow3, !overflow4 else { throw PreprocessingError.arithmeticOverflow }
            guard bytes <= configuration.limits.maxIntegralBytes else {
                throw PreprocessingError.integralMemoryLimitExceeded(
                    requiredBytes: bytes, limit: configuration.limits.maxIntegralBytes
                )
            }
            // No width*height integral tables: exactly 2*(2+2*radius)*height Int64 values.
            var tile = IntegralTile(width: tileWidth, height: image.height, entryCount: entries)
            var pixels = [UInt8](repeating: 255, count: count)
            for x in 0..<image.width {
                try cancellationCheck()
                // Avoid x+radius overflowing even when a caller sets unusually large limits.
                let x2 = x + min(radius, image.width - 1 - x)
                try tile.shift(to: x2, image: image, cancellationCheck: cancellationCheck)
                let x1 = x - min(radius, x) - 1
                for y in 0..<image.height {
                    if y & 4095 == 0 { try cancellationCheck() }
                    let y1 = y - min(radius, y) - 1
                    let y2 = y + min(radius, image.height - 1 - y)
                    let area = (x2 - x1) * (y2 - y1)
                    let moments = tile.means(x1: x1, x2: x2, y1: y1, y2: y2, area: area)
                    // Keep the Java abs semantics (not max(0, variance)) and operation order.
                    let variance = abs(moments.squared - (moments.plain * moments.plain))
                    let threshold = (meanCoefficient * moments.plain)
                        + (standardDeviationCoefficient * variance.squareRoot())
                    let index = y * image.width + x
                    if Double(image.pixels[index]) <= threshold { pixels[index] = 0 }
                }
            }
            try cancellationCheck()
            return BinaryImage(validatedWidth: image.width, height: image.height, pixels: pixels)
        }
    }
}

/// Audiveris VerticalFilter's two forward-only circular integral tiles.
private struct IntegralTile {
    let width: Int
    let height: Int
    var right = -1
    var plain: [Int64]
    var squared: [Int64]

    init(width: Int, height: Int, entryCount: Int) {
        self.width = width
        self.height = height
        self.plain = [Int64](repeating: 0, count: entryCount)
        self.squared = [Int64](repeating: 0, count: entryCount)
    }

    mutating func shift(
        to x2: Int, image: GrayImage, cancellationCheck: () throws -> Void
    ) throws {
        while right < x2 {
            try cancellationCheck()
            right += 1
            let current = (right % width) * height
            let previous = (right == 0 ? width - 1 : (right - 1) % width) * height
            var top: Int64 = 0
            var topLeft: Int64 = 0
            var squareTop: Int64 = 0
            var squareTopLeft: Int64 = 0
            for y in 0..<height {
                if y & 4095 == 0 { try cancellationCheck() }
                let pixel = Int64(image.pixels[y * image.width + right])
                let left = plain[previous + y]
                let squareLeft = squared[previous + y]
                let value = (pixel + left + top) - topLeft
                let squareValue = (pixel * pixel + squareLeft + squareTop) - squareTopLeft
                plain[current + y] = value
                squared[current + y] = squareValue
                top = value
                topLeft = left
                squareTop = squareValue
                squareTopLeft = squareLeft
            }
        }
    }

    func means(x1: Int, x2: Int, y1: Int, y2: Int, area: Int) -> (plain: Double, squared: Double) {
        let right = (x2 % width) * height
        let left = x1 >= 0 ? (x1 % width) * height : 0
        let a = x1 >= 0 && y1 >= 0 ? plain[left + y1] : 0
        let b = y1 >= 0 ? plain[right + y1] : 0
        let c = x1 >= 0 ? plain[left + y2] : 0
        let d = plain[right + y2]
        let sa = x1 >= 0 && y1 >= 0 ? squared[left + y1] : 0
        let sb = y1 >= 0 ? squared[right + y1] : 0
        let sc = x1 >= 0 ? squared[left + y2] : 0
        let sd = squared[right + y2]
        return (Double((a + d) - b - c) / Double(area),
                Double((sa + sd) - sb - sc) / Double(area))
    }
}
