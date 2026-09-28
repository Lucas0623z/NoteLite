// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 NoteLite contributors.

import Foundation
import XCTest
@testable import AudiverisCore

final class AudiverisCoreTests: XCTestCase {
    func testGlobalThresholdIncludesEqualityAndEndpoints() throws {
        let source = try GrayImage(width: 5, height: 1, pixels: [0, 139, 140, 141, 255])
        XCTAssertEqual(try global(source, threshold: 140).pixels, [0, 0, 0, 255, 255])
        XCTAssertEqual(try global(source, threshold: 0).pixels, [0, 255, 255, 255, 255])
        XCTAssertEqual(try global(source, threshold: 255).pixels, [0, 0, 0, 0, 0])
    }

    func testAdaptiveSmallAndUniformImages() throws {
        for (width, height) in [(1, 1), (1, 47), (53, 1), (19, 20)] {
            let levels: [(UInt8, UInt8)] = [(0, 0), (127, 255), (255, 255)]
            for (gray, binary) in levels {
                let image = try GrayImage(width: width, height: height,
                                          pixels: [UInt8](repeating: gray, count: width * height))
                let result = try AudiverisPreprocessor.preprocess(image)
                XCTAssertEqual(result.binaryImage.pixels,
                               [UInt8](repeating: binary, count: width * height))
                XCTAssertEqual(result.foregroundPixelCount, binary == 0 ? width * height : 0)
                try assertRunInvariants(result.binaryImage, table: result.horizontalRuns)
                try assertRunInvariants(result.binaryImage, table: result.verticalRuns)
            }
        }
        let equality = try GrayImage(width: 3, height: 1, pixels: [127, 127, 127])
        let configuration = PreprocessingConfiguration(method: .adaptive(meanCoefficient: 1))
        XCTAssertEqual(try AudiverisPreprocessor.binarize(equality, configuration: configuration).pixels,
                       [0, 0, 0])
    }

    func testAdaptiveRingWrapsAndClippedEdgesMatchBruteForce() throws {
        let width = 93
        let height = 43
        let pixels = (0..<(width * height)).map { UInt8(($0 * 73 + ($0 / width) * 19) % 256) }
        let image = try GrayImage(width: width, height: height, pixels: pixels)
        for radius in [0, 1, 18, 50] {
            let config = PreprocessingConfiguration(method: .adaptive(halfWindowSize: radius))
            let actual = try AudiverisPreprocessor.binarize(image, configuration: config)
            let expected = bruteForce(image, radius: radius)
            XCTAssertEqual(actual.pixels, expected, "radius=\(radius)")
        }
    }

    func testRunOrientationsAndTerminalRuns() throws {
        let binary = try BinaryImage(width: 5, height: 3, pixels: [
            0, 0, 255, 0, 0,
            255, 0, 255, 255, 0,
            0, 0, 0, 0, 0
        ])
        let horizontal = try AudiverisPreprocessor.retrieveRuns(binary, orientation: .horizontal)
        let vertical = try AudiverisPreprocessor.retrieveRuns(binary, orientation: .vertical)
        XCTAssertEqual(pairs(horizontal), [[[0, 2], [3, 2]], [[1, 1], [4, 1]], [[0, 5]]])
        XCTAssertEqual(pairs(vertical), [
            [[0, 1], [2, 1]], [[0, 3]], [[2, 1]], [[0, 1], [2, 1]], [[0, 3]]
        ])
        XCTAssertEqual(horizontal.foregroundPixelCount, 11)
        XCTAssertEqual(vertical.foregroundPixelCount, 11)
        try assertRunInvariants(binary, table: horizontal)
        try assertRunInvariants(binary, table: vertical)
    }

    func testRunCountCapIncludesBothTables() throws {
        let source = try GrayImage(width: 2, height: 2, pixels: [0, 255, 255, 0])
        let limit = ProcessingLimits(maxRunCount: 3)
        XCTAssertThrowsError(try AudiverisPreprocessor.preprocess(source,
            configuration: PreprocessingConfiguration(method: .global(threshold: 140), limits: limit))) {
            guard case PreprocessingError.runLimitExceeded = $0 else {
                return XCTFail("Unexpected error: \($0)")
            }
        }
        let exact = ProcessingLimits(maxRunCount: 4)
        let result = try AudiverisPreprocessor.preprocess(source,
            configuration: PreprocessingConfiguration(method: .global(threshold: 140), limits: exact))
        XCTAssertEqual(result.horizontalRuns.runCount + result.verticalRuns.runCount, 4)
        let white = try GrayImage(width: 1, height: 1, pixels: [255])
        XCTAssertEqual(try AudiverisPreprocessor.preprocess(white,
            configuration: PreprocessingConfiguration(limits: ProcessingLimits(maxRunCount: 0)))
            .foregroundPixelCount, 0)
    }

    func testInputValidationAndOverflowGuards() throws {
        XCTAssertThrowsError(try GrayImage(width: 0, height: 1, pixels: [])) {
            XCTAssertEqual($0 as? PreprocessingError, .invalidDimensions)
        }
        XCTAssertThrowsError(try GrayImage(width: -1, height: 1, pixels: []))
        XCTAssertThrowsError(try GrayImage(width: 2, height: 2, pixels: [0])) {
            XCTAssertEqual($0 as? PreprocessingError, .pixelCountMismatch(expected: 4, actual: 1))
        }
        XCTAssertThrowsError(try GrayImage(width: 8193, height: 1, pixels: [])) {
            XCTAssertEqual($0 as? PreprocessingError, .dimensionLimitExceeded(limit: 8192))
        }
        XCTAssertThrowsError(try GrayImage(width: 3, height: 3, pixels: [],
                                         limits: ProcessingLimits(maxPixelCount: 8))) {
            XCTAssertEqual($0 as? PreprocessingError, .pixelLimitExceeded(limit: 8))
        }
        let huge = ProcessingLimits(maxDimension: Int.max, maxPixelCount: Int.max)
        XCTAssertThrowsError(try GrayImage(width: Int.max, height: 2, pixels: [], limits: huge)) {
            XCTAssertEqual($0 as? PreprocessingError, .arithmeticOverflow)
        }
        XCTAssertThrowsError(try GrayImage(width: Int.max, height: 1, pixels: [], limits: huge)) {
            XCTAssertEqual($0 as? PreprocessingError, .arithmeticOverflow)
        }
        XCTAssertThrowsError(try BinaryImage(width: 1, height: 1, pixels: [42])) {
            XCTAssertEqual($0 as? PreprocessingError, .nonBinaryPixel(index: 0, value: 42))
        }
    }

    func testInvalidFilterConfigurationIsRejected() throws {
        let source = try GrayImage(width: 1, height: 1, pixels: [50])
        let invalid: [BinarizationMethod] = [
            .global(threshold: -1), .global(threshold: 256),
            .adaptive(meanCoefficient: .nan), .adaptive(standardDeviationCoefficient: .infinity),
            .adaptive(meanCoefficient: -0.1), .adaptive(standardDeviationCoefficient: 1.6),
            .adaptive(halfWindowSize: -1)
        ]
        for method in invalid {
            XCTAssertThrowsError(try AudiverisPreprocessor.binarize(source,
                configuration: PreprocessingConfiguration(method: method))) {
                XCTAssertEqual($0 as? PreprocessingError, .invalidConfiguration)
            }
        }
        XCTAssertThrowsError(try AudiverisPreprocessor.binarize(source,
            configuration: PreprocessingConfiguration(method: .adaptive(halfWindowSize: Int.max)))) {
            XCTAssertEqual($0 as? PreprocessingError, .arithmeticOverflow)
        }
    }

    func testIntegralStorageDependsOnHeightAndRadiusNotImageWidth() throws {
        let height = 17
        let required = 38 * height * 2 * MemoryLayout<Int64>.stride
        for width in [40, 400] {
            let image = try GrayImage(width: width, height: height,
                                      pixels: [UInt8](repeating: 200, count: width * height))
            let tight = PreprocessingConfiguration(limits: ProcessingLimits(maxIntegralBytes: required - 1))
            XCTAssertThrowsError(try AudiverisPreprocessor.binarize(image, configuration: tight)) {
                XCTAssertEqual($0 as? PreprocessingError,
                               .integralMemoryLimitExceeded(requiredBytes: required, limit: required - 1))
            }
            let exact = PreprocessingConfiguration(limits: ProcessingLimits(maxIntegralBytes: required))
            XCTAssertEqual(try AudiverisPreprocessor.binarize(image, configuration: exact).pixels,
                           [UInt8](repeating: 255, count: width * height))
        }
    }

    func testCooperativeCancellationDuringFilteringAndRuns() throws {
        let source = try GrayImage(width: 80, height: 80, pixels: [UInt8](repeating: 0, count: 6400))
        var checks = 0
        XCTAssertThrowsError(try AudiverisPreprocessor.binarize(source, cancellationCheck: {
            checks += 1
            if checks == 12 { throw CancellationError() }
        })) { XCTAssertTrue($0 is CancellationError) }
        XCTAssertEqual(checks, 12)
        let binary = try BinaryImage(width: 80, height: 80, pixels: source.pixels)
        checks = 0
        XCTAssertThrowsError(try AudiverisPreprocessor.retrieveRuns(binary, orientation: .vertical,
            cancellationCheck: {
                checks += 1
                if checks == 12 { throw CancellationError() }
            })) { XCTAssertTrue($0 is CancellationError) }
        XCTAssertEqual(checks, 12)
        XCTAssertThrowsError(try AudiverisPreprocessor.binarize(source,
            configuration: PreprocessingConfiguration(method: .global(threshold: 140)),
            cancellationCheck: { throw CancellationError() })) { XCTAssertTrue($0 is CancellationError) }
    }

    func testDefaultCancellationObservesSwiftTask() async throws {
        let source = try GrayImage(width: 1, height: 1, pixels: [0])
        let task = Task<BinaryImage, Error> {
            while !Task.isCancelled { await Task.yield() }
            return try AudiverisPreprocessor.binarize(source)
        }
        task.cancel()
        do {
            _ = try await task.value
            XCTFail("Expected cancelled task to stop before allocation")
        } catch {
            XCTAssertTrue(error is CancellationError)
        }
    }

    func testCommittedOriginalJavaOracleFixtures() throws {
        let directory = try XCTUnwrap(Bundle.module.url(forResource: "Fixtures", withExtension: nil))
        let files = try FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)
            .filter { $0.pathExtension == "json" && $0.lastPathComponent != "manifest.json" }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }
        XCTAssertEqual(files.count, 19, "All original Java oracle cases must be committed")
        for file in files {
            let fixture = try JSONDecoder().decode(JavaOracle.self, from: Data(contentsOf: file))
            let bytes = try XCTUnwrap(Data(base64Encoded: fixture.grayBase64), fixture.name)
            let expected = try XCTUnwrap(Data(base64Encoded: fixture.binaryBase64), fixture.name)
            let image = try GrayImage(width: fixture.width, height: fixture.height, pixels: Array(bytes))
            let method: BinarizationMethod
            switch fixture.mode {
            case "global": method = .global(threshold: fixture.threshold)
            case "adaptive":
                method = .adaptive(meanCoefficient: fixture.meanCoefficient,
                                   standardDeviationCoefficient: fixture.standardDeviationCoefficient,
                                   halfWindowSize: fixture.halfWindowSize)
            default: XCTFail("Unknown fixture mode: \(fixture.mode)"); continue
            }
            let result = try AudiverisPreprocessor.preprocess(image,
                configuration: PreprocessingConfiguration(method: method))
            XCTAssertEqual(result.binaryImage.pixels, Array(expected), fixture.name)
            XCTAssertEqual(pairs(result.horizontalRuns), fixture.horizontalRuns, fixture.name)
            XCTAssertEqual(pairs(result.verticalRuns), fixture.verticalRuns, fixture.name)
            try assertRunInvariants(result.binaryImage, table: result.horizontalRuns)
            try assertRunInvariants(result.binaryImage, table: result.verticalRuns)
        }
    }

    private func global(_ image: GrayImage, threshold: Int) throws -> BinaryImage {
        try AudiverisPreprocessor.binarize(image,
            configuration: PreprocessingConfiguration(method: .global(threshold: threshold)))
    }

    private func pairs(_ table: RunTable) -> [[[Int]]] {
        table.sequences.map { $0.map { [$0.start, $0.length] } }
    }

    private func assertRunInvariants(_ image: BinaryImage, table: RunTable) throws {
        let horizontal = table.orientation == .horizontal
        XCTAssertEqual(table.sequences.count, horizontal ? image.height : image.width)
        var reconstructed = [UInt8](repeating: 255, count: image.pixels.count)
        var runCount = 0
        var area = 0
        for (position, sequence) in table.sequences.enumerated() {
            var previousEnd = -1
            for run in sequence {
                XCTAssertGreaterThan(run.start, previousEnd, "Runs must have at least one background gap")
                XCTAssertGreaterThan(run.length, 0)
                XCTAssertLessThanOrEqual(run.endExclusive, horizontal ? image.width : image.height)
                for coordinate in run.start..<run.endExclusive {
                    let index = horizontal ? position * image.width + coordinate : coordinate * image.width + position
                    reconstructed[index] = 0
                }
                previousEnd = run.endExclusive
                runCount += 1
                area += run.length
            }
        }
        XCTAssertEqual(reconstructed, image.pixels)
        XCTAssertEqual(runCount, table.runCount)
        XCTAssertEqual(area, table.foregroundPixelCount)
    }

    private func bruteForce(_ image: GrayImage, radius: Int) -> [UInt8] {
        var result = [UInt8](repeating: 255, count: image.pixels.count)
        for y in 0..<image.height {
            for x in 0..<image.width {
                var sum = 0
                var squareSum = 0
                var count = 0
                for iy in max(0, y - radius)...min(image.height - 1, y + radius) {
                    for ix in max(0, x - radius)...min(image.width - 1, x + radius) {
                        let value = Int(image.pixels[iy * image.width + ix])
                        sum += value
                        squareSum += value * value
                        count += 1
                    }
                }
                let mean = Double(sum) / Double(count)
                let variance = abs(Double(squareSum) / Double(count) - mean * mean)
                let threshold = 0.7 * mean + 0.9 * variance.squareRoot()
                if Double(image.pixels[y * image.width + x]) <= threshold { result[y * image.width + x] = 0 }
            }
        }
        return result
    }
}

private struct JavaOracle: Decodable {
    let name: String
    let width: Int
    let height: Int
    let mode: String
    let halfWindowSize: Int
    let meanCoefficient: Double
    let standardDeviationCoefficient: Double
    let threshold: Int
    let grayBase64: String
    let binaryBase64: String
    let horizontalRuns: [[[Int]]]
    let verticalRuns: [[[Int]]]
}
