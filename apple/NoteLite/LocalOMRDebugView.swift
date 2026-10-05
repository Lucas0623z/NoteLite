#if DEBUG
import CoreGraphics
import SwiftUI
import UniformTypeIdentifiers

/// Deliberately separate from LibraryStore: this harness has no upload or
/// recognition action and cannot mark a library score as ready to practice.
struct LocalOMRDebugView: View {
    @Environment(\.dismiss) private var dismiss
    @StateObject private var model = LocalOMRDebugModel()
    @State private var importing = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    Text("尚未完成音符识别")
                        .font(.headline).accessibilityIdentifier("local-omr-incomplete")
                    Text("本阶段测试 Orpheus AI 的页面二值化与前景游程。不能生成 MusicXML。所有处理都在本机进行，不会上传文件。")
                        .foregroundStyle(.secondary)
                    HStack {
                        Button("选择 PDF 或图片") { importing = true }
                            .accessibilityIdentifier("local-omr-import")
                        Button("载入合成五线谱") { model.loadDemo() }
                            .accessibilityIdentifier("local-omr-demo")
                    }.disabled(model.busy)
                    if let url = model.sourceURL {
                        Text(url.lastPathComponent).font(.headline).lineLimit(2)
                    }
                    if let info = model.sourceInfo {
                        Text("文件共 \(info.pageCount) 页；每次仅处理你选择的一页。")
                        Stepper("选择第 \(model.selectedPage) 页", value: $model.selectedPage, in: 1...info.pageCount)
                            .disabled(model.busy).accessibilityIdentifier("local-omr-page")
                        Button("预处理所选页") { model.process() }
                            .buttonStyle(.borderedProminent).disabled(model.busy)
                            .accessibilityIdentifier("local-omr-run")
                    }
                    if model.busy {
                        HStack {
                            ProgressView("正在本地处理…")
                            Button("取消") { model.cancel() }.accessibilityIdentifier("local-omr-cancel")
                        }
                    }
                    if let message = model.message {
                        Text(message).foregroundStyle(.secondary).accessibilityIdentifier("local-omr-message")
                    }
                    if let result = model.result {
                        let processing = result.processing
                        Text("第 \(result.pageIndex + 1) / \(result.source.pageCount) 页 · \(processing.binaryImage.width) × \(processing.binaryImage.height) 像素\n水平游程 \(processing.horizontalRuns.runCount) · 垂直游程 \(processing.verticalRuns.runCount)\n前景像素 \(processing.foregroundPixelCount)")
                            .font(.subheadline.monospacedDigit())
                            .accessibilityIdentifier("local-omr-result")
                        if let preview = model.preview {
                            Image(decorative: preview, scale: 1)
                                .resizable().interpolation(.none).scaledToFit()
                                .accessibilityLabel("所选页的本地二值化预览")
                                .accessibilityIdentifier("local-omr-preview")
                        }
                    }
                    Text("测试限制：文件不超过 50 MB；栅格最长边 2400 像素、总像素不超过 400 万。大页面会缩小，可能损失细小谱面细节。")
                        .font(.caption).foregroundStyle(.secondary)
                }.padding(24).frame(maxWidth: 900).frame(maxWidth: .infinity, alignment: .leading)
            }
            .navigationTitle("本地引擎移植测试").noteLiteInlineTitle()
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("完成") { model.cancel(); dismiss() }.accessibilityIdentifier("local-omr-close")
                }
            }
            .fileImporter(isPresented: $importing, allowedContentTypes: [.pdf, .png, .jpeg, .tiff]) { result in
                switch result {
                case .success(let url): model.selectSource(url)
                case .failure(let error): model.message = error.localizedDescription
                }
            }
            .onDisappear { model.close() }
        }
        #if os(macOS)
        .noteLiteSheetSize(idealWidth: 820, idealHeight: 780)
        #endif
    }
}

@MainActor
private final class LocalOMRDebugModel: ObservableObject {
    @Published var sourceURL: URL?
    @Published var sourceInfo: LocalOMRSourceInfo?
    @Published var selectedPage = 1 { didSet { result = nil; preview = nil } }
    @Published var result: LocalOMRPageResult?
    @Published var preview: CGImage?
    @Published var busy = false
    @Published var message: String?
    private var operation: Task<Void, Never>?
    private var generation = UUID()
    private var demoURL: URL?

    func selectSource(_ url: URL) {
        cancel()
        sourceURL = url
        sourceInfo = nil
        selectedPage = 1
        result = nil
        preview = nil
        message = nil
        busy = true
        let token = generation
        operation = Task {
            do {
                let info = try await LocalOMRProcessor.inspect(url: url)
                guard token == generation else { return }
                sourceInfo = info
            } catch {
                guard token == generation else { return }
                message = error is CancellationError ? "已取消本地处理。" : error.localizedDescription
            }
            busy = false
        }
    }

    func process() {
        guard let sourceURL, sourceInfo != nil, !busy else { return }
        cancel()
        result = nil
        preview = nil
        message = nil
        busy = true
        let token = generation
        let index = selectedPage - 1
        operation = Task {
            do {
                let page = try await LocalOMRProcessor.preprocess(url: sourceURL, pageIndex: index)
                guard token == generation else { return }
                result = page
                preview = page.previewImage()
            } catch {
                guard token == generation else { return }
                message = error is CancellationError ? "已取消本地处理。" : error.localizedDescription
            }
            busy = false
        }
    }

    func loadDemo() {
        do {
            let url = FileManager.default.temporaryDirectory.appendingPathComponent("notelite-local-staff-\(UUID().uuidString).pdf")
            try LocalOMRDebugFixture.writeStaffPDF(to: url)
            if let demoURL { try? FileManager.default.removeItem(at: demoURL) }
            demoURL = url
            selectSource(url)
        } catch { message = error.localizedDescription }
    }

    func cancel() {
        generation = UUID()
        operation?.cancel()
        operation = nil
        if busy { message = "已取消本地处理。" }
        busy = false
    }

    func close() {
        cancel()
        if let demoURL { try? FileManager.default.removeItem(at: demoURL) }
        demoURL = nil
    }
}

/// Generated locally; no bundled copyrighted score, network, or OMR server.
enum LocalOMRDebugFixture {
    static func writeStaffPDF(to url: URL) throws {
        var box = CGRect(x: 0, y: 0, width: 400, height: 200)
        guard let consumer = CGDataConsumer(url: url as CFURL),
              let context = CGContext(consumer: consumer, mediaBox: &box, nil) else {
            throw LocalOMRError.renderingFailed
        }
        context.beginPDFPage(nil)
        context.setFillColor(gray: 1, alpha: 1)
        context.fill(box)
        context.setFillColor(gray: 0, alpha: 1)
        for index in 0..<5 {
            context.fill(CGRect(x: 30, y: 75 + index * 10, width: 340, height: 1))
        }
        for index in 0..<4 {
            let x = 85 + index * 70
            let y = 75 + index * 5
            context.fillEllipse(in: CGRect(x: x, y: y, width: 12, height: 8))
            context.fill(CGRect(x: x + 10, y: y + 4, width: 2, height: 30))
        }
        context.endPDFPage()
        context.closePDF()
    }
}
#endif
