# Native macOS UI test display

GitHub's macOS runner advertises a screen whose supported modes cannot contain
the required 900 × 1440 content window plus its real native title bar. The CI
workflow therefore compiles `create-ui-test-display.m` from this repository and
keeps it alive until the native XCTest run has captured the actual app window.

The helper creates an 1800 × 1800, non-HiDPI WindowServer display and makes it the
primary screen using public CoreGraphics configuration calls. Its `ready` output
requires a real `NSScreen`, adequate visible bounds, and the correct primary
display ID. The tests retain their 1440 × 900 and 900 × 1440 WKWebView assertions
and also require the actual native window to fit wholly inside a visible screen.
Neither page CSS nor the production window implementation is scaled or replaced.

The display creation declarations and descriptor setup are derived from
[Chromium's official native test helper](https://chromium.googlesource.com/chromium/src/+/b24245976fd032dfbc62673317b26a5ecd802b59/ui/display/mac/test/virtual_display_util_mac.mm)
under the accompanying BSD license. `CGVirtualDisplay` is an undocumented macOS
interface, so this executable is strictly test infrastructure: the Xcode targets
include `apple/NoteLite`, not `apple/scripts`. No helper, binary, private display
interface, or extra dependency is included in an application archive.

The program refuses to run outside GitHub Actions. A failed creation fails the
setup; it never changes the requested dimensions or manufactures a passing
viewport. SIGTERM restores the original screen origins and releases the display.
CI evidence must describe this as a native virtual test display, not a physical
monitor on a user's Mac. `native-test-display.json`, `display-modes.json`, native
window metrics, and screenshots are uploaded together with XCTest results.
