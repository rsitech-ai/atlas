import Foundation

public enum HealthState: String, Codable, CaseIterable, Sendable, Equatable, Hashable {
    case healthy
    case degraded
    case blocked
    case unsafe
    case repairable
}

public enum RuntimeProfile: String, Codable, CaseIterable, Sendable, Equatable, Hashable {
    case offline
    case monitored
}

public enum ComponentGroup: String, Codable, CaseIterable, Sendable, Equatable, Hashable {
    case storage
    case privacy
    case observability
    case resources
    case engine

    public var displayName: String {
        switch self {
        case .storage: "Storage"
        case .privacy: "Privacy"
        case .observability: "Observability"
        case .resources: "Resources"
        case .engine: "Engine"
        }
    }
}

public struct ComponentSection: Identifiable, Sendable, Equatable {
    public let group: ComponentGroup
    public let components: [ComponentStatus]

    public var id: ComponentGroup { group }
    public var title: String { group.displayName }
}

public struct ComponentStatus: Codable, Identifiable, Sendable, Equatable {
    public let componentID: String
    public let title: String
    public let group: ComponentGroup
    public let state: HealthState
    public let summary: String
    public let remediation: String?

    public var id: String { componentID }

    public init(
        componentID: String,
        title: String,
        group: ComponentGroup,
        state: HealthState,
        summary: String,
        remediation: String? = nil
    ) throws {
        guard componentID.range(
            of: "^[a-z][a-z0-9_]{0,63}$",
            options: .regularExpression
        ) != nil else {
            throw StatusContractError.invalidComponentID
        }
        try Self.validateDisplayText(title, maximumLength: 80)
        try Self.validateDisplayText(summary, maximumLength: 240)
        if let remediation {
            try Self.validateDisplayText(remediation, maximumLength: 240)
        }
        self.componentID = componentID
        self.title = title
        self.group = group
        self.state = state
        self.summary = summary
        self.remediation = remediation
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case componentID = "component_id"
        case title
        case group
        case state
        case summary
        case remediation
    }

    public init(from decoder: Decoder) throws {
        try decoder.rejectUnknownKeys(allowed: CodingKeys.self)
        let container = try decoder.container(keyedBy: CodingKeys.self)
        do {
            try self.init(
                componentID: container.decode(String.self, forKey: .componentID),
                title: container.decode(String.self, forKey: .title),
                group: container.decode(ComponentGroup.self, forKey: .group),
                state: container.decode(HealthState.self, forKey: .state),
                summary: container.decode(String.self, forKey: .summary),
                remediation: container.decodeIfPresent(String.self, forKey: .remediation)
            )
        } catch let error as StatusContractError {
            throw DecodingError.dataCorrupted(
                .init(codingPath: decoder.codingPath, debugDescription: String(describing: error))
            )
        }
    }

    private static func validateDisplayText(
        _ value: String,
        maximumLength: Int
    ) throws {
        guard
            !value.isEmpty,
            value == value.trimmingCharacters(in: .whitespacesAndNewlines),
            value.count <= maximumLength,
            !value.unicodeScalars.contains(where: { scalar in
                switch scalar.properties.generalCategory {
                case .control, .format, .surrogate, .privateUse, .unassigned:
                    true
                default:
                    false
                }
            })
        else {
            throw StatusContractError.invalidDisplayText
        }
    }
}

public struct SystemStatus: Codable, Sendable, Equatable {
    private static let componentLayout: [(String, ComponentGroup)] = [
        ("engine_runtime", .engine),
        ("database", .storage),
        ("artifact_store", .storage),
        ("offline_policy", .privacy),
        ("trace_store", .observability),
        ("resource_policy", .resources),
        ("model_registry", .resources),
        ("contract_api", .engine),
    ]

    public let schemaVersion: String
    public let product: String
    public let profile: RuntimeProfile
    public let state: HealthState
    public let checkedAt: Date
    public let components: [ComponentStatus]

    public var sections: [ComponentSection] {
        ComponentGroup.allCases.compactMap { group in
            let matching = components.filter { $0.group == group }
            return matching.isEmpty ? nil : ComponentSection(group: group, components: matching)
        }
    }

    public init(
        schemaVersion: String,
        product: String,
        profile: RuntimeProfile,
        state: HealthState,
        checkedAt: Date,
        components: [ComponentStatus]
    ) throws {
        guard schemaVersion == "1.1.0" else {
            throw StatusContractError.unsupportedSchema
        }
        guard product == "RSI Atlas Engine" else {
            throw StatusContractError.unexpectedProduct
        }
        guard
            components.count == Self.componentLayout.count,
            zip(components, Self.componentLayout).allSatisfy({ component, expected in
                component.componentID == expected.0 && component.group == expected.1
            })
        else {
            throw StatusContractError.invalidComponentLayout
        }
        let expectedState = components.max {
            $0.state.severity < $1.state.severity
        }?.state
        guard state == expectedState else {
            throw StatusContractError.inconsistentState
        }
        self.schemaVersion = schemaVersion
        self.product = product
        self.profile = profile
        self.state = state
        self.checkedAt = checkedAt
        self.components = components
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case schemaVersion = "schema_version"
        case product
        case profile
        case state
        case checkedAt = "checked_at"
        case components
    }

    public init(from decoder: Decoder) throws {
        try decoder.rejectUnknownKeys(allowed: CodingKeys.self)
        let container = try decoder.container(keyedBy: CodingKeys.self)
        do {
            try self.init(
                schemaVersion: container.decode(String.self, forKey: .schemaVersion),
                product: container.decode(String.self, forKey: .product),
                profile: container.decode(RuntimeProfile.self, forKey: .profile),
                state: container.decode(HealthState.self, forKey: .state),
                checkedAt: container.decode(Date.self, forKey: .checkedAt),
                components: container.decode([ComponentStatus].self, forKey: .components)
            )
        } catch let error as StatusContractError {
            throw DecodingError.dataCorrupted(
                .init(codingPath: decoder.codingPath, debugDescription: String(describing: error))
            )
        }
    }

    public static var decoder: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let rawValue = try container.decode(String.self)
            let fractional = ISO8601DateFormatter()
            fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let date = fractional.date(from: rawValue) {
                return date
            }
            let standard = ISO8601DateFormatter()
            standard.formatOptions = [.withInternetDateTime]
            if let date = standard.date(from: rawValue) {
                return date
            }
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Invalid ISO 8601 timestamp: \(rawValue)"
            )
        }
        return decoder
    }

    public static var encoder: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .custom { date, encoder in
            var container = encoder.singleValueContainer()
            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            try container.encode(formatter.string(from: date))
        }
        return encoder
    }
}

private enum StatusContractError: Error {
    case invalidComponentID
    case invalidDisplayText
    case unsupportedSchema
    case unexpectedProduct
    case invalidComponentLayout
    case inconsistentState
}

private extension HealthState {
    var severity: Int {
        switch self {
        case .healthy: 0
        case .degraded: 1
        case .repairable: 2
        case .blocked: 3
        case .unsafe: 4
        }
    }
}

private struct AnyCodingKey: CodingKey {
    let stringValue: String
    let intValue: Int?

    init?(stringValue: String) {
        self.stringValue = stringValue
        intValue = nil
    }

    init?(intValue: Int) {
        stringValue = String(intValue)
        self.intValue = intValue
    }
}

private extension Decoder {
    func rejectUnknownKeys<Keys>(allowed: Keys.Type) throws
    where Keys: CodingKey & CaseIterable, Keys.AllCases: Collection {
        let container = try container(keyedBy: AnyCodingKey.self)
        let allowedNames = Set(allowed.allCases.map(\.stringValue))
        let unknownNames = Set(container.allKeys.map(\.stringValue)).subtracting(allowedNames)
        guard unknownNames.isEmpty else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: codingPath,
                    debugDescription: "Unknown fields: \(unknownNames.sorted().joined(separator: ", "))"
                )
            )
        }
    }
}
