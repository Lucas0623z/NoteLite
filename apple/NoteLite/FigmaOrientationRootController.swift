#if os(iOS)
import UIKit

/// A UIKit orientation owner around the existing SwiftUI root. Containment
/// retains the exact Figma view, alerts and native file panels without adding
/// navigation chrome, safe-area padding, transforms or a second web view.
@MainActor
final class FigmaOrientationRootController: UIViewController {
    private let content: UIViewController
    #if DEBUG
    private var lastGeometry = ""
    #endif

    private init(content: UIViewController) {
        self.content = content
        super.init(nibName: nil, bundle: nil)
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError("Use the existing root controller") }

    static func install(in window: UIWindow) {
        guard let current = window.rootViewController,
              !(current is FigmaOrientationRootController) else { return }
        window.rootViewController = FigmaOrientationRootController(content: current)
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .clear
        addChild(content)
        content.view.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(content.view)
        NSLayoutConstraint.activate([
            content.view.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            content.view.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            content.view.topAnchor.constraint(equalTo: view.topAnchor),
            content.view.bottomAnchor.constraint(equalTo: view.bottomAnchor)
        ])
        content.didMove(toParent: self)
    }

    override var shouldAutorotate: Bool { true }
    override var supportedInterfaceOrientations: UIInterfaceOrientationMask {
        FigmaOrientationPolicy.shared.allowedOrientations
    }
    override var preferredInterfaceOrientationForPresentation: UIInterfaceOrientation {
        FigmaOrientationPolicy.shared.lockedLandscape ? .landscapeRight : .portrait
    }
    @available(iOS 26.0, *)
    override var prefersInterfaceOrientationLocked: Bool {
        FigmaOrientationPolicy.shared.lockedLandscape
    }
    override var childForStatusBarStyle: UIViewController? { content }
    override var childForStatusBarHidden: UIViewController? { content }
    override var childForHomeIndicatorAutoHidden: UIViewController? { content }
    override var childForScreenEdgesDeferringSystemGestures: UIViewController? { content }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        recordGeometry(reason: "layout")
    }

    override func viewWillTransition(to size: CGSize, with coordinator: UIViewControllerTransitionCoordinator) {
        super.viewWillTransition(to: size, with: coordinator)
        coordinator.animate(alongsideTransition: nil) { [weak self] _ in
            self?.recordGeometry(reason: "transition")
        }
    }

    func recordGeometry(reason: String) {
        #if DEBUG
        guard ProcessInfo.processInfo.arguments.contains("--uitesting-figma"),
              let window = viewIfLoaded?.window, let scene = window.windowScene else { return }
        let launchID = ProcessInfo.processInfo.environment["NOTELITE_UI_LAUNCH_ID"] ?? "unspecified"
        var value = "[NoteLite geometry] launch=\(launchID) pid=\(ProcessInfo.processInfo.processIdentifier) window=\(window.bounds) screen=\(scene.screen.bounds) orientation=\(scene.interfaceOrientation.rawValue) requestedLock=\(FigmaOrientationPolicy.shared.lockedLandscape)"
        if #available(iOS 26.0, *) {
            value += " effectiveLock=\(scene.effectiveGeometry.isInterfaceOrientationLocked)"
        }
        guard value != lastGeometry else { return }
        lastGeometry = value
        FigmaUITestDiagnostics.record(value + " reason=\(reason)")
        #endif
    }
}
#endif
