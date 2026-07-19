import Foundation

public enum DocumentProcessingState: String, Codable, Sendable, Equatable {
    case idle
    case running
    case canonicalized
    case reviewRequired = "review_required"
    case failed
}

public struct DocumentProcessingStatus: Codable, Sendable, Equatable {
    public let schemaVersion: String
    public let acquisitionID: UUID
    public let state: DocumentProcessingState
    public let parseAttemptID: UUID?
    public let documentVersionID: String?
    public let canonicalContentHash: String?
    public let pageCount: Int?
    public let warnings: [String]
    public let failureCode: String?

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case schemaVersion = "schema_version"
        case acquisitionID = "acquisition_id"
        case state
        case parseAttemptID = "parse_attempt_id"
        case documentVersionID = "document_version_id"
        case canonicalContentHash = "canonical_content_hash"
        case pageCount = "page_count"
        case warnings
        case failureCode = "failure_code"
    }

    public init(from decoder: Decoder) throws {
        try decoder.rejectUnknownKeys(allowed: CodingKeys.self)
        let container = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try container.decode(String.self, forKey: .schemaVersion)
        acquisitionID = try container.decode(UUID.self, forKey: .acquisitionID)
        state = try container.decode(DocumentProcessingState.self, forKey: .state)
        parseAttemptID = try container.decodeIfPresent(UUID.self, forKey: .parseAttemptID)
        documentVersionID = try container.decodeIfPresent(String.self, forKey: .documentVersionID)
        canonicalContentHash = try container.decodeIfPresent(String.self, forKey: .canonicalContentHash)
        pageCount = try container.decodeIfPresent(Int.self, forKey: .pageCount)
        warnings = try container.decode([String].self, forKey: .warnings)
        failureCode = try container.decodeIfPresent(String.self, forKey: .failureCode)
        guard schemaVersion == "rsi-atlas.document-processing.status.v1" else {
            throw DecodingError.dataCorruptedError(
                forKey: .schemaVersion,
                in: container,
                debugDescription: "Unsupported processing status schema"
            )
        }
    }
}

public struct CanonicalPageEvidence: Decodable, Sendable, Equatable, Identifiable {
    public var id: String { "\(documentVersionID):\(pageNumber)" }
    public let schemaVersion: String
    public let documentVersionID: String
    public let pageNumber: Int
    public let rawText: String
    public let normalizedText: String
    public let elementCount: Int
    public let elements: [CanonicalPageElement]
    public let sourceArtifactDigest: String
    public let canonicalContentHash: String
    public let parserName: String
    public let parserVersion: String

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case schemaVersion = "schema_version"
        case documentVersionID = "document_version_id"
        case pageNumber = "page_number"
        case rawText = "raw_text"
        case normalizedText = "normalized_text"
        case elementCount = "element_count"
        case elements
        case sourceArtifactDigest = "source_artifact_digest"
        case canonicalContentHash = "canonical_content_hash"
        case parserName = "parser_name"
        case parserVersion = "parser_version"
    }

    public init(from decoder: Decoder) throws {
        try decoder.rejectUnknownKeys(allowed: CodingKeys.self)
        let container = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try container.decode(String.self, forKey: .schemaVersion)
        documentVersionID = try container.decode(String.self, forKey: .documentVersionID)
        pageNumber = try container.decode(Int.self, forKey: .pageNumber)
        rawText = try container.decode(String.self, forKey: .rawText)
        normalizedText = try container.decode(String.self, forKey: .normalizedText)
        elementCount = try container.decode(Int.self, forKey: .elementCount)
        elements = try container.decode([CanonicalPageElement].self, forKey: .elements)
        sourceArtifactDigest = try container.decode(String.self, forKey: .sourceArtifactDigest)
        canonicalContentHash = try container.decode(String.self, forKey: .canonicalContentHash)
        parserName = try container.decode(String.self, forKey: .parserName)
        parserVersion = try container.decode(String.self, forKey: .parserVersion)
        guard schemaVersion == "rsi-atlas.canonical-page.v1" else {
            throw DecodingError.dataCorruptedError(
                forKey: .schemaVersion,
                in: container,
                debugDescription: "Unsupported canonical page schema"
            )
        }
    }
}

public struct CanonicalPageElement: Decodable, Sendable, Equatable, Identifiable {
    public var id: String { "\(sourceSpanID):\(readingOrder)" }
    public let kind: String
    public let role: String?
    public let readingOrder: Int
    public let rawText: String
    public let normalizedText: String
    public let sourceSpanID: String
    public let rawTextHash: String
    public let normalizedTextHash: String

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case kind
        case role
        case readingOrder = "reading_order"
        case rawText = "raw_text"
        case normalizedText = "normalized_text"
        case sourceBox = "source_box"
        case normalizedBox = "normalized_box"
        case sourceSpanID = "source_span_id"
        case rawTextHash = "raw_text_hash"
        case normalizedTextHash = "normalized_text_hash"
    }

    public init(from decoder: Decoder) throws {
        try decoder.rejectUnknownKeys(allowed: CodingKeys.self)
        let container = try decoder.container(keyedBy: CodingKeys.self)
        kind = try container.decode(String.self, forKey: .kind)
        role = try container.decodeIfPresent(String.self, forKey: .role)
        readingOrder = try container.decode(Int.self, forKey: .readingOrder)
        rawText = try container.decode(String.self, forKey: .rawText)
        normalizedText = try container.decode(String.self, forKey: .normalizedText)
        _ = try container.decode([String: String].self, forKey: .sourceBox)
        _ = try container.decode([String: String].self, forKey: .normalizedBox)
        sourceSpanID = try container.decode(String.self, forKey: .sourceSpanID)
        rawTextHash = try container.decode(String.self, forKey: .rawTextHash)
        normalizedTextHash = try container.decode(String.self, forKey: .normalizedTextHash)
    }
}
