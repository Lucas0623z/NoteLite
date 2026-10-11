#if os(macOS)
import AppKit
import WebKit

/// Debug automation sizes a real AppKit content window. Production dimensions,
/// page CSS and JavaScript layout are unchanged.
final class FigmaMacWKWebView: WKWebView {
    #if DEBUG
    private var configuredWindow: ObjectIdentifier?
    #endif

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        #if DEBUG
        guard let window, let size = Self.requestedTestSize,
              configuredWindow != ObjectIdentifier(window) else { return }
        configuredWindow = ObjectIdentifier(window)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { [weak window] in
            guard let window else { return }
            window.setContentSize(size)
            // Keep the top edge visible. A tall content area may exceed the
            // runner display; the UI test records that limit with its screenshot.
            if let visible = window.screen?.visibleFrame {
                window.setFrameOrigin(NSPoint(x: visible.minX + 16,
                                              y: visible.maxY - window.frame.height - 16))
            }
        }
        #endif
    }

    #if DEBUG
    private static var requestedTestSize: NSSize? {
        let arguments = ProcessInfo.processInfo.arguments
        guard arguments.contains("--uitesting-figma"),
              let argument = arguments.first(where: { $0.hasPrefix("--uitesting-window-size=") }) else { return nil }
        let value = argument.dropFirst("--uitesting-window-size=".count).split(separator: "x")
        guard value.count == 2, let width = Double(value[0]), let height = Double(value[1]),
              width.isFinite, height.isFinite, (840...2000).contains(width), (600...1800).contains(height) else { return nil }
        return NSSize(width: width, height: height)
    }
    #endif
}
#endif
