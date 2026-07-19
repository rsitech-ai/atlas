import Darwin
import Foundation

public struct LocalWorkspaceIdentity: Sendable, Equatable {
    public let tenantID: UUID
    public let workspaceID: UUID
    public let actorID: UUID

    public init(tenantID: UUID, workspaceID: UUID, actorID: UUID) {
        self.tenantID = tenantID
        self.workspaceID = workspaceID
        self.actorID = actorID
    }

    @MainActor
    public static func loadOrCreate(defaults: UserDefaults = .standard) -> Self {
        let prefix = "rsiAtlas.developmentIdentity."
        let keys = ["tenantID", "workspaceID", "actorID"].map { prefix + $0 }
        let existing = keys.compactMap { key in
            defaults.string(forKey: key).flatMap(UUID.init(uuidString:))
        }
        if existing.count == keys.count {
            return Self(tenantID: existing[0], workspaceID: existing[1], actorID: existing[2])
        }
        let created = [UUID(), UUID(), UUID()]
        for (key, identifier) in zip(keys, created) {
            defaults.set(identifier.uuidString.lowercased(), forKey: key)
        }
        return Self(tenantID: created[0], workspaceID: created[1], actorID: created[2])
    }
}

public struct DocumentImportRequest: Sendable, Equatable {
    public let sourceURL: URL
    public let acquisitionID: UUID
    public let traceID: UUID

    public init(sourceURL: URL, acquisitionID: UUID = UUID(), traceID: UUID = UUID()) {
        self.sourceURL = sourceURL
        self.acquisitionID = acquisitionID
        self.traceID = traceID
    }
}

public protocol DocumentImporting: Sendable {
    func importPDF(_ request: DocumentImportRequest) async throws -> DocumentAdmissionRecord
}

public enum DocumentImportClientError: Error, Equatable, LocalizedError, Sendable {
    case sourceMissingOrUnsafe
    case invalidPDF
    case emptyFile
    case fileTooLarge
    case sourceChanged
    case invalidResponse
    case httpStatus(Int)
    case responseTooLarge
    case incompatibleContract
    case transportUnavailable
    case authenticationFailed
    case authenticationRequired

    public var errorDescription: String? {
        switch self {
        case .sourceMissingOrUnsafe:
            "The selected source is missing, symlinked, or unsafe."
        case .invalidPDF:
            "Select one local PDF file."
        case .emptyFile:
            "The selected PDF is empty."
        case .fileTooLarge:
            "The selected PDF exceeds the 32 MB admission limit."
        case .sourceChanged:
            "The selected PDF changed while it was being uploaded."
        case .invalidResponse:
            "The local engine returned an invalid response."
        case let .httpStatus(statusCode):
            "The local engine returned HTTP \(statusCode)."
        case .responseTooLarge:
            "The local admission response exceeded the safe limit."
        case .incompatibleContract:
            "The local engine returned incompatible admission evidence."
        case .transportUnavailable:
            "The local engine could not be reached. No remote fallback was used."
        case .authenticationFailed:
            "Local engine IPC authentication failed."
        case .authenticationRequired:
            "Local engine IPC token is missing for Unix-domain transport."
        }
    }

    public static func from(_ error: LocalEngineHTTPError) -> DocumentImportClientError {
        switch error {
        case .invalidResponse:
            .invalidResponse
        case let .httpStatus(code):
            .httpStatus(code)
        case .responseTooLarge:
            .responseTooLarge
        case .transportUnavailable:
            .transportUnavailable
        case .authenticationFailed:
            .authenticationFailed
        case .authenticationRequired:
            .authenticationRequired
        }
    }
}

public struct DocumentImportClient: DocumentImporting {
    public typealias FileUploader = @Sendable (URLRequest, URL) async throws -> (Data, URLResponse)

    public static let maximumPDFBytes: Int64 = 33_554_432
    public static let maximumResponseBytes = 1_048_576
    private let configuration: LocalEngineConfiguration
    private let identity: LocalWorkspaceIdentity
    private let uploader: FileUploader

    public init(
        identity: LocalWorkspaceIdentity,
        configuration: LocalEngineConfiguration = .resolve(),
        uploader: FileUploader? = nil
    ) {
        self.identity = identity
        self.configuration = configuration
        let http = LocalEngineHTTP(configuration: configuration)
        self.uploader = uploader ?? { request, fileURL in
            try await http.uploadFile(
                request,
                fileURL: fileURL,
                maximumResponseBytes: DocumentImportClient.maximumResponseBytes
            )
        }
    }

    public func importPDF(at url: URL) async throws -> DocumentAdmissionRecord {
        try await importPDF(DocumentImportRequest(sourceURL: url))
    }

    public func importPDF(_ importRequest: DocumentImportRequest) async throws -> DocumentAdmissionRecord {
        let url = importRequest.sourceURL
        guard
            url.isFileURL,
            url.pathExtension.lowercased() == "pdf",
            url.lastPathComponent == url.lastPathComponent.precomposedStringWithCanonicalMapping,
            url.lastPathComponent.unicodeScalars.count <= 255,
            !url.lastPathComponent.unicodeScalars.contains(where: { scalar in
                switch scalar.properties.generalCategory {
                case .control, .format, .surrogate, .privateUse, .unassigned:
                    true
                default:
                    false
                }
            })
        else {
            throw DocumentImportClientError.invalidPDF
        }

        let accessed = url.startAccessingSecurityScopedResource()
        defer {
            if accessed {
                url.stopAccessingSecurityScopedResource()
            }
        }

        let descriptor = try openSource(url)
        defer { close(descriptor) }
        let initial = try sourceIdentity(descriptor: descriptor, url: url)
        guard initial.size > 0 else {
            throw DocumentImportClientError.emptyFile
        }
        guard initial.size <= Self.maximumPDFBytes else {
            throw DocumentImportClientError.fileTooLarge
        }

        let acquisitionID = importRequest.acquisitionID
        let traceID = importRequest.traceID
        var components = URLComponents(
            url: configuration.httpBaseURL,
            resolvingAgainstBaseURL: false
        )!
        components.path = "/v1/workspaces/\(identity.workspaceID.uuidString.lowercased())/documents:admit"
        components.queryItems = [
            URLQueryItem(name: "filename", value: url.lastPathComponent),
            URLQueryItem(name: "method", value: "manual_native"),
            URLQueryItem(name: "collector_version", value: "native-0.1.0"),
        ]
        guard let endpoint = components.url else {
            throw DocumentImportClientError.invalidPDF
        }
        var request = URLRequest(
            url: endpoint,
            cachePolicy: .reloadIgnoringLocalAndRemoteCacheData,
            timeoutInterval: 30
        )
        request.httpMethod = "POST"
        request.setValue("application/pdf", forHTTPHeaderField: "Content-Type")
        request.setValue(String(initial.size), forHTTPHeaderField: "Content-Length")
        request.setValue(
            identity.tenantID.uuidString.lowercased(),
            forHTTPHeaderField: "X-RSI-Tenant-ID"
        )
        request.setValue(
            identity.actorID.uuidString.lowercased(),
            forHTTPHeaderField: "X-RSI-Actor-ID"
        )
        request.setValue(
            traceID.uuidString.lowercased(),
            forHTTPHeaderField: "X-RSI-Trace-ID"
        )
        request.setValue(
            acquisitionID.uuidString.lowercased(),
            forHTTPHeaderField: "X-RSI-Acquisition-ID"
        )

        let snapshot = try createUploadSnapshot(
            descriptor: descriptor,
            sourceURL: url,
            expectedIdentity: initial
        )
        defer { snapshot.cleanup() }

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await uploader(request, snapshot.url)
        } catch is CancellationError {
            throw CancellationError()
        } catch let error as URLError where error.code == .cancelled {
            throw CancellationError()
        } catch let error as DocumentImportClientError {
            throw error
        } catch let error as LocalEngineHTTPError {
            throw DocumentImportClientError.from(error)
        } catch {
            throw DocumentImportClientError.transportUnavailable
        }
        guard let response = response as? HTTPURLResponse else {
            throw DocumentImportClientError.invalidResponse
        }
        guard 200 ..< 300 ~= response.statusCode else {
            throw DocumentImportClientError.httpStatus(response.statusCode)
        }
        guard data.count <= Self.maximumResponseBytes else {
            throw DocumentImportClientError.responseTooLarge
        }
        let record: DocumentAdmissionRecord
        do {
            record = try DocumentAdmissionRecord.decoder.decode(
                DocumentAdmissionRecord.self,
                from: data
            )
        } catch is DecodingError {
            throw DocumentImportClientError.incompatibleContract
        }
        guard
            record.context.tenantID == identity.tenantID,
            record.context.workspaceID == identity.workspaceID,
            record.context.actorID == identity.actorID,
            record.context.traceID == traceID,
            record.request.acquisitionID == acquisitionID,
            record.request.method == .manualNative,
            record.request.originalFilename == url.lastPathComponent,
            record.request.declaredMediaType == "application/pdf",
            record.request.collectorVersion == "native-0.1.0",
            record.request.networkProfile == "offline",
            Int64(record.artifact.sizeBytes) == initial.size
        else {
            throw DocumentImportClientError.incompatibleContract
        }
        return record
    }
}

private struct SourceIdentity: Equatable {
    let device: dev_t
    let inode: ino_t
    let mode: mode_t
    let links: nlink_t
    let owner: uid_t
    let size: Int64
    let modifiedSeconds: Int
    let modifiedNanoseconds: Int
    let changedSeconds: Int
    let changedNanoseconds: Int
}

private final class UploadSnapshot: @unchecked Sendable {
    let url: URL
    private let directoryPath: String

    init(url: URL, directoryPath: String) {
        self.url = url
        self.directoryPath = directoryPath
    }

    func cleanup() {
        _ = unlink(url.path)
        _ = rmdir(directoryPath)
    }
}

private func createUploadSnapshot(
    descriptor: Int32,
    sourceURL: URL,
    expectedIdentity: SourceIdentity
) throws -> UploadSnapshot {
    let temporaryRoot = canonicalTemporaryRoot()
    var directoryTemplate = Array(
        "\(temporaryRoot)/RSIAtlasDocumentImport.XXXXXX".utf8CString
    )
    guard let directoryPointer = mkdtemp(&directoryTemplate) else {
        throw DocumentImportClientError.sourceMissingOrUnsafe
    }
    let directoryPath = String(cString: directoryPointer)
    guard chmod(directoryPath, S_IRWXU) == 0 else {
        _ = rmdir(directoryPath)
        throw DocumentImportClientError.sourceMissingOrUnsafe
    }

    let snapshotURL = URL(filePath: directoryPath, directoryHint: .isDirectory)
        .appending(path: "upload.pdf")
    let destination = open(
        snapshotURL.path,
        O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC,
        S_IRUSR | S_IWUSR
    )
    guard destination >= 0 else {
        _ = rmdir(directoryPath)
        throw DocumentImportClientError.sourceMissingOrUnsafe
    }
    guard fchmod(destination, S_IRUSR | S_IWUSR) == 0 else {
        close(destination)
        _ = unlink(snapshotURL.path)
        _ = rmdir(directoryPath)
        throw DocumentImportClientError.sourceMissingOrUnsafe
    }

    do {
        var remaining = expectedIdentity.size
        var buffer = [UInt8](repeating: 0, count: 64 * 1_024)
        while remaining > 0 {
            let requested = min(buffer.count, Int(remaining))
            let count = read(descriptor, &buffer, requested)
            guard count > 0 else {
                throw DocumentImportClientError.sourceChanged
            }
            try writeAll(destination, bytes: buffer, count: count)
            remaining -= Int64(count)
        }
        var trailingByte: UInt8 = 0
        guard read(descriptor, &trailingByte, 1) == 0 else {
            throw DocumentImportClientError.sourceChanged
        }
        guard fsync(destination) == 0 else {
            throw DocumentImportClientError.sourceMissingOrUnsafe
        }
        guard try sourceIdentity(descriptor: descriptor, url: sourceURL) == expectedIdentity else {
            throw DocumentImportClientError.sourceChanged
        }
        close(destination)
        return UploadSnapshot(url: snapshotURL, directoryPath: directoryPath)
    } catch {
        close(destination)
        _ = unlink(snapshotURL.path)
        _ = rmdir(directoryPath)
        throw error
    }
}

private func writeAll(_ descriptor: Int32, bytes: [UInt8], count: Int) throws {
    var offset = 0
    while offset < count {
        let written = bytes.withUnsafeBytes { rawBuffer in
            write(descriptor, rawBuffer.baseAddress!.advanced(by: offset), count - offset)
        }
        guard written > 0 else {
            throw DocumentImportClientError.sourceMissingOrUnsafe
        }
        offset += written
    }
}

private func canonicalTemporaryRoot() -> String {
    let path = FileManager.default.temporaryDirectory.path
    if path.hasPrefix("/var/") {
        return "/private\(path)"
    }
    return path
}

private func openSource(_ url: URL) throws -> Int32 {
    let components = url.path.split(separator: "/", omittingEmptySubsequences: true)
    guard
        url.path.hasPrefix("/"),
        let leaf = components.last,
        !components.contains(where: { $0 == "." || $0 == ".." })
    else {
        throw DocumentImportClientError.sourceMissingOrUnsafe
    }

    var directoryDescriptor = open("/", O_RDONLY | O_DIRECTORY | O_CLOEXEC)
    guard directoryDescriptor >= 0 else {
        throw DocumentImportClientError.sourceMissingOrUnsafe
    }

    for component in components.dropLast() {
        let nextDescriptor = component.withCString { name in
            openat(
                directoryDescriptor,
                name,
                O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC
            )
        }
        close(directoryDescriptor)
        guard nextDescriptor >= 0 else {
            throw DocumentImportClientError.sourceMissingOrUnsafe
        }
        directoryDescriptor = nextDescriptor
    }

    let descriptor = leaf.withCString { name in
        openat(directoryDescriptor, name, O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
    }
    close(directoryDescriptor)
    guard descriptor >= 0 else {
        throw DocumentImportClientError.sourceMissingOrUnsafe
    }

    var descriptorState = stat()
    guard
        fstat(descriptor, &descriptorState) == 0,
        descriptorState.st_mode & S_IFMT == S_IFREG
    else {
        close(descriptor)
        throw DocumentImportClientError.sourceMissingOrUnsafe
    }
    return descriptor
}

private func sourceIdentity(descriptor: Int32, url: URL) throws -> SourceIdentity {
    var descriptorState = stat()
    var pathState = stat()
    guard
        fstat(descriptor, &descriptorState) == 0,
        lstat(url.path, &pathState) == 0,
        descriptorState.st_mode & S_IFMT == S_IFREG,
        pathState.st_mode & S_IFMT == S_IFREG,
        descriptorState.st_dev == pathState.st_dev,
        descriptorState.st_ino == pathState.st_ino,
        descriptorState.st_size == pathState.st_size
    else {
        throw DocumentImportClientError.sourceChanged
    }
    return SourceIdentity(
        device: descriptorState.st_dev,
        inode: descriptorState.st_ino,
        mode: descriptorState.st_mode,
        links: descriptorState.st_nlink,
        owner: descriptorState.st_uid,
        size: descriptorState.st_size,
        modifiedSeconds: descriptorState.st_mtimespec.tv_sec,
        modifiedNanoseconds: descriptorState.st_mtimespec.tv_nsec,
        changedSeconds: descriptorState.st_ctimespec.tv_sec,
        changedNanoseconds: descriptorState.st_ctimespec.tv_nsec
    )
}
