import RSIAtlasCore
import SwiftUI

extension AdmissionOutcome {
    var displayName: String {
        switch self {
        case .quarantineForReview:
            "Quarantined for review"
        case .requestPassword:
            "Password required"
        case .rejectPolicyViolation:
            "Rejected by policy"
        case .rejectUnsafe:
            "Rejected as unsafe"
        case .markExactDuplicate:
            "Exact duplicate"
        case .accept:
            "Accepted"
        case .acceptWithRestrictions:
            "Accepted with restrictions"
        case .registerNewVersion:
            "Registered as a new version"
        }
    }

    var boundaryMessage: String {
        switch self {
        case .quarantineForReview:
            "Quarantined — not admitted, parsed, or searchable."
        case .requestPassword:
            "Raw evidence retained — not admitted until a password is reviewed."
        case .rejectPolicyViolation, .rejectUnsafe:
            "Rejected — raw evidence retained, but not admitted, parsed, or searchable."
        case .markExactDuplicate:
            "Duplicate linked — the existing raw artifact remains the source of truth."
        case .accept, .acceptWithRestrictions, .registerNewVersion:
            "This outcome is outside the Phase 2A admission contract."
        }
    }

    var systemImage: String {
        switch self {
        case .quarantineForReview:
            "tray.and.arrow.down.fill"
        case .requestPassword:
            "lock.fill"
        case .rejectPolicyViolation, .rejectUnsafe:
            "xmark.octagon.fill"
        case .markExactDuplicate:
            "doc.on.doc.fill"
        case .accept, .acceptWithRestrictions, .registerNewVersion:
            "questionmark.diamond.fill"
        }
    }

    var tint: Color {
        switch self {
        case .quarantineForReview, .requestPassword:
            .orange
        case .rejectPolicyViolation, .rejectUnsafe:
            .red
        case .markExactDuplicate:
            .blue
        case .accept, .acceptWithRestrictions, .registerNewVersion:
            .secondary
        }
    }

    /// Phase 2B development Process PDF is only offered for quarantine-for-review
    /// (or later accept outcomes). Password / reject / duplicate stay blocked.
    var allowsDevelopmentProcessing: Bool {
        switch self {
        case .quarantineForReview, .accept, .acceptWithRestrictions:
            true
        case .requestPassword, .rejectPolicyViolation, .rejectUnsafe,
             .markExactDuplicate, .registerNewVersion:
            false
        }
    }
}

extension SafetyCheckState {
    var displayName: String {
        switch self {
        case .pass: "Passed"
        case .fail: "Failed"
        case .unknown: "Not yet established"
        }
    }

    var systemImage: String {
        switch self {
        case .pass: "checkmark.circle.fill"
        case .fail: "xmark.circle.fill"
        case .unknown: "questionmark.circle"
        }
    }

    var tint: Color {
        switch self {
        case .pass: .green
        case .fail: .red
        case .unknown: .orange
        }
    }
}

extension String {
    var admissionReasonDisplayName: String {
        replacingOccurrences(of: "_", with: " ")
            .localizedCapitalized
    }
}
