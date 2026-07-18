import Foundation
import Testing

@testable import RSIAtlasCore

struct SystemStatusDecodingTests {
    @Test
    func decodesVersionedOfflineStatus() throws {
        let fixtureURL = try #require(Bundle.module.url(forResource: "system_status_v1", withExtension: "json"))
        let data = try Data(contentsOf: fixtureURL)

        let status = try SystemStatus.decoder.decode(SystemStatus.self, from: data)

        #expect(status.schemaVersion == "1.0.0")
        #expect(status.product == "RSI Atlas Engine")
        #expect(status.profile == .offline)
        #expect(status.state == .healthy)
        #expect(status.components.map(\.id) == ["engine_runtime", "offline_policy", "contract_api"])
    }

    @Test
    func rejectsUnknownTopLevelFields() throws {
        let fixtureURL = try #require(Bundle.module.url(forResource: "system_status_v1", withExtension: "json"))
        let data = try Data(contentsOf: fixtureURL)
        var payload = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
        payload["surprise"] = true

        #expect(throws: DecodingError.self) {
            try SystemStatus.decoder.decode(
                SystemStatus.self,
                from: JSONSerialization.data(withJSONObject: payload)
            )
        }
    }

    @Test
    func rejectsUnsupportedSchemaVersions() throws {
        let fixtureURL = try #require(Bundle.module.url(forResource: "system_status_v1", withExtension: "json"))
        let data = try Data(contentsOf: fixtureURL)
        var payload = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
        payload["schema_version"] = "2.0.0"

        #expect(throws: DecodingError.self) {
            try SystemStatus.decoder.decode(
                SystemStatus.self,
                from: JSONSerialization.data(withJSONObject: payload)
            )
        }
    }
}
