import Foundation
import UniformTypeIdentifiers
import WebKit
#if os(iOS)
import UIKit
#else
import AppKit
#endif

/// Delegate completion includes cancellation on the minimum supported Apple OS.
/// SwiftUI's older fileImporter/fileExporter completion does not report Cancel.
@MainActor
final class FigmaNativeFilePanel: NSObject {
    private var completion: ((Result<[URL], Error>) -> Void)?
    #if os(iOS)
    private var picker: UIDocumentPickerViewController?
    #else
    private var panel: NSSavePanel?
    #endif

    private init(completion: @escaping (Result<[URL], Error>) -> Void) {
        self.completion = completion
    }

    static func open(in webView: WKWebView, completion: @escaping (Result<[URL], Error>) -> Void) throws -> FigmaNativeFilePanel {
        let result = FigmaNativeFilePanel(completion: completion)
        let types: [UTType] = [.pdf, .png, .jpeg, .xml,
                              UTType(filenameExtension: "musicxml") ?? .xml,
                              UTType(filenameExtension: "mxl") ?? .zip]
        #if os(iOS)
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: types, asCopy: false)
        picker.allowsMultipleSelection = false
        try result.present(picker, in: webView)
        #else
        let panel = NSOpenPanel()
        panel.allowedContentTypes = types
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        result.panel = panel
        let completed: (NSApplication.ModalResponse) -> Void = { response in
            result.finish(response == .OK ? .success(panel.urls) : .failure(CancellationError()))
        }
        if let window = webView.window { panel.beginSheetModal(for: window, completionHandler: completed) }
        else { panel.begin(completionHandler: completed) }
        #endif
        return result
    }

    static func save(_ source: URL, in webView: WKWebView,
                     completion: @escaping (Result<[URL], Error>) -> Void) throws -> FigmaNativeFilePanel {
        let result = FigmaNativeFilePanel(completion: completion)
        #if os(iOS)
        let picker = UIDocumentPickerViewController(forExporting: [source], asCopy: true)
        try result.present(picker, in: webView)
        #else
        let panel = NSSavePanel()
        panel.nameFieldStringValue = source.lastPathComponent
        panel.allowedContentTypes = [UTType(filenameExtension: source.pathExtension) ?? .data]
        panel.canCreateDirectories = true
        result.panel = panel
        let completed: (NSApplication.ModalResponse) -> Void = { response in
            guard response == .OK, let destination = panel.url else {
                result.finish(.failure(CancellationError()))
                return
            }
            let scoped = destination.startAccessingSecurityScopedResource()
            Task {
                defer { if scoped { destination.stopAccessingSecurityScopedResource() } }
                do {
                    try await Task.detached(priority: .userInitiated) {
                        try Data(contentsOf: source).write(to: destination, options: .atomic)
                    }.value
                    result.finish(.success([destination]))
                } catch { result.finish(.failure(error)) }
            }
        }
        if let window = webView.window { panel.beginSheetModal(for: window, completionHandler: completed) }
        else { panel.begin(completionHandler: completed) }
        #endif
        return result
    }

    func cancel() {
        #if os(iOS)
        picker?.dismiss(animated: true)
        #else
        if let panel, let parent = panel.sheetParent { parent.endSheet(panel, returnCode: .cancel) }
        panel?.orderOut(nil)
        #endif
        finish(.failure(CancellationError()))
    }

    private func finish(_ value: Result<[URL], Error>) {
        let callback = completion
        completion = nil
        callback?(value)
    }

    #if os(iOS)
    private func present(_ picker: UIDocumentPickerViewController, in webView: WKWebView) throws {
        guard let presenter = webView.window?.rootViewController, presenter.presentedViewController == nil else {
            throw CloudOMRError(code: "busy", message: "请先关闭当前系统窗口后再选择文件。")
        }
        self.picker = picker
        picker.delegate = self
        picker.presentationController?.delegate = self
        presenter.present(picker, animated: true) { [weak self, weak picker] in
            picker?.presentationController?.delegate = self
        }
    }
    #endif
}

#if os(iOS)
extension FigmaNativeFilePanel: UIDocumentPickerDelegate, UIAdaptivePresentationControllerDelegate {
    func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
        finish(urls.isEmpty ? .failure(CancellationError()) : .success(urls))
    }
    func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) {
        finish(.failure(CancellationError()))
    }
    func presentationControllerDidDismiss(_ presentationController: UIPresentationController) {
        finish(.failure(CancellationError()))
    }
}
#endif
