import Foundation
import Testing

@testable import RSIAtlasCore

struct SystemStatusDecodingTests {
    @Test
    func decodesVersionedGroupedOfflineStatus() throws {
        let status = try decodeFixture()

        #expect(status.schemaVersion == "1.1.0")
        #expect(status.product == "RSI Atlas Engine")
        #expect(status.profile == .offline)
        #expect(status.state == .degraded)
        #expect(status.components.map(\.id) == [
            "engine_runtime",
            "database",
            "artifact_store",
            "offline_policy",
            "trace_store",
            "resource_policy",
            "model_registry",
            "contract_api",
        ])
        #expect(Set(status.components.map(\.group)) == Set(ComponentGroup.allCases))
        #expect(status.sections.map(\.title) == [
            "Storage",
            "Privacy",
            "Observability",
            "Resources",
            "Engine",
        ])
        #expect(status.sections.flatMap(\.components).count == 8)
        #expect(status.components.first(where: { $0.id == "database" })?.remediation == nil)
        #expect(
            status.components.first(where: { $0.id == "model_registry" })?.remediation
                == "Model execution remains disabled until evaluation and approval are implemented."
        )
    }

    @Test
    func rejectsUnknownTopLevelAndNestedFields() throws {
        var topLevel = try fixturePayload()
        topLevel["surprise"] = true
        #expect(throws: DecodingError.self) {
            try decode(topLevel)
        }

        var nested = try fixturePayload()
        var components = try #require(nested["components"] as? [[String: Any]])
        components[0]["remediation_action"] = "run shell"
        nested["components"] = components
        #expect(throws: DecodingError.self) {
            try decode(nested)
        }
    }

    @Test
    func rejectsUnsupportedSchemaAndUnknownGroup() throws {
        var version = try fixturePayload()
        version["schema_version"] = "1.0.0"
        #expect(throws: DecodingError.self) {
            try decode(version)
        }

        var group = try fixturePayload()
        var components = try #require(group["components"] as? [[String: Any]])
        components[0]["group"] = "network"
        group["components"] = components
        #expect(throws: DecodingError.self) {
            try decode(group)
        }
    }

    @Test
    func rejectsDuplicateComponentsAndInconsistentSeverity() throws {
        var duplicate = try fixturePayload()
        var components = try #require(duplicate["components"] as? [[String: Any]])
        components.append(components[0])
        duplicate["components"] = components
        #expect(throws: DecodingError.self) {
            try decode(duplicate)
        }

        var inconsistent = try fixturePayload()
        inconsistent["state"] = "healthy"
        #expect(throws: DecodingError.self) {
            try decode(inconsistent)
        }
    }

    @Test
    func rejectsInvalidDisplayTextAndAllowsOmittedRemediation() throws {
        var invalid = try fixturePayload()
        var components = try #require(invalid["components"] as? [[String: Any]])
        components[0]["summary"] = "runtime\nprivate"
        invalid["components"] = components
        #expect(throws: DecodingError.self) {
            try decode(invalid)
        }

        var omitted = try fixturePayload()
        components = try #require(omitted["components"] as? [[String: Any]])
        components[0].removeValue(forKey: "remediation")
        omitted["components"] = components
        let status = try decode(omitted)
        #expect(status.components[0].remediation == nil)
    }
}

private func fixtureURL() throws -> URL {
    try #require(Bundle.module.url(forResource: "system_status_v1_1", withExtension: "json"))
}

private func fixturePayload() throws -> [String: Any] {
    let data = try Data(contentsOf: fixtureURL())
    return try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
}

private func decodeFixture() throws -> SystemStatus {
    try SystemStatus.decoder.decode(SystemStatus.self, from: Data(contentsOf: fixtureURL()))
}

private func decode(_ payload: [String: Any]) throws -> SystemStatus {
    try SystemStatus.decoder.decode(
        SystemStatus.self,
        from: JSONSerialization.data(withJSONObject: payload)
    )
}
