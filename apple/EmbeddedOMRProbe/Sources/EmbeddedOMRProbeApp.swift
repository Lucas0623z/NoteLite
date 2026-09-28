// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 NoteLite contributors.
import SwiftUI

private func requireCancelledRequest(resourceRoot: String, sandbox: String) throws {
    let cancellation = EmbeddedOMRCancellation()
    cancellation.cancel()
    do {
        _ = try EmbeddedJVM.recognize(resourceRoot: resourceRoot, sandbox: sandbox,
                                     input: sandbox + "/must-not-be-read.png", cancellation: cancellation)
        throw CocoaError(.coderInvalidValue)
    } catch let error as NSError {
        guard error.domain == NSCocoaErrorDomain && error.code == NSUserCancelledError else { throw error }
    }
}

private func reportObject(_ text: String) throws -> [String: Any] {
    guard let report = try JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any] else {
        throw CocoaError(.coderReadCorrupt)
    }
    return report
}

private func reportText(_ report: [String: Any]) throws -> String {
    String(decoding: try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys]), as: UTF8.self)
}

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

    private func onWorker(named name: String, operation: @escaping @Sendable () throws -> String) async throws -> String {
        var worker: Thread?
        let outcome: Result<String, Error> = await withCheckedContinuation { continuation in
            let thread = Thread {
                continuation.resume(returning: Result { try operation() })
            }
            thread.name = name
            thread.stackSize = 8 * 1024 * 1024
            worker = thread
            thread.start()
        }
        // The bridge has already detached before returning. Also observe the
        // native thread's completion before creating the next worker. Yielding
        // leaves the main actor available for UI work during this short handoff.
        while let thread = worker, !thread.isFinished { await Task.yield() }
        return try outcome.get()
    }

    func run() async {
        guard !started else { return }
        started = true
        running = true
        status = "Running native components and full score recognition…"
        let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let resultURL = documents.appendingPathComponent("embedded-probe-result.json")
        let primaryURL = documents.appendingPathComponent("embedded-probe-primary-result.json")
        let reuseURL = documents.appendingPathComponent("embedded-probe-reuse-result.json")
        let startedAt = ProcessInfo.processInfo.systemUptime
        var phase = "initial-recognition"
        var firstScoreRecognitionCompleted = false
        do {
            guard let resources = Bundle.main.url(forResource: "ProbeResources", withExtension: nil) else {
                throw CocoaError(.fileNoSuchFile)
            }
            let sandbox = documents.appendingPathComponent("omr", isDirectory: true)
            let primaryText = try await onWorker(named: "Embedded OMR initial probe") {
                try requireCancelledRequest(resourceRoot: sandbox.appendingPathComponent("must-not-be-opened").path,
                                            sandbox: sandbox.path)
                var initial = try reportObject(EmbeddedJVM.run(resourceRoot: resources.path, sandbox: sandbox.path))
                guard initial["status"] as? String == "SUCCESS",
                      initial["fullScoreRecognitionTested"] as? Bool == true else {
                    throw CocoaError(.coderInvalidValue)
                }
                initial["cancelledBeforeVMStart"] = true
                initial["nativeMemoryScope"] = "VM initialization, component gates and first recognition"
                return try reportText(initial)
            }
            // Preserve the original result before testing reuse, even if a later gate fails.
            try Data(primaryText.utf8).write(to: primaryURL, options: .atomic)
            firstScoreRecognitionCompleted = true
            var complete = try reportObject(primaryText)
            phase = "cancel-existing-vm"
            status = "Checking cancellation and JVM reuse…"
            _ = try await onWorker(named: "Embedded OMR cancelled reuse") {
                try requireCancelledRequest(resourceRoot: resources.path, sandbox: sandbox.path)
                return "CANCELLED"
            }
            phase = "repeat-recognition"
            let repeated = try await onWorker(named: "Embedded OMR repeated recognition") {
                try EmbeddedJVM.recognize(resourceRoot: resources.path, sandbox: sandbox.path,
                                          input: sandbox.appendingPathComponent("chula.png").path,
                                          cancellation: EmbeddedOMRCancellation())
            }
            let reuse = try reportObject(repeated)
            guard reuse["status"] as? String == "SUCCESS",
                  let firstJob = complete["outputDirectory"] as? String,
                  let secondJob = reuse["outputDirectory"] as? String, firstJob != secondJob,
                  let xml = reuse["musicXML"] as? [String], !xml.isEmpty,
                  let midi = reuse["midi"] as? [String], !midi.isEmpty else {
                throw CocoaError(.coderInvalidValue)
            }
            complete["vmReuse"] = ["status": "SUCCESS", "cancelledOnExistingVM": true,
                                    "workerCompletionObserved": true, "recognition": reuse]
            try Data(reportText(complete).utf8).write(to: reuseURL, options: .atomic)
            var jobs = Set([firstJob, secondJob])
            var documentRuns: [[String: Any]] = []
            for format in ["pdf", "tiff"] {
                phase = "two-page-\(format)-recognition"
                status = "Recognizing both pages of the \(format.uppercased()) score…"
                let fixture = "chula-two-page.\(format)"
                let documentStarted = ProcessInfo.processInfo.systemUptime
                let documentText = try await onWorker(named: "Embedded OMR two-page \(format)") {
                    let input = sandbox.appendingPathComponent(fixture)
                    let source = resources.appendingPathComponent("examples").appendingPathComponent(fixture)
                    if FileManager.default.fileExists(atPath: input.path) {
                        try FileManager.default.removeItem(at: input)
                    }
                    try FileManager.default.copyItem(at: source, to: input)
                    return try EmbeddedJVM.recognize(resourceRoot: resources.path, sandbox: sandbox.path,
                                                      input: input.path, cancellation: EmbeddedOMRCancellation())
                }
                let result = try reportObject(documentText)
                guard result["status"] as? String == "SUCCESS",
                      let job = result["outputDirectory"] as? String, jobs.insert(job).inserted,
                      let xml = result["musicXML"] as? [String], !xml.isEmpty,
                      let midi = result["midi"] as? [String], !midi.isEmpty else {
                    throw CocoaError(.coderInvalidValue)
                }
                let record: [String: Any] = ["format": format, "inputFile": fixture,
                    "recognition": result, "nativeElapsedMilliseconds":
                        Int((ProcessInfo.processInfo.systemUptime - documentStarted) * 1000)]
                documentRuns.append(record)
                try Data(reportText(record).utf8).write(
                    to: documents.appendingPathComponent("embedded-probe-\(format)-result.json"), options: .atomic)
            }
            complete["multipageDocuments"] = documentRuns
            complete["totalProbeElapsedMilliseconds"] = Int((ProcessInfo.processInfo.systemUptime - startedAt) * 1000)
            let text = try reportText(complete)
            try Data(text.utf8).write(to: resultURL, options: .atomic)
            report = text
            status = "Recognition and export passed"
            NSLog("EMBEDDED_OMR_PROBE_RESULT %@", text)
        } catch {
            status = "Probe failed"
            let failure: [String: Any] = ["status": "FAILED", "error": error.localizedDescription,
                                          "phase": phase, "fullScoreRecognitionTested": false,
                                          "firstScoreRecognitionCompleted": firstScoreRecognitionCompleted]
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
