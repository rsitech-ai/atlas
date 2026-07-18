import Foundation

public enum AcquisitionMethod: String, Codable, Sendable, Equatable {
    case manualNative = "manual_native"
    case manualCLI = "manual_cli"
    case localAPI = "local_api"
}

public enum DocumentLifecycle: String, Codable, Sendable, Equatable {
    case quarantined
    case awaitingReview = "awaiting_review"
    case awaitingPassword = "awaiting_password"
    case rejected
    case duplicate
}

public enum AdmissionOutcome: String, Codable, Sendable, Equatable {
    case accept
    case acceptWithRestrictions = "accept_with_restrictions"
    case requestPassword = "request_password"
    case quarantineForReview = "quarantine_for_review"
    case rejectPolicyViolation = "reject_policy_violation"
    case rejectUnsafe = "reject_unsafe"
    case markExactDuplicate = "mark_exact_duplicate"
    case registerNewVersion = "register_new_version"
}

public enum SafetyCheckState: String, Codable, Sendable, Equatable {
    case pass
    case fail
    case unknown
}

public struct AdmissionCommandContext: Codable, Sendable, Equatable {
    public let tenantID: UUID
    public let workspaceID: UUID
    public let actorID: UUID
    public let traceID: UUID

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case tenantID = "tenant_id"
        case workspaceID = "workspace_id"
        case actorID = "actor_id"
        case traceID = "trace_id"
    }

    public init(from decoder: Decoder) throws {
        try decoder.rejectUnknownKeys(allowed: CodingKeys.self)
        let container = try decoder.container(keyedBy: CodingKeys.self)
        tenantID = try container.decode(UUID.self, forKey: .tenantID)
        workspaceID = try container.decode(UUID.self, forKey: .workspaceID)
        actorID = try container.decode(UUID.self, forKey: .actorID)
        traceID = try container.decode(UUID.self, forKey: .traceID)
    }
}

public struct DocumentAcquisitionRequest: Codable, Sendable, Equatable {
    public let schemaVersion: String
    public let acquisitionID: UUID
    public let method: AcquisitionMethod
    public let originalFilename: String
    public let sourceLocator: String
    public let declaredMediaType: String
    public let collectorVersion: String
    public let networkProfile: String

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case schemaVersion = "schema_version"
        case acquisitionID = "acquisition_id"
        case method
        case originalFilename = "original_filename"
        case sourceLocator = "source_locator"
        case declaredMediaType = "declared_media_type"
        case collectorVersion = "collector_version"
        case networkProfile = "network_profile"
    }

    public init(from decoder: Decoder) throws {
        try decoder.rejectUnknownKeys(allowed: CodingKeys.self)
        let container = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try container.decode(String.self, forKey: .schemaVersion)
        acquisitionID = try container.decode(UUID.self, forKey: .acquisitionID)
        method = try container.decode(AcquisitionMethod.self, forKey: .method)
        originalFilename = try container.decode(String.self, forKey: .originalFilename)
        sourceLocator = try container.decode(String.self, forKey: .sourceLocator)
        declaredMediaType = try container.decode(String.self, forKey: .declaredMediaType)
        collectorVersion = try container.decode(String.self, forKey: .collectorVersion)
        networkProfile = try container.decode(String.self, forKey: .networkProfile)
        try validate(decoder: decoder)
    }

    private func validate(decoder: Decoder) throws {
        guard schemaVersion == "1.0.0" else {
            throw contractError(decoder, "Unsupported acquisition schema")
        }
        guard
            originalFilename == originalFilename.precomposedStringWithCanonicalMapping,
            originalFilename.unicodeScalars.count <= 255,
            originalFilename != ".",
            originalFilename != "..",
            !originalFilename.contains("/"),
            !originalFilename.contains("\\"),
            originalFilename.lowercased().hasSuffix(".pdf"),
            isSafeContractText(originalFilename)
        else {
            throw contractError(decoder, "Invalid original filename")
        }
        guard sourceLocator == "manual-import:\(acquisitionID.uuidString.lowercased())" else {
            throw contractError(decoder, "Acquisition source locator is inconsistent")
        }
        guard declaredMediaType == "application/pdf", networkProfile == "offline" else {
            throw contractError(decoder, "Unsupported acquisition boundary")
        }
        guard collectorVersion.range(
            of: "^[a-z0-9][a-z0-9._-]{0,63}$",
            options: .regularExpression
        ) != nil else {
            throw contractError(decoder, "Invalid collector version")
        }
    }
}

public struct DocumentArtifactDescriptor: Codable, Sendable, Equatable {
    public let schemaVersion: String
    public let artifactID: String
    public let algorithm: String
    public let digest: String
    public let sizeBytes: Int
    public let mediaType: String

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case schemaVersion = "schema_version"
        case artifactID = "artifact_id"
        case algorithm
        case digest
        case sizeBytes = "size_bytes"
        case mediaType = "media_type"
    }

    public init(from decoder: Decoder) throws {
        try decoder.rejectUnknownKeys(allowed: CodingKeys.self)
        let container = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try container.decode(String.self, forKey: .schemaVersion)
        artifactID = try container.decode(String.self, forKey: .artifactID)
        algorithm = try container.decode(String.self, forKey: .algorithm)
        digest = try container.decode(String.self, forKey: .digest)
        sizeBytes = try container.decode(Int.self, forKey: .sizeBytes)
        mediaType = try container.decode(String.self, forKey: .mediaType)
        guard
            schemaVersion == "1.0.0",
            algorithm == "sha256",
            digest.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil,
            artifactID == "sha256:\(digest)",
            1 ... 33_554_432 ~= sizeBytes,
            mediaType == "application/pdf"
        else {
            throw contractError(decoder, "Invalid immutable artifact descriptor")
        }
    }
}

public struct PDFSafetyProfile: Codable, Sendable, Equatable {
    public let schemaVersion: String
    public let policyVersion: String
    public let artifactID: String
    public let digest: String
    public let sizeBytes: Int
    public let headerVersion: String?
    public let eofMarkerPresent: Bool
    public let pageMarkerCount: Int?
    public let mimeSignatureConsistency: SafetyCheckState
    public let sizeLimit: SafetyCheckState
    public let pageCountLimit: SafetyCheckState
    public let encryptionPasswordState: SafetyCheckState
    public let malformedStructure: SafetyCheckState
    public let embeddedFiles: SafetyCheckState
    public let activeActions: SafetyCheckState
    public let suspiciousReferences: SafetyCheckState
    public let decompressionRatio: SafetyCheckState
    public let sourcePolicy: SafetyCheckState
    public let availableDisk: SafetyCheckState
    public let inspectedAt: Date

    public var checks: [DocumentSafetyCheck] {
        [
            .init(id: "mime_signature", title: "PDF signature", state: mimeSignatureConsistency),
            .init(id: "size_limit", title: "File size", state: sizeLimit),
            .init(id: "page_count", title: "Page count", state: pageCountLimit),
            .init(id: "encryption", title: "Encryption", state: encryptionPasswordState),
            .init(id: "structure", title: "Document structure", state: malformedStructure),
            .init(id: "embedded_files", title: "Embedded files", state: embeddedFiles),
            .init(id: "active_actions", title: "Active actions", state: activeActions),
            .init(id: "references", title: "External references", state: suspiciousReferences),
            .init(id: "decompression", title: "Decompression ratio", state: decompressionRatio),
            .init(id: "source_policy", title: "Source policy", state: sourcePolicy),
            .init(id: "available_disk", title: "Available disk", state: availableDisk),
        ]
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case schemaVersion = "schema_version"
        case policyVersion = "policy_version"
        case artifactID = "artifact_id"
        case digest
        case sizeBytes = "size_bytes"
        case headerVersion = "header_version"
        case eofMarkerPresent = "eof_marker_present"
        case pageMarkerCount = "page_marker_count"
        case mimeSignatureConsistency = "mime_signature_consistency"
        case sizeLimit = "size_limit"
        case pageCountLimit = "page_count_limit"
        case encryptionPasswordState = "encryption_password_state"
        case malformedStructure = "malformed_structure"
        case embeddedFiles = "embedded_files"
        case activeActions = "active_actions"
        case suspiciousReferences = "suspicious_references"
        case decompressionRatio = "decompression_ratio"
        case sourcePolicy = "source_policy"
        case availableDisk = "available_disk"
        case inspectedAt = "inspected_at"
    }

    public init(from decoder: Decoder) throws {
        try decoder.rejectUnknownKeys(allowed: CodingKeys.self)
        let container = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try container.decode(String.self, forKey: .schemaVersion)
        policyVersion = try container.decode(String.self, forKey: .policyVersion)
        artifactID = try container.decode(String.self, forKey: .artifactID)
        digest = try container.decode(String.self, forKey: .digest)
        sizeBytes = try container.decode(Int.self, forKey: .sizeBytes)
        headerVersion = try container.decodeIfPresent(String.self, forKey: .headerVersion)
        eofMarkerPresent = try container.decode(Bool.self, forKey: .eofMarkerPresent)
        pageMarkerCount = try container.decodeIfPresent(Int.self, forKey: .pageMarkerCount)
        mimeSignatureConsistency = try container.decode(
            SafetyCheckState.self,
            forKey: .mimeSignatureConsistency
        )
        sizeLimit = try container.decode(SafetyCheckState.self, forKey: .sizeLimit)
        pageCountLimit = try container.decode(SafetyCheckState.self, forKey: .pageCountLimit)
        encryptionPasswordState = try container.decode(
            SafetyCheckState.self,
            forKey: .encryptionPasswordState
        )
        malformedStructure = try container.decode(
            SafetyCheckState.self,
            forKey: .malformedStructure
        )
        embeddedFiles = try container.decode(SafetyCheckState.self, forKey: .embeddedFiles)
        activeActions = try container.decode(SafetyCheckState.self, forKey: .activeActions)
        suspiciousReferences = try container.decode(
            SafetyCheckState.self,
            forKey: .suspiciousReferences
        )
        decompressionRatio = try container.decode(
            SafetyCheckState.self,
            forKey: .decompressionRatio
        )
        sourcePolicy = try container.decode(SafetyCheckState.self, forKey: .sourcePolicy)
        availableDisk = try container.decode(SafetyCheckState.self, forKey: .availableDisk)
        inspectedAt = try decodeContractDate(container, forKey: .inspectedAt)
        try validate(decoder: decoder)
    }

    private func validate(decoder: Decoder) throws {
        guard
            schemaVersion == "1.0.0",
            policyVersion == "phase-2a-1",
            digest.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil,
            artifactID == "sha256:\(digest)",
            1 ... 33_554_432 ~= sizeBytes,
            headerVersion == nil || headerVersion?.range(
                of: "^1\\.[0-7]$",
                options: .regularExpression
            ) != nil,
            pageMarkerCount == nil || 0 ... 2_001 ~= pageMarkerCount!
        else {
            throw contractError(decoder, "Invalid PDF safety profile")
        }
        if mimeSignatureConsistency == .pass, headerVersion == nil {
            throw contractError(decoder, "Passing signature evidence lacks a PDF header")
        }
        if malformedStructure == .pass, headerVersion == nil || !eofMarkerPresent {
            throw contractError(decoder, "Passing structure evidence is incomplete")
        }
        if pageCountLimit == .pass,
           pageMarkerCount == nil || !(1 ... 2_000 ~= pageMarkerCount!)
        {
            throw contractError(decoder, "Passing page-count evidence is inconsistent")
        }
    }
}

public struct DocumentSafetyCheck: Identifiable, Sendable, Equatable {
    public let id: String
    public let title: String
    public let state: SafetyCheckState
}

public struct DocumentAdmissionRecord: Codable, Sendable, Equatable {
    public let schemaVersion: String
    public let context: AdmissionCommandContext
    public let request: DocumentAcquisitionRequest
    public let artifact: DocumentArtifactDescriptor
    public let profile: PDFSafetyProfile
    public let lifecycle: DocumentLifecycle
    public let outcome: AdmissionOutcome
    public let reasonCodes: [String]
    public let duplicateOfAcquisitionID: UUID?
    public let recordedAt: Date

    public static var decoder: JSONDecoder {
        let decoder = JSONDecoder()
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

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case schemaVersion = "schema_version"
        case context
        case request
        case artifact
        case profile
        case lifecycle
        case outcome
        case reasonCodes = "reason_codes"
        case duplicateOfAcquisitionID = "duplicate_of_acquisition_id"
        case recordedAt = "recorded_at"
    }

    public init(from decoder: Decoder) throws {
        try decoder.rejectUnknownKeys(allowed: CodingKeys.self)
        let container = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try container.decode(String.self, forKey: .schemaVersion)
        context = try container.decode(AdmissionCommandContext.self, forKey: .context)
        request = try container.decode(DocumentAcquisitionRequest.self, forKey: .request)
        artifact = try container.decode(DocumentArtifactDescriptor.self, forKey: .artifact)
        profile = try container.decode(PDFSafetyProfile.self, forKey: .profile)
        lifecycle = try container.decode(DocumentLifecycle.self, forKey: .lifecycle)
        outcome = try container.decode(AdmissionOutcome.self, forKey: .outcome)
        reasonCodes = try container.decode([String].self, forKey: .reasonCodes)
        duplicateOfAcquisitionID = try container.decodeIfPresent(
            UUID.self,
            forKey: .duplicateOfAcquisitionID
        )
        recordedAt = try decodeContractDate(container, forKey: .recordedAt)
        try validate(decoder: decoder)
    }

    private func validate(decoder: Decoder) throws {
        let expectedLifecycle: DocumentLifecycle?
        switch outcome {
        case .quarantineForReview:
            expectedLifecycle = .awaitingReview
        case .requestPassword:
            expectedLifecycle = .awaitingPassword
        case .rejectPolicyViolation, .rejectUnsafe:
            expectedLifecycle = .rejected
        case .markExactDuplicate:
            expectedLifecycle = .duplicate
        case .accept, .acceptWithRestrictions, .registerNewVersion:
            expectedLifecycle = nil
        }
        guard schemaVersion == "1.0.0", expectedLifecycle == lifecycle else {
            throw contractError(decoder, "Unsupported or inconsistent admission outcome")
        }
        let isDuplicate = outcome == .markExactDuplicate
        guard
            isDuplicate == (duplicateOfAcquisitionID != nil),
            duplicateOfAcquisitionID != request.acquisitionID,
            artifact.artifactID == profile.artifactID,
            artifact.digest == profile.digest,
            artifact.sizeBytes == profile.sizeBytes
        else {
            throw contractError(decoder, "Admission evidence is inconsistent")
        }
        guard
            !reasonCodes.isEmpty,
            reasonCodes.count <= 32,
            reasonCodes == Array(Set(reasonCodes)).sorted(),
            reasonCodes.allSatisfy({ reason in
                reason.range(
                    of: "^[a-z][a-z0-9_]{0,63}$",
                    options: .regularExpression
                ) != nil
            })
        else {
            throw contractError(decoder, "Invalid admission reason codes")
        }
    }
}

private func decodeContractDate<Key: CodingKey>(
    _ container: KeyedDecodingContainer<Key>,
    forKey key: Key
) throws -> Date {
    let rawValue = try container.decode(String.self, forKey: key)
    guard rawValue.hasSuffix("Z") || rawValue.hasSuffix("+00:00") else {
        throw DecodingError.dataCorruptedError(
            forKey: key,
            in: container,
            debugDescription: "Contract timestamp must use UTC"
        )
    }
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
        forKey: key,
        in: container,
        debugDescription: "Invalid ISO 8601 contract timestamp"
    )
}

private func contractError(_ decoder: Decoder, _ description: String) -> DecodingError {
    .dataCorrupted(
        .init(codingPath: decoder.codingPath, debugDescription: description)
    )
}

private func isSafeContractText(_ value: String) -> Bool {
    !value.isEmpty && !value.unicodeScalars.contains { scalar in
        switch scalar.properties.generalCategory {
        case .control, .format, .surrogate, .privateUse, .unassigned:
            true
        default:
            false
        }
    }
}
