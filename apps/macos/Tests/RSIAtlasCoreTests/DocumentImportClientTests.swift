import Foundation
import Testing

@testable import RSIAtlasCore

struct DocumentImportClientTests {
    @Test @MainActor
    func localIdentityPersistsDevelopmentScopeUUIDs() throws {
        let suiteName = "DocumentImportClientTests.\(UUID())"
        let defaults = try #require(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }

        let first = LocalWorkspaceIdentity.loadOrCreate(defaults: defaults)
        let second = LocalWorkspaceIdentity.loadOrCreate(defaults: defaults)

        #expect(first == second)
        #expect(first.tenantID != first.workspaceID)
        #expect(first.workspaceID != first.actorID)
    }

    @Test
    func uploadsOneFileBackedPDFWithStrictLocalMetadata() async throws {
        let source = try temporaryPDF(named: "protocol-paper.pdf")
        defer { try? FileManager.default.removeItem(at: source.deletingLastPathComponent()) }
        let expected = try admissionFixture()
        let identity = fixtureIdentity()
        let client = DocumentImportClient(identity: identity) { request, uploadURL in
            #expect(uploadURL != source)
            #expect(try Data(contentsOf: uploadURL) == Data(contentsOf: source))
            #expect(request.httpMethod == "POST")
            #expect(request.timeoutInterval == 30)
            #expect(request.value(forHTTPHeaderField: "Content-Type") == "application/pdf")
            #expect(request.value(forHTTPHeaderField: "Content-Length") == "15")
            #expect(request.value(forHTTPHeaderField: "X-RSI-Tenant-ID") == identity.tenantID.uuidString.lowercased())
            #expect(request.value(forHTTPHeaderField: "X-RSI-Actor-ID") == identity.actorID.uuidString.lowercased())
            #expect(request.value(forHTTPHeaderField: "X-RSI-Trace-ID") != nil)
            #expect(request.value(forHTTPHeaderField: "X-RSI-Acquisition-ID") != nil)
            #expect(request.url?.absoluteString.contains("method=manual_native") == true)
            #expect(request.url?.absoluteString.contains("filename=protocol-paper.pdf") == true)
            let data = try DocumentAdmissionRecord.encoder.encode(expected)
            return (data, try httpResponse(for: request, statusCode: 200))
        }

        let record = try await client.importPDF(
            DocumentImportRequest(
                sourceURL: source,
                acquisitionID: fixtureAcquisitionID,
                traceID: fixtureTraceID
            )
        )

        #expect(record == expected)
    }

    @Test
    func uploadUsesDescriptorSnapshotDuringPathSwapAndRestore() async throws {
        let source = try temporaryPDF(named: "swap.pdf")
        let directory = source.deletingLastPathComponent()
        defer { try? FileManager.default.removeItem(at: directory) }
        let original = try Data(contentsOf: source)
        let backup = directory.appending(path: "original.pdf")
        let expected = try admissionFixture(originalFilename: "swap.pdf")
        let client = DocumentImportClient(identity: fixtureIdentity()) { request, uploadURL in
            try FileManager.default.moveItem(at: source, to: backup)
            try Data(repeating: 0x58, count: original.count).write(to: source)
            #expect(try Data(contentsOf: uploadURL) == original)
            try FileManager.default.removeItem(at: source)
            try FileManager.default.moveItem(at: backup, to: source)
            return (
                try DocumentAdmissionRecord.encoder.encode(expected),
                try httpResponse(for: request, statusCode: 200)
            )
        }

        let record = try await client.importPDF(
            DocumentImportRequest(
                sourceURL: source,
                acquisitionID: fixtureAcquisitionID,
                traceID: fixtureTraceID
            )
        )

        #expect(record == expected)
    }

    @Test
    func rejectsAValidRecordForDifferentCommandIdentity() async throws {
        let source = try temporaryPDF(named: "identity.pdf")
        defer { try? FileManager.default.removeItem(at: source.deletingLastPathComponent()) }
        let unrelated = try admissionFixture()
        let client = DocumentImportClient(identity: fixtureIdentity()) { request, _ in
            (
                try DocumentAdmissionRecord.encoder.encode(unrelated),
                try httpResponse(for: request, statusCode: 200)
            )
        }

        await #expect(throws: DocumentImportClientError.incompatibleContract) {
            try await client.importPDF(at: source)
        }
    }

    @Test
    func rejectsSymlinkNonPDFEmptyAndOversizedSourcesBeforeUpload() async throws {
        let directory = privateTemporaryDirectory()
            .appending(path: "DocumentImportClientTests-\(UUID())", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: directory) }
        let valid = directory.appending(path: "valid.pdf")
        try Data("%PDF-1.7\n%%EOF\n".utf8).write(to: valid)
        let symlink = directory.appending(path: "linked.pdf")
        try FileManager.default.createSymbolicLink(at: symlink, withDestinationURL: valid)
        let realDirectory = directory.appending(path: "real", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: realDirectory, withIntermediateDirectories: false)
        let nestedPDF = realDirectory.appending(path: "nested.pdf")
        try Data("%PDF-1.7\n%%EOF\n".utf8).write(to: nestedPDF)
        let linkedDirectory = directory.appending(path: "linked-directory", directoryHint: .isDirectory)
        try FileManager.default.createSymbolicLink(
            at: linkedDirectory,
            withDestinationURL: realDirectory
        )
        let ancestorSymlink = linkedDirectory.appending(path: "nested.pdf")
        let nonPDF = directory.appending(path: "paper.txt")
        try Data("not pdf".utf8).write(to: nonPDF)
        let empty = directory.appending(path: "empty.pdf")
        FileManager.default.createFile(atPath: empty.path, contents: Data())
        let oversized = directory.appending(path: "oversized.pdf")
        FileManager.default.createFile(atPath: oversized.path, contents: Data())
        let handle = try FileHandle(forWritingTo: oversized)
        try handle.truncate(atOffset: 33_554_433)
        try handle.close()
        let client = DocumentImportClient(identity: fixtureIdentity()) { _, _ in
            Issue.record("Uploader must not run for rejected files")
            throw StubImportError.unavailable
        }

        await #expect(throws: DocumentImportClientError.sourceMissingOrUnsafe) {
            try await client.importPDF(at: symlink)
        }
        await #expect(throws: DocumentImportClientError.sourceMissingOrUnsafe) {
            try await client.importPDF(at: ancestorSymlink)
        }
        await #expect(throws: DocumentImportClientError.invalidPDF) {
            try await client.importPDF(at: nonPDF)
        }
        await #expect(throws: DocumentImportClientError.emptyFile) {
            try await client.importPDF(at: empty)
        }
        await #expect(throws: DocumentImportClientError.fileTooLarge) {
            try await client.importPDF(at: oversized)
        }
    }

    @Test
    func sourceChangesAfterSnapshotDoNotOverrideDurableResponse() async throws {
        let source = try temporaryPDF(named: "changing.pdf")
        defer { try? FileManager.default.removeItem(at: source.deletingLastPathComponent()) }
        let expected = try admissionFixture(originalFilename: "changing.pdf")
        let client = DocumentImportClient(identity: fixtureIdentity()) { request, _ in
            try Data("changed".utf8).write(to: source)
            return (
                try DocumentAdmissionRecord.encoder.encode(expected),
                try httpResponse(for: request, statusCode: 200)
            )
        }

        let record = try await client.importPDF(
            DocumentImportRequest(
                sourceURL: source,
                acquisitionID: fixtureAcquisitionID,
                traceID: fixtureTraceID
            )
        )

        #expect(record == expected)
    }

    @Test
    func mapsHTTPContractSizeTransportAndCancellationFailures() async throws {
        let source = try temporaryPDF(named: "mapping.pdf")
        defer { try? FileManager.default.removeItem(at: source.deletingLastPathComponent()) }

        let failedHTTP = DocumentImportClient(identity: fixtureIdentity()) { request, _ in
            (Data(), try httpResponse(for: request, statusCode: 503))
        }
        await #expect(throws: DocumentImportClientError.httpStatus(503)) {
            try await failedHTTP.importPDF(at: source)
        }

        let oversized = DocumentImportClient(identity: fixtureIdentity()) { request, _ in
            (
                Data(repeating: 0, count: DocumentImportClient.maximumResponseBytes + 1),
                try httpResponse(for: request, statusCode: 200)
            )
        }
        await #expect(throws: DocumentImportClientError.responseTooLarge) {
            try await oversized.importPDF(at: source)
        }

        let incompatible = DocumentImportClient(identity: fixtureIdentity()) { request, _ in
            (Data("{}".utf8), try httpResponse(for: request, statusCode: 200))
        }
        await #expect(throws: DocumentImportClientError.incompatibleContract) {
            try await incompatible.importPDF(at: source)
        }

        let cancelled = DocumentImportClient(identity: fixtureIdentity()) { _, _ in
            throw URLError(.cancelled)
        }
        await #expect(throws: CancellationError.self) {
            try await cancelled.importPDF(at: source)
        }
    }
}

private enum StubImportError: Error {
    case unavailable
}

private func fixtureIdentity() -> LocalWorkspaceIdentity {
    LocalWorkspaceIdentity(
        tenantID: UUID(uuidString: "11111111-1111-4111-8111-111111111111")!,
        workspaceID: UUID(uuidString: "22222222-2222-4222-8222-222222222222")!,
        actorID: UUID(uuidString: "33333333-3333-4333-8333-333333333333")!
    )
}

private func temporaryPDF(named name: String) throws -> URL {
    let directory = privateTemporaryDirectory()
        .appending(path: "DocumentImportClientTests-\(UUID())", directoryHint: .isDirectory)
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
    let source = directory.appending(path: name)
    try Data("%PDF-1.7\n%%EOF\n".utf8).write(to: source)
    return source
}

private func privateTemporaryDirectory() -> URL {
    let temporaryDirectory = FileManager.default.temporaryDirectory
    guard temporaryDirectory.path.hasPrefix("/var/") else {
        return temporaryDirectory
    }
    return URL(filePath: "/private\(temporaryDirectory.path)", directoryHint: .isDirectory)
}

private let fixtureAcquisitionID = UUID(uuidString: "55555555-5555-4555-8555-555555555555")!
private let fixtureTraceID = UUID(uuidString: "44444444-4444-4444-8444-444444444444")!

private func admissionFixture(
    originalFilename: String = "protocol-paper.pdf",
    acquisitionID: UUID = fixtureAcquisitionID,
    traceID: UUID = fixtureTraceID
) throws -> DocumentAdmissionRecord {
    let fixtureURL = try #require(
        Bundle.module.url(forResource: "document_admission_v1", withExtension: "json")
    )
    var object = try #require(
        JSONSerialization.jsonObject(with: Data(contentsOf: fixtureURL)) as? [String: Any]
    )
    var context = try #require(object["context"] as? [String: Any])
    context["trace_id"] = traceID.uuidString.lowercased()
    object["context"] = context
    var request = try #require(object["request"] as? [String: Any])
    request["acquisition_id"] = acquisitionID.uuidString.lowercased()
    request["source_locator"] = "manual-import:\(acquisitionID.uuidString.lowercased())"
    request["original_filename"] = originalFilename
    object["request"] = request
    return try DocumentAdmissionRecord.decoder.decode(
        DocumentAdmissionRecord.self,
        from: JSONSerialization.data(withJSONObject: object)
    )
}

private func httpResponse(for request: URLRequest, statusCode: Int) throws -> HTTPURLResponse {
    try #require(
        HTTPURLResponse(
            url: request.url!,
            statusCode: statusCode,
            httpVersion: "HTTP/1.1",
            headerFields: ["Content-Type": "application/json"]
        )
    )
}
