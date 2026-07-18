import Foundation

public enum HealthState: String, Codable, Sendable, Equatable {
    case healthy
    case degraded
    case blocked
    case unsafe
    case repairable
}

public enum RuntimeProfile: String, Codable, Sendable, Equatable {
    case offline
    case monitored
}

public struct ComponentStatus: Codable, Identifiable, Sendable, Equatable {
    public let componentID: String
    public let title: String
    public let state: HealthState
    public let summary: String

    public var id: String { componentID }

    public init(componentID: String, title: String, state: HealthState, summary: String) {
        self.componentID = componentID
        self.title = title
        self.state = state
        self.summary = summary
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case componentID = "component_id"
        case title
        case state
        case summary
    }

    public init(from decoder: Decoder) throws {
        try decoder.rejectUnknownKeys(allowed: CodingKeys.self)
        let container = try decoder.container(keyedBy: CodingKeys.self)
        componentID = try container.decode(String.self, forKey: .componentID)
        title = try container.decode(String.self, forKey: .title)
        state = try container.decode(HealthState.self, forKey: .state)
        summary = try container.decode(String.self, forKey: .summary)
    }
}

public struct SystemStatus: Codable, Sendable, Equatable {
    public let schemaVersion: String
    public let product: String
    public let profile: RuntimeProfile
    public let state: HealthState
    public let checkedAt: Date
    public let components: [ComponentStatus]

    public init(
        schemaVersion: String,
        product: String,
        profile: RuntimeProfile,
        state: HealthState,
        checkedAt: Date,
        components: [ComponentStatus]
    ) {
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
        schemaVersion = try container.decode(String.self, forKey: .schemaVersion)
        product = try container.decode(String.self, forKey: .product)
        profile = try container.decode(RuntimeProfile.self, forKey: .profile)
        state = try container.decode(HealthState.self, forKey: .state)
        checkedAt = try container.decode(Date.self, forKey: .checkedAt)
        components = try container.decode([ComponentStatus].self, forKey: .components)

        guard schemaVersion == "1.0.0" else {
            throw DecodingError.dataCorruptedError(
                forKey: .schemaVersion,
                in: container,
                debugDescription: "Unsupported RSI Atlas status schema: \(schemaVersion)"
            )
        }
        guard product == "RSI Atlas Engine" else {
            throw DecodingError.dataCorruptedError(
                forKey: .product,
                in: container,
                debugDescription: "Unexpected status product: \(product)"
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
