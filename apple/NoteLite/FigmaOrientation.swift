import Foundation
#if os(iOS)
import UIKit

@MainActor
final class FigmaOrientationPolicy {
    static let shared = FigmaOrientationPolicy()
    private(set) var lockedLandscape = false
    private var previousOrientation: UIInterfaceOrientation?
    private var generation = 0
    var onError: ((String) -> Void)?

    var allowedOrientations: UIInterfaceOrientationMask {
        if lockedLandscape { return .landscape }
        return UIDevice.current.userInterfaceIdiom == .pad ? .all : .allButUpsideDown
    }

    func set(_ mode: String, window: UIWindow?) throws -> [String: Any] {
        guard mode == "landscape" || mode == "restore" else {
            throw CloudOMRError(code: "invalid_orientation", message: "不支持的页面方向。")
        }
        guard let scene = window?.windowScene else {
            throw CloudOMRError(code: "orientation_unavailable", message: "当前窗口尚未准备好切换方向。")
        }
        let priorLock = lockedLandscape
        let priorOrientation = previousOrientation
        generation += 1
        let ticket = generation
        let requested: UIInterfaceOrientationMask
        if mode == "landscape" {
            if !lockedLandscape { previousOrientation = scene.interfaceOrientation }
            lockedLandscape = true
            requested = .landscape
        } else {
            lockedLandscape = false
            requested = Self.mask(previousOrientation ?? .portrait)
            previousOrientation = nil
        }
        window?.rootViewController?.setNeedsUpdateOfSupportedInterfaceOrientations()
        scene.requestGeometryUpdate(.iOS(interfaceOrientations: requested)) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self, generation == ticket else { return }
                // A failed restore must still release the app's landscape lock.
                lockedLandscape = mode == "restore" ? false : priorLock
                previousOrientation = mode == "restore" ? nil : priorOrientation
                window?.rootViewController?.setNeedsUpdateOfSupportedInterfaceOrientations()
                let message: String
                if mode == "restore" {
                    message = "系统未能恢复原来的方向，请调整设备或窗口方向。"
                } else if UIDevice.current.userInterfaceIdiom == .pad {
                    message = "系统未能自动横屏。在窗口模式下，请切换为全屏或调整窗口为横向查看乐谱。"
                } else {
                    message = "系统未能自动横屏，请将设备转为横向查看乐谱。"
                }
                onError?(message)
            }
        }
        return ["mode": mode, "requested": true, "platform": "ios"]
    }

    private static func mask(_ orientation: UIInterfaceOrientation) -> UIInterfaceOrientationMask {
        switch orientation {
        case .landscapeLeft: return .landscapeLeft
        case .landscapeRight: return .landscapeRight
        case .portraitUpsideDown: return .portraitUpsideDown
        default: return .portrait
        }
    }
}

@MainActor
final class NoteLiteOrientationAppDelegate: NSObject, UIApplicationDelegate {
    func application(_ application: UIApplication,
                     supportedInterfaceOrientationsFor window: UIWindow?) -> UIInterfaceOrientationMask {
        FigmaOrientationPolicy.shared.allowedOrientations
    }
}
#endif
