// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 NoteLite contributors.

import AudiverisCore
import Dispatch
import Foundation

// Synthetic A4-sized staff raster. This measures preprocessing, not recognition accuracy.
let width = 2480
let height = 3508
var pixels = [UInt8](repeating: 248, count: width * height)
for staffTop in stride(from: 180, to: height - 180, by: 230) {
    for line in 0..<5 {
        for y in (staffTop + line * 14)..<(staffTop + line * 14 + 2) {
            for x in 140..<(width - 140) { pixels[y * width + x] = 12 }
        }
    }
    for x in stride(from: 210, to: width - 160, by: 95) {
        let centerY = staffTop + (x % 5) * 14
        for y in (centerY - 4)...(centerY + 4) {
            for dx in -7...7 where dx * dx * 16 + (y - centerY) * (y - centerY) * 49 <= 784 {
                pixels[y * width + x + dx] = 8
            }
        }
        for y in (centerY - 44)..<centerY { pixels[y * width + x + 7] = 8 }
    }
}
let image = try GrayImage(width: width, height: height, pixels: pixels)
let start = DispatchTime.now().uptimeNanoseconds
let result = try AudiverisPreprocessor.preprocess(image)
let elapsed = Double(DispatchTime.now().uptimeNanoseconds - start) / 1_000_000_000
let totalRuns = result.horizontalRuns.runCount + result.verticalRuns.runCount
let integralBytes = 2 * 38 * height * MemoryLayout<Int64>.stride
let report: [String: Any] = [
    "input": "synthetic-staff-page",
    "stage": "binarization-and-runs-only",
    "width": width,
    "height": height,
    "pixels": width * height,
    "elapsedSeconds": elapsed,
    "foregroundPixels": result.foregroundPixelCount,
    "horizontalRuns": result.horizontalRuns.runCount,
    "verticalRuns": result.verticalRuns.runCount,
    "integralTileBytes": integralBytes,
    // Payload estimate excludes array spare capacity, allocator overhead, and process memory.
    "estimatedPayloadBytes": 2 * width * height + integralBytes
        + totalRuns * MemoryLayout<ForegroundRun>.stride,
    "configuredCombinedRunLimit": ProcessingLimits.default.maxRunCount,
    "configuredIntegralByteLimit": ProcessingLimits.default.maxIntegralBytes
]
let json = try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
print(String(decoding: json, as: UTF8.self))
