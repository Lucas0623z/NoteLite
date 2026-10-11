import Foundation
import CoreGraphics

// CI environment only. Public display APIs enumerate actual supported modes;
// no virtual display is invented and production window/page code is unchanged.
// https://developer.apple.com/documentation/coregraphics/cgconfigureoption
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
    // CGDisplaySetDisplayMode reverts when this short-lived helper exits.
    // Keep this disposable CI runner's supported mode for its login session.
    var configuration: CGDisplayConfigRef?
    let begin = CGBeginDisplayConfiguration(&configuration)
    result["beginResult"] = begin.rawValue
    if begin == .success {
        let configure = CGConfigureDisplayWithDisplayMode(configuration, display, selected, nil)
        result["configureResult"] = configure.rawValue
        if configure == .success {
            result["configurationResult"] = CGCompleteDisplayConfiguration(configuration, .forSession).rawValue
        } else {
            result["cancelResult"] = CGCancelDisplayConfiguration(configuration).rawValue
        }
    }
}
if let actual = CGDisplayCopyDisplayMode(display) { result["actual"] = details(actual) }
let bounds = CGDisplayBounds(display)
result["actualBounds"] = ["width": bounds.width, "height": bounds.height]
let data = try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys])
print(String(decoding: data, as: UTF8.self))
