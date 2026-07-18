import Foundation
import Testing

@testable import RSIAtlasCore

struct EngineClientTests {
    @Test
    func decodesSuccessfulBoundedLoopbackResponse() async throws {
        let expected = try fixtureStatusForClient()
        let data = try SystemStatus.encoder.encode(expected)
        let client = EngineClient { request in
            #expect(request.url == URL(string: "http://127.0.0.1:8765/v1/system/status"))
            #expect(request.httpMethod == "GET")
            #expect(request.timeoutInterval == 5)
            #expect(request.cachePolicy == .reloadIgnoringLocalAndRemoteCacheData)
            return (data, try response(for: request, statusCode: 200))
        }

        let status = try await client.loadStatus()

        #expect(status == expected)
    }

    @Test
    func rejectsFailedHTTPAndNonHTTPResponses() async throws {
        let failed = EngineClient { request in
            (Data(), try response(for: request, statusCode: 503))
        }
        await #expect(throws: EngineClientError.httpStatus(503)) {
            try await failed.loadStatus()
        }

        let invalid = EngineClient { request in
            (Data(), URLResponse(url: request.url!, mimeType: nil, expectedContentLength: 0, textEncodingName: nil))
        }
        await #expect(throws: EngineClientError.invalidResponse) {
            try await invalid.loadStatus()
        }
    }

    @Test
    func rejectsOversizedAndIncompatibleContractsWithTypedErrors() async throws {
        let oversized = EngineClient { request in
            (Data(repeating: 0, count: EngineClient.maximumResponseBytes + 1), try response(for: request))
        }
        await #expect(throws: EngineClientError.responseTooLarge) {
            try await oversized.loadStatus()
        }

        let invalidJSON = EngineClient { request in
            (Data("{}".utf8), try response(for: request))
        }
        await #expect(throws: EngineClientError.incompatibleContract) {
            try await invalidJSON.loadStatus()
        }
    }
}

private func response(for request: URLRequest, statusCode: Int = 200) throws -> HTTPURLResponse {
    try #require(
        HTTPURLResponse(
            url: request.url!,
            statusCode: statusCode,
            httpVersion: "HTTP/1.1",
            headerFields: ["Content-Type": "application/json"]
        )
    )
}

private func fixtureStatusForClient() throws -> SystemStatus {
    let fixtureURL = try #require(
        Bundle.module.url(forResource: "system_status_v1_1", withExtension: "json")
    )
    return try SystemStatus.decoder.decode(
        SystemStatus.self,
        from: Data(contentsOf: fixtureURL)
    )
}
