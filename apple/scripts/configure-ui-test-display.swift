import Foundation
import CoreGraphics

// CI environment only. Public display APIs enumerate actual supported modes;
// no virtual display is invented and production window/page code is unchanged.
// https://developer.apple.com/documentation/coregraphics/cgdisplaysetdisplaymode(_:_:_:)
let display = CGMainDisplayID()
let options = [kCGDisplayShowDuplicateLowResolutionModes as String: true] as CFDictionary
let modes = (CGDisplayCopyAllDisplayModes(display, options) as? [CGDisplayMode]) ?? []
func details(_ mode: CGDisplayMode) -> [String: Any] {
    ["id": mode.ioDisplayModeID, "width": mode.width, "height": mode.height,
     "pixelWidth": mode.pixelWidth, "pixelHeight": mode.pixelHeight, "refreshRate": mode.refreshRate]
}
let original = CGDisplayCopyDisplayMode(display)
let preferred = modes.filter { $0.width >= 1500 && $0.height >= 1550 }
    .min { $0.width * $0.height < $1.width * $1.height }
let largest = modes.max { $0.width * $0.height < $1.width * $1.height }
let selected = preferred ?? largest
var result: [String: Any] = ["displayId": display, "supportedModes": modes.map(details),
                             "bothRequestedWindowsCanFit": preferred != nil]
if let original { result["original"] = details(original) }
if let selected {
    result["selected"] = details(selected)
    result["configurationResult"] = CGDisplaySetDisplayMode(display, selected, nil).rawValue
}
if let actual = CGDisplayCopyDisplayMode(display) { result["actual"] = details(actual) }
let bounds = CGDisplayBounds(display)
result["actualBounds"] = ["width": bounds.width, "height": bounds.height]
let data = try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys])
print(String(decoding: data, as: UTF8.self))
