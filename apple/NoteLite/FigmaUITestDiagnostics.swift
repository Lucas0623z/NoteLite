#if DEBUG
import Foundation

/// Static native UI test events only. This file is collected by the Apple CI
/// runner; production builds never install or write these diagnostics.
@MainActor
enum FigmaUITestDiagnostics {
    static func record(_ message: String) {
        guard ProcessInfo.processInfo.arguments.contains("--uitesting-figma"),
              message.hasPrefix("[NoteLite dialog]") || message.hasPrefix("[NoteLite window]") else { return }
        let line = "\(ISO8601DateFormatter().string(from: Date())) pid=\(ProcessInfo.processInfo.processIdentifier) \(message.prefix(500))\n"
        NSLog("%@", line)
        guard let directory = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first,
              let data = line.data(using: .utf8) else { return }
        let file = directory.appendingPathComponent("FigmaUITestDiagnostics.log")
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            let size = (try? file.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
            if !FileManager.default.fileExists(atPath: file.path) || size > 256 * 1024 {
                try data.write(to: file, options: .atomic)
            } else {
                let handle = try FileHandle(forWritingTo: file)
                defer { try? handle.close() }
                try handle.seekToEnd()
                try handle.write(contentsOf: data)
            }
        } catch {
            // Logging must never change the product's actual request/UI result.
        }
    }
}
#endif
