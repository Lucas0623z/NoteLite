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
        // The later attempt happens after SwiftUI has applied its initial saved
        // frame; both attempts still resize the actual AppKit content window.
        for delay in [0.15, 1.25] {
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak window] in
                guard let window else { return }
                window.setContentSize(size)
                if let visible = window.screen?.visibleFrame {
                    window.setFrameOrigin(NSPoint(x: visible.minX + 16,
                                                  y: visible.maxY - window.frame.height - 16))
                }
                window.contentView?.layoutSubtreeIfNeeded()
                let content = window.contentView?.bounds.size ?? .zero
                FigmaUITestDiagnostics.record("[NoteLite window] resize delay=\(delay) requested=\(size.width)x\(size.height) content=\(content.width)x\(content.height) frame=\(window.frame.width)x\(window.frame.height) visible=\(window.isVisible)")
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
