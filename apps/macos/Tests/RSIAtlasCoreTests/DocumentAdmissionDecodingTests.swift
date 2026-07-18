import Foundation
import Testing

@testable import RSIAtlasCore

struct DocumentAdmissionDecodingTests {
    @Test
    func admissionFixtureDecodesStrictly() throws {
        let record = try DocumentAdmissionRecord.decoder.decode(
            DocumentAdmissionRecord.self,
            from: try fixtureData()
        )

        #expect(record.schemaVersion == "1.0.0")
        #expect(record.request.method == .manualNative)
        #expect(record.lifecycle == .awaitingReview)
        #expect(record.outcome == .quarantineForReview)
        #expect(record.artifact.digest == "1e7313ace78f0fb481a486939b4885902663102818090805515553d84e0bbfd3")
        #expect(record.profile.mimeSignatureConsistency == .pass)
        #expect(record.profile.pageCountLimit == .unknown)
        #expect(record.reasonCodes == ["required_check_unknown"])
    }

    @Test
    func rejectsUnknownNestedFieldsAndInconsistentEvidence() throws {
        let data = try fixtureData()
        var object = try #require(
            JSONSerialization.jsonObject(with: data) as? [String: Any]
        )
        var artifact = try #require(object["artifact"] as? [String: Any])
        artifact["untrusted_extra"] = true
        object["artifact"] = artifact
        let unknown = try JSONSerialization.data(withJSONObject: object)

        #expect(throws: DecodingError.self) {
            try DocumentAdmissionRecord.decoder.decode(
                DocumentAdmissionRecord.self,
                from: unknown
            )
        }

        object = try #require(
            JSONSerialization.jsonObject(with: data) as? [String: Any]
        )
        artifact = try #require(object["artifact"] as? [String: Any])
        artifact["digest"] = String(repeating: "0", count: 64)
        object["artifact"] = artifact
        let inconsistent = try JSONSerialization.data(withJSONObject: object)

        #expect(throws: DecodingError.self) {
            try DocumentAdmissionRecord.decoder.decode(
                DocumentAdmissionRecord.self,
                from: inconsistent
            )
        }

        object = try #require(
            JSONSerialization.jsonObject(with: data) as? [String: Any]
        )
        object["recorded_at"] = "2026-07-18T23:32:30.902886+02:00"
        let nonUTC = try JSONSerialization.data(withJSONObject: object)

        #expect(throws: DecodingError.self) {
            try DocumentAdmissionRecord.decoder.decode(
                DocumentAdmissionRecord.self,
                from: nonUTC
            )
        }
    }

    @Test
    func rejectsUnknownFieldsAtEveryContractObjectBoundary() throws {
        for boundary in ["top", "context", "request", "artifact", "profile"] {
            var object = try fixtureObject()
            if boundary == "top" {
                object["unexpected"] = true
            } else {
                var nested = try #require(object[boundary] as? [String: Any])
                nested["unexpected"] = true
                object[boundary] = nested
            }
            #expect(throws: DecodingError.self, "Boundary: \(boundary)") {
                try decodeFixtureObject(object)
            }
        }
    }

    @Test
    func acceptsEveryPhaseTwoAOutcomeAndAcquisitionMethod() throws {
        let outcomes: [(String, String, String?, String)] = [
            ("quarantine_for_review", "awaiting_review", nil, "required_check_unknown"),
            ("request_password", "awaiting_password", nil, "password_required"),
            ("reject_policy_violation", "rejected", nil, "source_policy_denied"),
            ("reject_unsafe", "rejected", nil, "pdf_signature_or_mime_invalid"),
            (
                "mark_exact_duplicate",
                "duplicate",
                "66666666-6666-4666-8666-666666666666",
                "exact_duplicate"
            ),
        ]
        for (outcome, lifecycle, duplicate, reason) in outcomes {
            var object = try fixtureObject()
            object["outcome"] = outcome
            object["lifecycle"] = lifecycle
            object["duplicate_of_acquisition_id"] = duplicate
            object["reason_codes"] = [reason]
            #expect(throws: Never.self, "Outcome: \(outcome)") {
                try decodeFixtureObject(object)
            }
        }

        for method in ["manual_native", "manual_cli", "local_api"] {
            var object = try fixtureObject()
            var request = try #require(object["request"] as? [String: Any])
            request["method"] = method
            object["request"] = request
            #expect(throws: Never.self, "Method: \(method)") {
                try decodeFixtureObject(object)
            }
        }
    }

    @Test
    func rejectsOutcomeDuplicateReasonAndProfileInvariantDrift() throws {
        let invalidOutcomes: [(String, String, String?)] = [
            ("accept", "quarantined", nil),
            ("accept_with_restrictions", "quarantined", nil),
            ("register_new_version", "quarantined", nil),
            ("request_password", "awaiting_review", nil),
            ("mark_exact_duplicate", "duplicate", nil),
            (
                "quarantine_for_review",
                "awaiting_review",
                "66666666-6666-4666-8666-666666666666"
            ),
            (
                "mark_exact_duplicate",
                "duplicate",
                "55555555-5555-4555-8555-555555555555"
            ),
        ]
        for (outcome, lifecycle, duplicate) in invalidOutcomes {
            var object = try fixtureObject()
            object["outcome"] = outcome
            object["lifecycle"] = lifecycle
            object["duplicate_of_acquisition_id"] = duplicate
            #expect(throws: DecodingError.self, "Outcome: \(outcome)") {
                try decodeFixtureObject(object)
            }
        }

        let invalidReasons: [[String]] = [
            [],
            ["duplicate", "duplicate"],
            ["z_reason", "a_reason"],
            ["Uppercase"],
            ["9_starts_with_digit"],
            [String(repeating: "a", count: 65)],
        ]
        for reasons in invalidReasons {
            var object = try fixtureObject()
            object["reason_codes"] = reasons
            #expect(throws: DecodingError.self, "Reasons: \(reasons)") {
                try decodeFixtureObject(object)
            }
        }

        let invalidProfiles: [(String, Any)] = [
            ("schema_version", "2.0.0"),
            ("policy_version", "phase-2b-1"),
            ("size_bytes", 0),
            ("header_version", "1.8"),
            ("page_marker_count", 2_002),
        ]
        for (field, value) in invalidProfiles {
            var object = try fixtureObject()
            var profile = try #require(object["profile"] as? [String: Any])
            profile[field] = value
            object["profile"] = profile
            #expect(throws: DecodingError.self, "Profile field: \(field)") {
                try decodeFixtureObject(object)
            }
        }

        var object = try fixtureObject()
        var profile = try #require(object["profile"] as? [String: Any])
        profile["header_version"] = NSNull()
        object["profile"] = profile
        #expect(throws: DecodingError.self) { try decodeFixtureObject(object) }

        object = try fixtureObject()
        profile = try #require(object["profile"] as? [String: Any])
        profile["malformed_structure"] = "pass"
        profile["eof_marker_present"] = false
        object["profile"] = profile
        #expect(throws: DecodingError.self) { try decodeFixtureObject(object) }

        object = try fixtureObject()
        profile = try #require(object["profile"] as? [String: Any])
        profile["page_count_limit"] = "pass"
        profile["page_marker_count"] = NSNull()
        object["profile"] = profile
        #expect(throws: DecodingError.self) { try decodeFixtureObject(object) }
    }

    @Test
    func rejectsFilenameBeyondPythonUnicodeCodePointLimit() throws {
        var object = try fixtureObject()
        var request = try #require(object["request"] as? [String: Any])
        let filename = String(repeating: "🇵🇱", count: 126) + ".pdf"
        #expect(filename.count <= 255)
        #expect(filename.unicodeScalars.count > 255)
        request["original_filename"] = filename
        object["request"] = request

        #expect(throws: DecodingError.self) {
            try decodeFixtureObject(object)
        }
    }
}

private func fixtureData() throws -> Data {
    let fixtureURL = try #require(
        Bundle.module.url(forResource: "document_admission_v1", withExtension: "json")
    )
    return try Data(contentsOf: fixtureURL)
}

private func fixtureObject() throws -> [String: Any] {
    try #require(
        JSONSerialization.jsonObject(with: fixtureData()) as? [String: Any]
    )
}

@discardableResult
private func decodeFixtureObject(_ object: [String: Any]) throws -> DocumentAdmissionRecord {
    try DocumentAdmissionRecord.decoder.decode(
        DocumentAdmissionRecord.self,
        from: JSONSerialization.data(withJSONObject: object)
    )
}
