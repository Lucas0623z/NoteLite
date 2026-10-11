import Foundation
import WebKit

/// Only resources from the installed Figma bundle are served at this local origin.
final class FigmaResourceHandler: NSObject, WKURLSchemeHandler {
    static let scheme = "notelite-ui"
    static let host = "app"
    private let root: URL

    init(root: URL) { self.root = root.standardizedFileURL.resolvingSymlinksInPath() }

    static func isTrusted(_ url: URL?) -> Bool {
        guard let url else { return false }
        return url.scheme == scheme && url.host == host && url.user == nil && url.password == nil && url.port == nil
    }

    func webView(_ webView: WKWebView, start urlSchemeTask: WKURLSchemeTask) {
        do {
            guard let url = urlSchemeTask.request.url, Self.isTrusted(url),
                  urlSchemeTask.request.httpMethod == "GET" || urlSchemeTask.request.httpMethod == nil else {
                throw URLError(.unsupportedURL)
            }
            let relative = url.path == "/" ? "index.html" : String(url.path.dropFirst())
            let target = try Self.resource(relativePath: relative, root: root)
            let data = try Data(contentsOf: target, options: .mappedIfSafe)
            // Custom schemes can have an opaque WebKit origin. Local module/font
            // requests need an explicit CORS response; no server credentials are served here.
            let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1", headerFields: [
                "Content-Type": Self.mimeType(target.pathExtension),
                "Content-Length": String(data.count),
                "Access-Control-Allow-Origin": "*",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src notelite-ui: data: blob:; script-src notelite-ui:; style-src notelite-ui: 'unsafe-inline'; font-src notelite-ui: data:; img-src notelite-ui: data: blob:; connect-src notelite-ui:; frame-src blob:; object-src 'none'; base-uri 'none'"
            ])!
            urlSchemeTask.didReceive(response)
            urlSchemeTask.didReceive(data)
            urlSchemeTask.didFinish()
        } catch { urlSchemeTask.didFailWithError(error) }
    }

    func webView(_ webView: WKWebView, stop urlSchemeTask: WKURLSchemeTask) {}

    static func resource(relativePath: String, root: URL) throws -> URL {
        guard !relativePath.isEmpty, !relativePath.hasPrefix("/"), !relativePath.contains("\\"),
              !relativePath.split(separator: "/", omittingEmptySubsequences: false).contains(where: { $0 == ".." || $0 == "." }),
              !relativePath.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) }) else {
            throw URLError(.noPermissionsToReadFile)
        }
        let normalizedRoot = root.standardizedFileURL.resolvingSymlinksInPath()
        let target = normalizedRoot.appendingPathComponent(relativePath).standardizedFileURL.resolvingSymlinksInPath()
        guard target.path.hasPrefix(normalizedRoot.path + "/"),
              (try target.resourceValues(forKeys: [.isRegularFileKey])).isRegularFile == true else {
            throw URLError(.noPermissionsToReadFile)
        }
        return target
    }

    private static func mimeType(_ ext: String) -> String {
        switch ext.lowercased() {
        case "html": return "text/html"
        case "js", "mjs": return "text/javascript"
        case "css": return "text/css"
        case "json": return "application/json"
        case "svg": return "image/svg+xml"
        case "png": return "image/png"
        case "jpg", "jpeg": return "image/jpeg"
        case "webp": return "image/webp"
        case "gif": return "image/gif"
        case "woff": return "font/woff"
        case "woff2": return "font/woff2"
        case "ttf": return "font/ttf"
        case "otf": return "font/otf"
        case "pdf": return "application/pdf"
        case "xml", "musicxml": return "application/vnd.recordare.musicxml+xml"
        default: return "application/octet-stream"
        }
    }
}
