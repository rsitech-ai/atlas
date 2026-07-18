import Foundation
import Testing

@testable import RSIAtlasCore

struct EngineClientTests {
    @Test
    func decodesSuccessfulLoopbackResponse() async throws {
        let expected = try fixtureStatusForClient()
        let data = try SystemStatus.encoder.encode(expected)
        let client = EngineClient { request in
            #expect(request.url == URL(string: "http://127.0.0.1:8765/v1/system/status"))
            let response = try #require(
                HTTPURLResponse(
                    url: request.url!,
                    statusCode: 200,
                    httpVersion: "HTTP/1.1",
                    headerFields: ["Content-Type": "application/json"]
                )
            )
            return (data, response)
        }

        let status = try await client.loadStatus()

        #expect(status == expected)
    }

    @Test
    func rejectsFailedHTTPResponse() async throws {
        let client = EngineClient { request in
            let response = try #require(
                HTTPURLResponse(
                    url: request.url!,
                    statusCode: 503,
                    httpVersion: "HTTP/1.1",
                    headerFields: nil
                )
            )
            return (Data(), response)
        }

        await #expect(throws: EngineClientError.httpStatus(503)) {
            try await client.loadStatus()
        }
    }
}

private func fixtureStatusForClient() throws -> SystemStatus {
    let fixtureURL = try #require(Bundle.module.url(forResource: "system_status_v1", withExtension: "json"))
    return try SystemStatus.decoder.decode(SystemStatus.self, from: Data(contentsOf: fixtureURL))
}
