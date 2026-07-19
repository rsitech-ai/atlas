import Foundation

public struct ResearchWorkflowCheckpoint: Codable, Sendable, Equatable {
    public let workflowID: UUID
    public let queryID: UUID
    public let step: String
    public let runID: String?
    public let packetID: String?
    public let findingTaskID: String?
    public let reportID: String?
    public let detail: String
    public let updatedAt: String

    private enum CodingKeys: String, CodingKey {
        case workflowID = "workflow_id"
        case queryID = "query_id"
        case step
        case runID = "run_id"
        case packetID = "packet_id"
        case findingTaskID = "finding_task_id"
        case reportID = "report_id"
        case detail
        case updatedAt = "updated_at"
    }
}

public struct ResearchWorkflowResponse: Codable, Sendable, Equatable {
    public let checkpoint: ResearchWorkflowCheckpoint
    public let interrupted: Bool
}

public struct ResearchWorkflowAttempt: Codable, Sendable, Equatable {
    public let checkpoint: ResearchWorkflowCheckpoint
    public let title: String
}

public struct ResearchWorkflowListResponse: Codable, Sendable, Equatable {
    public let workflows: [ResearchWorkflowAttempt]
}

public struct ChunkSetSummaryDTO: Codable, Sendable, Equatable, Identifiable {
    public var id: String { chunkSetID }
    public let documentVersionID: String
    public let chunkSetID: String
    public let strategyID: String
    public let chunkCount: Int

    private enum CodingKeys: String, CodingKey {
        case documentVersionID = "document_version_id"
        case chunkSetID = "chunk_set_id"
        case strategyID = "strategy_id"
        case chunkCount = "chunk_count"
    }
}

public struct ChunkSetEvidenceDTO: Codable, Sendable, Equatable {
    public let documentVersionID: String
    public let chunkSetID: String
    public let strategyID: String
    public let chunkCount: Int
    public let chunks: [[String: JSONValue]]

    private enum CodingKeys: String, CodingKey {
        case documentVersionID = "document_version_id"
        case chunkSetID = "chunk_set_id"
        case strategyID = "strategy_id"
        case chunkCount = "chunk_count"
        case chunks
    }
}

/// Minimal JSON value for chunk payload inspection without full contract bindings.
public enum JSONValue: Codable, Sendable, Equatable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([String: JSONValue].self) {
            self = .object(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else {
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Unsupported JSON value"
            )
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case let .string(value):
            try container.encode(value)
        case let .number(value):
            try container.encode(value)
        case let .bool(value):
            try container.encode(value)
        case let .object(value):
            try container.encode(value)
        case let .array(value):
            try container.encode(value)
        case .null:
            try container.encodeNil()
        }
    }

    public var displayText: String {
        switch self {
        case let .string(value):
            value
        case let .number(value):
            String(value)
        case let .bool(value):
            value ? "true" : "false"
        case .null:
            "null"
        case .object, .array:
            "(structured)"
        }
    }
}

public struct TimelineEventDTO: Codable, Sendable, Equatable, Identifiable {
    public var id: String {
        "\(eventKind)-\(subjectID)-\(eventTime)-\(summary.prefix(24))"
    }

    public let eventKind: String
    public let subjectID: String
    public let eventTime: String
    public let summary: String
    public let observationID: String?
    public let envelopeID: String?

    private enum CodingKeys: String, CodingKey {
        case eventKind = "event_kind"
        case subjectID = "subject_id"
        case eventTime = "event_time"
        case summary
        case observationID = "observation_id"
        case envelopeID = "envelope_id"
    }
}

public struct TimelineResponseDTO: Codable, Sendable, Equatable {
    public let timeline: TimelinePayloadDTO
}

public struct TimelinePayloadDTO: Codable, Sendable, Equatable {
    public let timelineID: String
    public let subjects: [String]
    public let events: [TimelineEventDTO]
    public let asOf: String

    private enum CodingKeys: String, CodingKey {
        case timelineID = "timeline_id"
        case subjects
        case events
        case asOf = "as_of"
    }
}

public struct ObservationListResponse: Codable, Sendable, Equatable {
    public let observations: [[String: JSONValue]]
}
