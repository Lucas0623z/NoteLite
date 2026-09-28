// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) Audiveris 2026; NoteLite contributors 2026.
// Swift adaptation of RunsRetriever. Original author: Hervé Bitteur.
// This program comes WITHOUT ANY WARRANTY. See LICENSE and NOTICE.md.

public enum RunOrientation: String, Equatable, Sendable {
    case horizontal
    case vertical
}

/// A maximal consecutive foreground interval. `start` is inclusive.
public struct ForegroundRun: Equatable, Sendable {
    public let start: Int
    public let length: Int
    public var endExclusive: Int { start + length }

    // Only extraction creates runs, so length is positive and endpoints are in bounds.
    init(start: Int, length: Int) {
        self.start = start
        self.length = length
    }
}

public struct RunTable: Equatable, Sendable {
    public let width: Int
    public let height: Int
    public let orientation: RunOrientation
    /// One sequence for every row (horizontal) or column (vertical), including empty ones.
    public let sequences: [[ForegroundRun]]
    public let runCount: Int
    public let foregroundPixelCount: Int
}

extension AudiverisPreprocessor {
    /// Retrieves whole-image runs using Audiveris' start/length and orientation conventions.
    /// Region callbacks and run rejection are outside this first porting slice.
    public static func retrieveRuns(
        _ image: BinaryImage,
        orientation: RunOrientation,
        limits: ProcessingLimits = .default,
        cancellationCheck: () throws -> Void = { try Task.checkCancellation() }
    ) throws -> RunTable {
        try cancellationCheck()
        _ = try limits.validateDimensions(width: image.width, height: image.height)
        let positionCount = orientation == .horizontal ? image.height : image.width
        let coordinateCount = orientation == .horizontal ? image.width : image.height
        var sequences = [[ForegroundRun]]()
        sequences.reserveCapacity(positionCount)
        var runCount = 0
        var foregroundCount = 0
        for position in 0..<positionCount {
            try cancellationCheck()
            var sequence = [ForegroundRun]()
            var start: Int?
            for coordinate in 0..<coordinateCount {
                if coordinate & 4095 == 0 { try cancellationCheck() }
                let index = orientation == .horizontal
                    ? position * image.width + coordinate
                    : coordinate * image.width + position
                if image.pixels[index] == 0 {
                    foregroundCount += 1
                    if start == nil { start = coordinate }
                } else if let runStart = start {
                    guard runCount < limits.maxRunCount else {
                        throw PreprocessingError.runLimitExceeded(limit: limits.maxRunCount)
                    }
                    sequence.append(ForegroundRun(start: runStart, length: coordinate - runStart))
                    runCount += 1
                    start = nil
                }
            }
            // Flush a foreground run touching the final pixel, including a one-pixel image.
            if let runStart = start {
                guard runCount < limits.maxRunCount else {
                    throw PreprocessingError.runLimitExceeded(limit: limits.maxRunCount)
                }
                sequence.append(ForegroundRun(start: runStart, length: coordinateCount - runStart))
                runCount += 1
            }
            sequences.append(sequence)
        }
        try cancellationCheck()
        return RunTable(width: image.width, height: image.height, orientation: orientation,
                        sequences: sequences, runCount: runCount, foregroundPixelCount: foregroundCount)
    }
}
