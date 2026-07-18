import Foundation
import Testing

@testable import RSIAtlasCore

struct DocumentImportStoreTests {
    @Test @MainActor
    func successfulImportPublishesDurableRecord() async throws {
        let expected = try storeAdmissionFixture()
        let store = DocumentImportStore(
            client: StubDocumentImporter(result: .success(expected))
        )
        let source = URL(fileURLWithPath: "/tmp/protocol-paper.pdf")

        await store.importPDF(source)

        #expect(store.state == .loaded(expected))
    }

    @Test @MainActor
    func staleImportCannotReplaceLatestResult() async throws {
        let firstRecord = try storeAdmissionFixture()
        let secondRecord = try storeAdmissionFixture(acquisitionID: UUID())
        let client = ControlledDocumentImporter()
        let store = DocumentImportStore(client: client)

        let first = Task { await store.importPDF(URL(fileURLWithPath: "/tmp/first.pdf")) }
        await client.waitUntilRequestCount(1)
        let second = Task { await store.importPDF(URL(fileURLWithPath: "/tmp/second.pdf")) }
        await client.waitUntilRequestCount(2)

        await client.completeRequest(at: 1, with: .success(secondRecord))
        await second.value
        await client.completeRequest(at: 0, with: .success(firstRecord))
        await first.value

        #expect(store.state == .loaded(secondRecord))
    }

    @Test @MainActor
    func failureIsSanitizedAndRetryUsesLatestSelection() async throws {
        let expected = try storeAdmissionFixture()
        let client = ControlledDocumentImporter()
        let store = DocumentImportStore(client: client)
        let source = URL(fileURLWithPath: "/private/research/protocol.pdf")

        let failed = Task { await store.importPDF(source) }
        await client.waitUntilRequestCount(1)
        await client.completeRequest(
            at: 0,
            with: .failure(DocumentImportClientError.incompatibleContract)
        )
        await failed.value

        #expect(store.state == .failed(filename: "protocol.pdf", failure: .incompatibleContract))
        #expect(String(describing: store.state).contains("/private") == false)

        let retry = Task { await store.retry() }
        await client.waitUntilRequestCount(2)
        let firstRequest = await client.request(at: 0)
        let retryRequest = await client.request(at: 1)
        #expect(retryRequest.sourceURL == firstRequest.sourceURL)
        #expect(retryRequest.acquisitionID == firstRequest.acquisitionID)
        #expect(retryRequest.traceID == firstRequest.traceID)
        await client.completeRequest(at: 1, with: .success(expected))
        await retry.value

        #expect(store.state == .loaded(expected))
    }
}

private struct StubDocumentImporter: DocumentImporting {
    let result: Result<DocumentAdmissionRecord, any Error>

    func importPDF(_ request: DocumentImportRequest) async throws -> DocumentAdmissionRecord {
        try result.get()
    }
}

private actor ControlledDocumentImporter: DocumentImporting {
    private var continuations: [CheckedContinuation<DocumentAdmissionRecord, any Error>] = []
    private var requests: [DocumentImportRequest] = []

    func importPDF(_ request: DocumentImportRequest) async throws -> DocumentAdmissionRecord {
        try await withCheckedThrowingContinuation { continuation in
            requests.append(request)
            continuations.append(continuation)
        }
    }

    func request(at index: Int) -> DocumentImportRequest {
        requests[index]
    }

    func waitUntilRequestCount(_ expectedCount: Int) async {
        while continuations.count < expectedCount {
            await Task.yield()
        }
    }

    func completeRequest(
        at index: Int,
        with result: Result<DocumentAdmissionRecord, any Error>
    ) {
        switch result {
        case let .success(record):
            continuations[index].resume(returning: record)
        case let .failure(error):
            continuations[index].resume(throwing: error)
        }
    }
}

private func storeAdmissionFixture(
    acquisitionID: UUID = UUID(uuidString: "55555555-5555-4555-8555-555555555555")!
) throws -> DocumentAdmissionRecord {
    let fixtureURL = try #require(
        Bundle.module.url(forResource: "document_admission_v1", withExtension: "json")
    )
    let data = try Data(contentsOf: fixtureURL)
    var object = try #require(
        JSONSerialization.jsonObject(with: data) as? [String: Any]
    )
    var request = try #require(object["request"] as? [String: Any])
    request["acquisition_id"] = acquisitionID.uuidString.lowercased()
    request["source_locator"] = "manual-import:\(acquisitionID.uuidString.lowercased())"
    object["request"] = request
    return try DocumentAdmissionRecord.decoder.decode(
        DocumentAdmissionRecord.self,
        from: JSONSerialization.data(withJSONObject: object)
    )
}
