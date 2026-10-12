#if DEBUG
import Foundation
#if os(iOS)
import UIKit
import UIKit.UIGestureRecognizerSubclass
import WebKit
#endif

/// Static native UI test events only. This file is collected by the Apple CI
/// runner; production builds never install or write these diagnostics.
@MainActor
enum FigmaUITestDiagnostics {
    static func record(_ message: String) {
        guard ProcessInfo.processInfo.arguments.contains("--uitesting-figma"),
              message.hasPrefix("[NoteLite dialog]") || message.hasPrefix("[NoteLite window]") ||
                message.hasPrefix("[NoteLite touch]") || message.hasPrefix("[NoteLite geometry]") else { return }
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

    #if os(iOS)
    static func installTouchObservation(on webView: WKWebView) {
        guard ProcessInfo.processInfo.arguments.contains("--uitesting-figma"),
              !(webView.gestureRecognizers ?? []).contains(where: { $0 is FigmaUITestTouchObservation }) else { return }
        let observer = FigmaUITestTouchObservation(target: nil, action: nil)
        observer.cancelsTouchesInView = false
        observer.delaysTouchesBegan = false
        observer.delaysTouchesEnded = false
        observer.requiresExclusiveTouchType = false
        webView.addGestureRecognizer(observer)
    }
    #endif
}

#if os(iOS)
/// Metadata-only observation of the real event received by UIKit. It never
/// recognizes a gesture, invokes an action, changes hit testing, cancels a
/// touch, delays touch delivery, or prevents WebKit's recognizers.
@MainActor
private final class FigmaUITestTouchObservation: UIGestureRecognizer {
    override func canPrevent(_ preventedGestureRecognizer: UIGestureRecognizer) -> Bool { false }
    override func canBePrevented(by preventingGestureRecognizer: UIGestureRecognizer) -> Bool { false }
    override func shouldRequireFailure(of otherGestureRecognizer: UIGestureRecognizer) -> Bool { false }
    override func shouldBeRequiredToFail(by otherGestureRecognizer: UIGestureRecognizer) -> Bool { false }

    override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent) {
        // Release immediately, irrespective of whether logging can succeed.
        defer { state = .failed }
        guard let touch = touches.first, let webView = view as? WKWebView,
              let window = webView.window else { return }
        let windowPoint = touch.location(in: window)
        let screenPoint = window.convert(windowPoint, to: window.screen.coordinateSpace)
        let webFrame = webView.convert(webView.bounds, to: window)
        let scene = window.windowScene
        let locked: String
        if #available(iOS 26, *) {
            locked = scene.map { String($0.effectiveGeometry.isInterfaceOrientationLocked) } ?? "unknown"
        } else { locked = "unavailable" }
        let launchID = ProcessInfo.processInfo.environment["NOTELITE_UI_LAUNCH_ID"]
            .flatMap(UUID.init(uuidString:))?.uuidString ?? "initial-process"
        let message = "[NoteLite touch] phase=began launch=\(launchID) t=\(number(touch.timestamp)) " +
            "window=\(rectangle(window.frame)) webInWindow=\(rectangle(webFrame)) " +
            "screen=\(rectangle(window.screen.bounds)) scale=\(number(window.screen.scale)) " +
            "nativeScale=\(number(window.screen.nativeScale)) windowPoint=\(point(windowPoint)) " +
            "screenPoint=\(point(screenPoint)) orientation=\(scene?.interfaceOrientation.rawValue ?? 0) locked=\(locked)"
        // Capture geometry now, then write after this event's delivery stack
        // has returned. File I/O must not hold the touch-dispatching method.
        DispatchQueue.main.async { FigmaUITestDiagnostics.record(message) }
    }

    private func number(_ value: CGFloat) -> String { String(format: "%.3f", Double(value)) }
    private func number(_ value: TimeInterval) -> String { String(format: "%.3f", value) }
    private func point(_ point: CGPoint) -> String { "[\(number(point.x)),\(number(point.y))]" }
    private func rectangle(_ rectangle: CGRect) -> String {
        "[\(number(rectangle.minX)),\(number(rectangle.minY)),\(number(rectangle.width)),\(number(rectangle.height))]"
    }
}
#endif
#endif
