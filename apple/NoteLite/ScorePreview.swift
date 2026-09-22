import SwiftUI
import PDFKit
import QuickLookThumbnailing
#if os(macOS)
import AppKit
#else
import UIKit
#endif

/// Thumbnails always come from the user's local document, never sample notation.
struct ScoreThumbnail: View {
    let url: URL?
    @State private var thumbnail: CGImage?

    var body: some View {
        ZStack {
            NoteLiteTheme.paper
            if let thumbnail {
                Image(decorative: thumbnail, scale: 1)
                    .resizable()
                    .scaledToFit()
                    .padding(3)
            } else {
                Image(systemName: "doc.text")
                    .font(.system(size: 22, weight: .light))
                    .foregroundStyle(Color(red: 0.41, green: 0.45, blue: 0.51))
            }
        }
        .frame(width: 52, height: 68)
        .clipShape(RoundedRectangle(cornerRadius: 4))
        .overlay(RoundedRectangle(cornerRadius: 4).stroke(NoteLiteTheme.line, lineWidth: 0.5))
        .accessibilityHidden(true)
        .task(id: url) {
            thumbnail = nil
            guard let url else { return }
            let image = await DocumentThumbnail.image(for: url, size: CGSize(width: 156, height: 204))
            guard !Task.isCancelled else { return }
            thumbnail = image
        }
    }
}

struct ScoreSourcePreview: View {
    let url: URL
    @State private var image: CGImage?
    @State private var loading = true

    private var isMusicXML: Bool {
        ["xml", "musicxml", "mxl"].contains(url.pathExtension.lowercased())
    }

    var body: some View {
        Group {
            if url.pathExtension.lowercased() == "pdf" {
                PDFDocumentPreview(url: url)
            } else if isMusicXML {
                VStack(spacing: 14) {
                    Image(systemName: "music.note.list")
                        .font(.system(size: 34, weight: .light))
                    Text("MusicXML 曲谱").font(.headline)
                    Text("开始练习即可查看完整谱面。")
                        .font(.subheadline)
                }
                .foregroundStyle(Color(red: 0.41, green: 0.45, blue: 0.51))
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let image {
                Image(decorative: image, scale: 1)
                    .resizable()
                    .scaledToFit()
                    .padding(16)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .accessibilityLabel("原始乐谱预览")
            } else if loading {
                ProgressView("正在载入原稿…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                VStack(spacing: 12) {
                    Image(systemName: "doc.text.magnifyingglass").font(.title)
                    Text("无法预览这份文件").font(.headline)
                    Text("仍可分享原稿或重新导入。")
                        .font(.subheadline).foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .background(NoteLiteTheme.paper)
        .task(id: url) {
            loading = true
            image = nil
            guard url.pathExtension.lowercased() != "pdf", !isMusicXML else {
                loading = false
                return
            }
            let result = await DocumentThumbnail.image(for: url, size: CGSize(width: 1800, height: 2400))
            guard !Task.isCancelled else { return }
            image = result
            loading = false
        }
    }
}

private enum DocumentThumbnail {
    static func image(for url: URL, size: CGSize) async -> CGImage? {
        await withCheckedContinuation { continuation in
            let request = QLThumbnailGenerator.Request(fileAt: url, size: size, scale: 1,
                                                       representationTypes: .thumbnail)
            QLThumbnailGenerator.shared.generateBestRepresentation(for: request) { representation, _ in
                continuation.resume(returning: representation?.cgImage)
            }
        }
    }
}

#if os(macOS)
private struct PDFDocumentPreview: NSViewRepresentable {
    let url: URL
    func makeNSView(context: Context) -> PDFView { configuredPDFView() }
    func updateNSView(_ view: PDFView, context: Context) {
        if view.document?.documentURL != url { view.document = PDFDocument(url: url) }
    }
}
#else
private struct PDFDocumentPreview: UIViewRepresentable {
    let url: URL
    func makeUIView(context: Context) -> PDFView { configuredPDFView() }
    func updateUIView(_ view: PDFView, context: Context) {
        if view.document?.documentURL != url { view.document = PDFDocument(url: url) }
    }
}
#endif

private func configuredPDFView() -> PDFView {
    let view = PDFView()
    view.autoScales = true
    view.displayMode = .singlePageContinuous
    view.displayDirection = .vertical
    #if os(macOS)
    view.backgroundColor = NSColor(srgbRed: 0.992, green: 0.988, blue: 0.976, alpha: 1)
    #else
    view.backgroundColor = UIColor(red: 0.992, green: 0.988, blue: 0.976, alpha: 1)
    #endif
    return view
}
