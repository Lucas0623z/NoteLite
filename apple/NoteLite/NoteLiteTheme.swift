import SwiftUI
#if os(macOS)
import AppKit
#else
import UIKit
#endif

/// Shared semantic colors from the approved NoteLite Apple-platform design.
enum NoteLiteTheme {
    static let accent = adaptive(0x345DA8, dark: 0x91B2ED)
    static let window = adaptive(0xF5F6F8, dark: 0x191C22)
    static let sidebar = adaptive(0xECEEF1, dark: 0x20242B)
    static let surface = adaptive(0xFFFFFF, dark: 0x252A32)
    static let paper = adaptive(0xFDFCF9, dark: 0xFDFCF9)
    static let ink = adaptive(0x252A34, dark: 0xE9ECF1)
    static let secondary = adaptive(0x697383, dark: 0xAEB7C5)
    static let line = adaptive(0xDEE2E8, dark: 0x3B424E)
    static let selection = adaptive(0xE9EFF9, dark: 0x2D3F5D)
    static let correct = adaptive(0x417F62, dark: 0x89C4A5)
    static let wrong = adaptive(0xB84F45, dark: 0xEE9B90)

    private static func adaptive(_ light: UInt32, dark: UInt32) -> Color {
        func rgb(_ value: UInt32) -> (CGFloat, CGFloat, CGFloat) {
            (CGFloat((value >> 16) & 0xFF) / 255,
             CGFloat((value >> 8) & 0xFF) / 255,
             CGFloat(value & 0xFF) / 255)
        }
        #if os(macOS)
        return Color(nsColor: NSColor(name: nil) { appearance in
            let isDark = appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
            let (r, g, b) = rgb(isDark ? dark : light)
            return NSColor(srgbRed: r, green: g, blue: b, alpha: 1)
        })
        #else
        return Color(uiColor: UIColor { traits in
            let (r, g, b) = rgb(traits.userInterfaceStyle == .dark ? dark : light)
            return UIColor(red: r, green: g, blue: b, alpha: 1)
        })
        #endif
    }
}

extension View {
    /// `navigationBarTitleDisplayMode` is unavailable on native macOS.
    @ViewBuilder func noteLiteInlineTitle() -> some View {
        #if os(iOS)
        navigationBarTitleDisplayMode(.inline)
        #else
        self
        #endif
    }
}
