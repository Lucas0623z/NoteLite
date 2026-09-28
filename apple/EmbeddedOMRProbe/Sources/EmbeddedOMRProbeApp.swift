// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 NoteLite contributors.
import SwiftUI

@main
struct EmbeddedOMRProbeApp: App {
    @StateObject private var model = ProbeModel()
    var body: some Scene {
        WindowGroup {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Text("Audiveris embedded probe").font(.title2.bold())
                    Text(model.status).font(.headline)
                    Text("This test runs the bundled Java engine, fonts, OCR and score export in this app's process.")
                    if model.running { ProgressView() }
                    Text(model.report).font(.system(.footnote, design: .monospaced)).textSelection(.enabled)
                    if let reportURL = model.reportURL {
                        ShareLink("Share test report", item: reportURL)
                    }
                }.padding()
            }
            .task { await model.run() }
        }
    }
}

@MainActor
final class ProbeModel: ObservableObject {
    @Published var status = "Waiting to start"
    @Published var report = ""
    @Published var running = false
    @Published var reportURL: URL?
    private var started = false

    func run() async {
        guard !started else { return }
        started = true
        running = true
        status = "Running native components and full score recognition…"
        let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let resultURL = documents.appendingPathComponent("embedded-probe-result.json")
        do {
            guard let resources = Bundle.main.url(forResource: "ProbeResources", withExtension: nil) else {
                throw CocoaError(.fileNoSuchFile)
            }
            let sandbox = documents.appendingPathComponent("omr", isDirectory: true)
            let text: String = try await withCheckedThrowingContinuation { continuation in
                // Zero interprets Java on the native stack; reserve enough for the initiating worker.
                let worker = Thread {
                    do {
                        // This request is cancelled before native entry. It must
                        // return before touching an input file or starting the VM.
                        let cancellation = EmbeddedOMRCancellation()
                        cancellation.cancel()
                        do {
                            _ = try EmbeddedJVM.recognize(resourceRoot: sandbox.appendingPathComponent("must-not-be-opened", isDirectory: true).path,
                                                          sandbox: sandbox.path,
                                                          input: sandbox.appendingPathComponent("must-not-be-read.png").path,
                                                          cancellation: cancellation)
                            throw CocoaError(.coderInvalidValue)
                        } catch let error as NSError {
                            guard error.domain == NSCocoaErrorDomain && error.code == NSUserCancelledError else {
                                throw error
                            }
                        }
                        let result = try EmbeddedJVM.run(resourceRoot: resources.path, sandbox: sandbox.path)
                        guard var report = try JSONSerialization.jsonObject(with: Data(result.utf8)) as? [String: Any] else {
                            throw CocoaError(.coderReadCorrupt)
                        }
                        report["cancelledBeforeVMStart"] = true
                        let data = try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys])
                        continuation.resume(returning: String(decoding: data, as: UTF8.self))
                    } catch {
                        continuation.resume(throwing: error)
                    }
                }
                worker.name = "Embedded OMR probe"
                worker.stackSize = 8 * 1024 * 1024
                worker.start()
            }
            try Data(text.utf8).write(to: resultURL, options: .atomic)
            report = text
            status = "Recognition and export passed"
            NSLog("EMBEDDED_OMR_PROBE_RESULT %@", text)
        } catch {
            status = "Probe failed"
            let failure: [String: Any] = ["status": "FAILED", "error": error.localizedDescription,
                                          "fullScoreRecognitionTested": false]
            let data = (try? JSONSerialization.data(withJSONObject: failure, options: [.prettyPrinted, .sortedKeys]))
                ?? Data("{\"status\":\"FAILED\"}".utf8)
            try? data.write(to: resultURL, options: .atomic)
            report = String(decoding: data, as: UTF8.self)
            NSLog("EMBEDDED_OMR_PROBE_RESULT %@", report)
        }
        reportURL = resultURL
        running = false
    }
}
