import Foundation
import Combine

@MainActor
final class LibraryStore: ObservableObject {
    @Published private(set) var records: [ScoreRecord] = []
    @Published private(set) var uploadProgress: [UUID: Double] = [:]
    @Published private(set) var serverAddress: String
    @Published private(set) var activeIDs: Set<UUID> = []
    @Published private(set) var isImporting = false
    @Published var errorMessage: String?

    private struct Worker {
        let generation: UUID
        let task: Task<Void, Never>
    }
    private var workers: [UUID: Worker] = [:]
    private var storage: DocumentStorage?
    private let defaults: UserDefaults
    private let localRecognizer: any EmbeddedRecognizing
    private static let serverKey = "NoteLite.serverURL"

    init(defaults: UserDefaults = .standard, storageRoot: URL? = nil,
         localRecognizer: any EmbeddedRecognizing = EmbeddedRecognitionService.shared) {
        self.defaults = defaults
        self.localRecognizer = localRecognizer
        serverAddress = defaults.string(forKey: Self.serverKey) ?? ""
        do {
            let storage = try DocumentStorage(root: storageRoot)
            var loaded = try storage.load()
            // A POST interrupted before its response cannot be resumed without risking a duplicate.
            for index in loaded.indices where loaded[index].phase == .uploading {
                loaded[index].phase = .imported
                loaded[index].paused = true
                loaded[index].lastError = "上次上传已中断。服务器可能已接收文件，重新识别可能创建另一项任务。"
            }
            for index in loaded.indices where loaded[index].recognitionLocation == .device &&
                [.queued, .running, .downloading].contains(loaded[index].phase) {
                loaded[index].phase = .imported
                loaded[index].paused = true
                loaded[index].lastError = "上次本地识谱已中断，可以重新开始。"
            }
            try storage.save(loaded)
            self.storage = storage
            records = loaded
        } catch {
            // Do not overwrite an unreadable manifest with an empty library.
            errorMessage = "无法读取本地乐谱库：\(error.localizedDescription)"
        }
    }

    var canImport: Bool { storage != nil && !isImporting }
    var isConfigured: Bool { (try? ServerConfiguration(serverAddress)) != nil }
    var hasLocalEngine: Bool {
        #if os(iOS) && !EMBEDDED_OMR_RUNTIME
        // The default mobile client uses cloud OMR. Explicit legacy runtime
        // builds retain their offline acceptance route; audio remains local.
        return false
        #else
        return localRecognizer.isAvailable
        #endif
    }
    var canRecognize: Bool { hasLocalEngine || isConfigured }

    func record(_ id: UUID) -> ScoreRecord? { records.first { $0.id == id } }

    func saveConfiguration(address: String, token: String) throws {
        let configuration = try ServerConfiguration(address)
        try TokenStore.save(token, for: configuration)
        serverAddress = configuration.key
        defaults.set(configuration.key, forKey: Self.serverKey)
    }

    func storedToken() -> String {
        guard let configuration = try? ServerConfiguration(serverAddress) else { return "" }
        do { return try TokenStore.read(for: configuration) }
        catch { errorMessage = error.localizedDescription; return "" }
    }

    @discardableResult
    func importFiles(_ urls: [URL]) async -> UUID? {
        guard let storage, !isImporting else { return nil }
        isImporting = true
        defer { isImporting = false }
        var firstID: UUID?
        var errors: [String] = []
        for url in urls {
            do {
                // Files providers may hydrate an iCloud file here; never block the UI actor.
                let record = try await Task.detached(priority: .userInitiated) {
                    try storage.importFile(url)
                }.value
                do {
                    let updated = [record] + records
                    try storage.save(updated)
                    records = updated
                    firstID = firstID ?? record.id
                } catch {
                    try? storage.remove(record)
                    throw error
                }
            } catch {
                errors.append("\(url.lastPathComponent)：\(error.localizedDescription)")
            }
        }
        if !errors.isEmpty { errorMessage = errors.joined(separator: "\n") }
        return firstID
    }

    func sourceURL(_ record: ScoreRecord) -> URL? { storage?.sourceURL(for: record) }

    func practiceURL(_ record: ScoreRecord) -> URL? {
        practiceParts(record).first?.url
    }

    func practiceParts(_ record: ScoreRecord) -> [PracticePart] {
        if record.isMusicXML {
            guard let url = sourceURL(record), FileManager.default.fileExists(atPath: url.path) else { return [] }
            return [PracticePart(artifactName: nil, url: url, title: nil)]
        }
        let files = Set(record.downloadedArtifacts).filter {
            FileRules.musicXMLExtensions.contains(($0 as NSString).pathExtension.lowercased())
        }.sorted {
            $0.compare($1, options: [.numeric, .caseInsensitive], locale: Locale(identifier: "en_US_POSIX")) == .orderedAscending
        }.compactMap { name -> (String, URL)? in
            artifactURL(name, record: record).map { (name, $0) }
        }
        return files.enumerated().map { index, file in
            PracticePart(artifactName: file.0, url: file.1,
                         title: files.count > 1 ? "第 \(index + 1) 部分" : nil)
        }
    }

    func practicePart(_ record: ScoreRecord, artifactName: String?) -> PracticePart? {
        let parts = practiceParts(record)
        // Old history predates part identity and always opened the first score.
        if record.isMusicXML { return artifactName == nil ? parts.first : nil }
        let name = artifactName ?? record.downloadedArtifacts.sorted().first {
            FileRules.musicXMLExtensions.contains(($0 as NSString).pathExtension.lowercased())
        }
        return parts.first { $0.artifactName == name }
    }

    #if DEBUG
    /// UI navigation tests provide real desktop exports without running OMR.
    /// This import route and its launch argument do not exist in Release builds.
    func importPracticeUITestFixture(_ data: Data) async {
        struct Fixture: Decodable {
            struct Artifact: Decodable { let name: String; let data: Data }
            let source: Data
            let artifacts: [Artifact]
        }
        let filename = "多部分练习样本.png"
        guard let storage, !records.contains(where: { $0.filename == filename }) else { return }
        do {
            let fixture = try JSONDecoder().decode(Fixture.self, from: data)
            let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            defer { try? FileManager.default.removeItem(at: directory) }
            let source = directory.appendingPathComponent(filename)
            try fixture.source.write(to: source)
            guard let id = await importFiles([source]), let record = self.record(id) else { return }
            let artifacts = fixture.artifacts.map { EmbeddedArtifact(name: $0.name, data: $0.data) }
            try storage.installEmbeddedArtifacts(artifacts, for: record)
            try update(id) {
                $0.downloadedArtifacts = artifacts.map(\.name)
                $0.phase = .ready
            }
        } catch { errorMessage = "无法载入练习测试样本：\(error.localizedDescription)" }
    }
    #endif

    func artifactURL(_ name: String, record: ScoreRecord) -> URL? {
        guard let url = try? storage?.artifactURL(name: name, for: record),
              FileManager.default.fileExists(atPath: url.path) else { return nil }
        return url
    }

    func start(_ id: UUID, newJob: Bool = false) {
        guard let storage, let record = record(id), workers[id] == nil else { return }
        // Structured scores can be practised directly and must not be sent to the image recognizer.
        guard !record.isMusicXML else { return }
        if hasLocalEngine && record.job == nil {
            startLocal(id, storage: storage)
            return
        }
        do {
            // Existing tasks stay attached to their original server and that server's Keychain token.
            let address = !newJob && record.job != nil ? (record.serverURL ?? serverAddress) : serverAddress
            let configuration = try ServerConfiguration(address)
            let token = try TokenStore.read(for: configuration)
            guard !token.isEmpty else { throw NoteLiteError.missingToken }
            let api = NoteLiteAPI(configuration: configuration, token: token)
            try update(id) { value in
                value.lastError = nil
                value.paused = false
                if value.job == nil {
                    value.prepareForUpload(serverURL: configuration.key)
                }
            }
            let generation = UUID()
            let task = Task { [weak self] in
                guard let self else { return }
                await self.process(id, generation: generation, api: api, storage: storage,
                                   restart: newJob || record.job?.state == .failed)
            }
            workers[id] = Worker(generation: generation, task: task)
            activeIDs.insert(id)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func pause(_ id: UUID, userInitiated: Bool = true) {
        workers.removeValue(forKey: id)?.task.cancel()
        activeIDs.remove(id)
        uploadProgress.removeValue(forKey: id)
        do {
            try update(id) { value in
                if value.recognitionLocation == .device {
                    value.phase = .imported
                    value.paused = true
                    value.lastError = userInitiated ? "本地识谱已停止；正在执行的图像处理会在安全结束后释放。" : "本地识谱已中断，可以重新开始。"
                } else if value.phase == .uploading {
                    value.phase = .imported
                    value.paused = true
                    value.lastError = "上传已中断。服务器可能已接收文件，重新识别可能创建另一项任务。"
                } else if userInitiated {
                    value.paused = true
                }
            }
        } catch { errorMessage = error.localizedDescription }
    }

    func suspendForBackground() {
        for id in Array(workers.keys) { pause(id, userInitiated: false) }
    }

    func resumePending() {
        for record in records where !record.paused && record.job != nil {
            if [.queued, .running, .downloading].contains(record.phase) { start(record.id) }
        }
    }

    func delete(_ id: UUID) { cleanServerJob(id, deleteLocal: true) }

    func cleanServerJob(_ id: UUID, deleteLocal: Bool = false) {
        guard record(id) != nil, let storage else { return }
        pause(id)
        let generation = UUID()
        let task = Task { [weak self] in
            guard let self else { return }
            defer {
                if self.workers[id]?.generation == generation {
                    self.workers.removeValue(forKey: id)
                    self.activeIDs.remove(id)
                }
            }
            do {
                guard let record = self.record(id) else { return }
                if let job = record.job {
                    let api = try self.apiForSavedJob(record)
                    try await api.deleteJob(job.id)
                    try self.ensureCurrent(id, generation: generation)
                }
                if deleteLocal {
                    let remaining = self.records.filter { $0.id != id }
                    try storage.save(remaining)
                    self.records = remaining
                    try storage.remove(record)
                } else {
                    try self.update(id) {
                        $0.job = nil
                        $0.serverURL = nil
                        $0.phase = $0.downloadedArtifacts.isEmpty ? .imported : .ready
                        $0.lastError = nil
                        $0.paused = false
                    }
                }
            } catch {
                if !Task.isCancelled { self.errorMessage = "清理失败，本地记录已保留：\(error.localizedDescription)" }
            }
        }
        workers[id] = Worker(generation: generation, task: task)
        activeIDs.insert(id)
    }

    private func startLocal(_ id: UUID, storage: DocumentStorage) {
        do {
            try update(id) { $0.prepareForLocalRecognition() }
            let generation = UUID()
            let task = Task { [weak self] in
                guard let self else { return }
                defer {
                    if self.workers[id]?.generation == generation {
                        self.workers.removeValue(forKey: id)
                        self.activeIDs.remove(id)
                    }
                }
                do {
                    guard let initial = self.record(id) else { return }
                    let artifacts = try await self.localRecognizer.recognize(source: storage.sourceURL(for: initial))
                    try self.ensureCurrent(id, generation: generation)
                    // Native engine exports are owned by this job; persist them before marking ready.
                    try storage.installEmbeddedArtifacts(artifacts, for: initial)
                    try self.update(id) {
                        $0.downloadedArtifacts = artifacts.map(\.name)
                        $0.phase = .ready
                        $0.paused = false
                        $0.lastError = nil
                    }
                } catch {
                    guard self.workers[id]?.generation == generation, !Task.isCancelled else { return }
                    do {
                        try self.update(id) { $0.phase = .failed; $0.lastError = error.localizedDescription }
                    } catch { self.errorMessage = "无法保存本地识谱状态：\(error.localizedDescription)" }
                }
            }
            workers[id] = Worker(generation: generation, task: task)
            activeIDs.insert(id)
        } catch { errorMessage = error.localizedDescription }
    }

    private func process(_ id: UUID, generation: UUID, api: NoteLiteAPI,
                         storage: DocumentStorage, restart: Bool) async {
        defer {
            if workers[id]?.generation == generation {
                workers.removeValue(forKey: id)
                activeIDs.remove(id)
                uploadProgress.removeValue(forKey: id)
            }
        }
        do {
            if restart, let previous = record(id), let oldJob = previous.job {
                let oldAPI = try apiForSavedJob(previous)
                try await oldAPI.deleteJob(oldJob.id)
                try ensureCurrent(id, generation: generation)
                try update(id) {
                    $0.prepareForUpload(serverURL: api.configuration.key)
                }
            }
            guard let initial = record(id) else { return }
            var job: RemoteJob
            if let existing = initial.job {
                job = existing
            } else {
                job = try await api.upload(file: storage.sourceURL(for: initial), filename: initial.filename) { [weak self] progress in
                    Task { @MainActor in
                        guard let self, self.workers[id]?.generation == generation else { return }
                        self.uploadProgress[id] = progress
                    }
                }
                try ensureCurrent(id, generation: generation)
                try update(id) { $0.job = job }
            }

            while true {
                try ensureCurrent(id, generation: generation)
                switch job.state {
                case .queued, .running:
                    try update(id) {
                        $0.job = job
                        $0.phase = job.state == .queued ? .queued : .running
                    }
                    try await Task.sleep(nanoseconds: 2_000_000_000)
                    job = try await api.job(job.id)
                case .failed:
                    try update(id) { $0.job = job }
                    throw NoteLiteError.server(job.error ?? "识谱失败，请检查乐谱是否清晰后重试。")
                case .succeeded:
                    try CloudResultValidation.validateManifest(job.artifacts)
                    try update(id) { $0.job = job; $0.phase = .downloading }
                    var totalBytes = 0
                    for artifact in job.artifacts {
                        try ensureCurrent(id, generation: generation)
                        guard let current = record(id) else { return }
                        let destination = try storage.artifactURL(name: artifact.name, for: current)
                        if !current.downloadedArtifacts.contains(artifact.name) ||
                            !FileManager.default.fileExists(atPath: destination.path) {
                            try await api.download(artifact, jobID: job.id, to: destination,
                                                   maximumBytes: CloudResultValidation.maximumJobBytes - totalBytes)
                            try ensureCurrent(id, generation: generation)
                            try update(id) {
                                if !$0.downloadedArtifacts.contains(artifact.name) {
                                    $0.downloadedArtifacts.append(artifact.name)
                                }
                            }
                        }
                        let size = try CloudResultValidation.validateArtifact(at: destination)
                        totalBytes += size
                        guard totalBytes <= CloudResultValidation.maximumJobBytes else {
                            throw NoteLiteError.server("识谱结果总大小超过 32 MiB，请减少页数后重试。")
                        }
                    }
                    guard let completed = record(id), !practiceParts(completed).isEmpty else {
                        throw NoteLiteError.server("服务器没有提供可练习的 MusicXML 乐谱。")
                    }
                    // Persist a usable local copy before requesting remote deletion.
                    try update(id) { $0.phase = .ready; $0.lastError = nil; $0.paused = false }
                    #if os(iOS)
                    do {
                        try await api.deleteJob(job.id)
                        try ensureCurrent(id, generation: generation)
                        try update(id) { $0.job = nil; $0.serverURL = nil }
                    } catch {
                        try ensureCurrent(id, generation: generation)
                        try update(id) {
                            $0.lastError = "结果已保存，可离线练习；云端任务清理失败，请稍后重试清理：\(error.localizedDescription)"
                        }
                    }
                    #endif
                    return
                }
            }
        } catch {
            guard workers[id]?.generation == generation, !Task.isCancelled else { return }
            do {
                try update(id) {
                    let wasUploading = $0.phase == .uploading
                    $0.phase = .failed
                    $0.lastError = error.localizedDescription + (wasUploading
                        ? " 上传未确认完成，服务器可能已收到文件；重试可能创建另一项任务。" : "")
                }
            } catch { errorMessage = "无法保存任务状态：\(error.localizedDescription)" }
        }
    }

    private func ensureCurrent(_ id: UUID, generation: UUID) throws {
        try Task.checkCancellation()
        guard workers[id]?.generation == generation else { throw CancellationError() }
    }

    private func apiForSavedJob(_ record: ScoreRecord) throws -> NoteLiteAPI {
        guard let address = record.serverURL else { throw NoteLiteError.invalidServer }
        let configuration = try ServerConfiguration(address)
        let token = try TokenStore.read(for: configuration)
        guard !token.isEmpty else { throw NoteLiteError.missingToken }
        return NoteLiteAPI(configuration: configuration, token: token)
    }

    private func update(_ id: UUID, change: (inout ScoreRecord) -> Void) throws {
        guard let index = records.firstIndex(where: { $0.id == id }), let storage else { return }
        var updated = records
        change(&updated[index])
        try storage.save(updated)
        records = updated
    }
}
