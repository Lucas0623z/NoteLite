import Foundation
#if os(iOS)
import UIKit

@MainActor
final class FigmaOrientationPolicy {
    static let shared = FigmaOrientationPolicy()
    private(set) var lockedLandscape = false
    private(set) var restoringOrientation = false
    private var preparingLandscape = false
    private var previousOrientation: UIInterfaceOrientation?
    private var generation = 0
    private var failedGeneration: Int?
    private var geometryTask: Task<Void, Never>?
    var onError: ((String) -> Void)?

    var prefersOrientationLock: Bool { lockedLandscape || restoringOrientation }

    var allowedOrientations: UIInterfaceOrientationMask {
        if lockedLandscape && !preparingLandscape { return .landscape }
        return UIDevice.current.userInterfaceIdiom == .pad ? .all : .allButUpsideDown
    }

    func set(_ mode: String, window: UIWindow?) throws -> [String: Any] {
        guard mode == "landscape" || mode == "restore" else {
            throw CloudOMRError(code: "invalid_orientation", message: "不支持的页面方向。")
        }
        guard let scene = window?.windowScene else {
            throw CloudOMRError(code: "orientation_unavailable", message: "当前窗口尚未准备好切换方向。")
        }
        // iPadOS 26 consults the root controller's lock preference as well as
        // the application mask. Keep the existing SwiftUI root and its state
        // inside a chrome-free UIKit container that supplies that preference.
        if let window { FigmaOrientationRootController.install(in: window) }
        let priorLock = lockedLandscape
        let priorOrientation = previousOrientation
        geometryTask?.cancel()
        generation += 1
        let ticket = generation
        let requested: UIInterfaceOrientationMask
        if mode == "landscape" {
            if !lockedLandscape && !restoringOrientation {
                previousOrientation = scene.interfaceOrientation
            }
            lockedLandscape = true
            restoringOrientation = false
            if #available(iOS 26.0, *), UIDevice.current.userInterfaceIdiom == .pad {
                // Retain support for the current portrait orientation while
                // UIKit establishes its fullscreen orientation lock.
                preparingLandscape = !scene.interfaceOrientation.isLandscape
            } else {
                preparingLandscape = false
            }
            requested = .landscape
        } else {
            // iPadOS 26 permits a programmatic orientation change after the
            // fullscreen scene's lock becomes effective. Keep that preference
            // through the return rotation, then release it after real geometry
            // has restored. Releasing it before the request causes error 101.
            restoringOrientation = prefersOrientationLock
            lockedLandscape = false
            preparingLandscape = false
            requested = Self.mask(previousOrientation ?? .portrait)
        }
        updateController(in: window)

        geometryTask = Task { @MainActor [weak self, weak window] in
            guard let self, generation == ticket, let window else { return }
            if !Self.matches(requested, scene: scene, window: window) {
                if #available(iOS 26.0, *), UIDevice.current.userInterfaceIdiom == .pad,
                   prefersOrientationLock {
                    // setNeedsUpdateOfPrefersInterfaceOrientationLocked is
                    // asynchronous. Do not request a rotation in the same
                    // turn that replaces the root or updates its preference.
                    let clock = ContinuousClock()
                    let deadline = clock.now.advanced(by: .seconds(2))
                    while !scene.effectiveGeometry.isInterfaceOrientationLocked,
                          clock.now < deadline, generation == ticket, !Task.isCancelled {
                        try? await Task.sleep(nanoseconds: 40_000_000)
                    }
                    guard generation == ticket, !Task.isCancelled else { return }
                    (window.rootViewController as? FigmaOrientationRootController)?
                        .recordGeometry(reason: "effective-lock-before-geometry")
                }

                preparingLandscape = false
                updateController(in: window)

                // If the system declines the lock, preserve its actual public
                // geometry error rather than inventing a successful rotation.
                scene.requestGeometryUpdate(.iOS(interfaceOrientations: requested)) { [weak self, weak window] error in
                    Task { @MainActor [weak self, weak window] in
                        guard let self, generation == ticket, failedGeneration != ticket else { return }
                        // Updating supported orientations can already apply
                        // the requested rotation before a concurrent geometry
                        // action returns BSActionErrorDomain. Keep the lock
                        // only when the real scene and window have reached the
                        // target; otherwise retain the original failure path.
                        if let window, window.windowScene === scene,
                           Self.matches(requested, scene: scene, window: window) {
                            #if DEBUG
                            let nativeError = error as NSError
                            FigmaUITestDiagnostics.record("[NoteLite geometry] geometry-error-after-target-applied mode=\(mode) domain=\(nativeError.domain) code=\(nativeError.code)")
                            #endif
                            updateController(in: window)
                            return
                        }
                        fail(mode, error: error, ticket: ticket, window: window,
                             priorLock: priorLock, priorOrientation: priorOrientation)
                    }
                }

                let clock = ContinuousClock()
                let deadline = clock.now.advanced(by: .seconds(3))
                while !Self.matches(requested, scene: scene, window: window),
                      clock.now < deadline, generation == ticket,
                      failedGeneration != ticket, !Task.isCancelled {
                    try? await Task.sleep(nanoseconds: 40_000_000)
                }
                guard generation == ticket, failedGeneration != ticket, !Task.isCancelled else { return }
                guard Self.matches(requested, scene: scene, window: window) else {
                    fail(mode, error: NSError(domain: "NoteLiteOrientation", code: 1,
                                              userInfo: [NSLocalizedDescriptionKey: "The requested native orientation did not become effective."]),
                         ticket: ticket, window: window, priorLock: priorLock,
                         priorOrientation: priorOrientation)
                    return
                }
            }
            guard generation == ticket, !Task.isCancelled else { return }
            preparingLandscape = false
            if mode == "restore" {
                restoringOrientation = false
                previousOrientation = nil
                updateController(in: window)
            }
        }
        return ["mode": mode, "requested": true, "platform": "ios"]
    }

    private func fail(_ mode: String, error: Error, ticket: Int, window: UIWindow?,
                      priorLock: Bool, priorOrientation: UIInterfaceOrientation?) {
        guard generation == ticket, failedGeneration != ticket else { return }
        failedGeneration = ticket
        #if DEBUG
        let nativeError = error as NSError
        FigmaUITestDiagnostics.record("[NoteLite geometry] request-failed mode=\(mode) domain=\(nativeError.domain) code=\(nativeError.code) detail=\(nativeError.localizedDescription.prefix(250))")
        #endif
        // A failed restore must still release the app's orientation lock.
        lockedLandscape = mode == "restore" ? false : priorLock
        restoringOrientation = false
        preparingLandscape = false
        previousOrientation = mode == "restore" ? nil : priorOrientation
        updateController(in: window)
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

    private static func matches(_ requested: UIInterfaceOrientationMask,
                                scene: UIWindowScene, window: UIWindow) -> Bool {
        let orientation = scene.interfaceOrientation
        guard orientation != .unknown, requested.contains(mask(orientation)) else { return false }
        return orientation.isLandscape ? window.bounds.width > window.bounds.height :
            window.bounds.height > window.bounds.width
    }

    private func updateController(in window: UIWindow?) {
        let root = window?.rootViewController
        root?.setNeedsUpdateOfSupportedInterfaceOrientations()
        if #available(iOS 26.0, *) {
            root?.setNeedsUpdateOfPrefersInterfaceOrientationLocked()
        }
        root?.viewIfLoaded?.setNeedsLayout()
        (root as? FigmaOrientationRootController)?.recordGeometry(reason: "request")
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
