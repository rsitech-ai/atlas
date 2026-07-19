import Testing

@testable import RSIAtlasApp
@testable import RSIAtlasCore

struct EvidencePresentationTests {
    @Test
    func evidenceWorkspaceIsAStableNativeDestination() {
        #expect(WorkspaceDestination.allCases == [
            .commandCenter,
            .evidence,
            .research,
            .comparison,
            .chunks,
        ])
        #expect(WorkspaceDestination.evidence.title == "Evidence")
        #expect(WorkspaceDestination.evidence.systemImage == "doc.badge.plus")
        #expect(WorkspaceDestination.research.title == "Research")
        #expect(WorkspaceDestination.comparison.title == "Comparison")
        #expect(WorkspaceDestination.chunks.title == "Chunks")
    }

    @Test
    func exposesStableEvidenceAccessibilityIdentifiers() {
        #expect(EvidenceAccessibility.importButton == "evidence.import")
        #expect(EvidenceAccessibility.progress == "evidence.progress")
        #expect(EvidenceAccessibility.outcome == "evidence.outcome")
        #expect(EvidenceAccessibility.rawArtifact == "evidence.raw_artifact")
        #expect(EvidenceAccessibility.safetyChecks == "evidence.safety_checks")
        #expect(EvidenceAccessibility.reasons == "evidence.reasons")
        #expect(EvidenceAccessibility.error == "evidence.error")
        #expect(EvidenceAccessibility.retry == "evidence.retry")
    }

    @Test
    func admissionPresentationNeverClaimsUnknownEvidenceIsSearchable() {
        #expect(AdmissionOutcome.quarantineForReview.displayName == "Quarantined for review")
        #expect(AdmissionOutcome.requestPassword.displayName == "Password required")
        #expect(AdmissionOutcome.rejectUnsafe.displayName == "Rejected as unsafe")
        #expect(AdmissionOutcome.markExactDuplicate.displayName == "Exact duplicate")
        #expect(
            AdmissionOutcome.quarantineForReview.boundaryMessage
                == "Quarantined — not admitted, parsed, or searchable."
        )
        #expect(AdmissionOutcome.quarantineForReview.allowsDevelopmentProcessing)
        #expect(!AdmissionOutcome.requestPassword.allowsDevelopmentProcessing)
        #expect(!AdmissionOutcome.rejectUnsafe.allowsDevelopmentProcessing)
        #expect(!AdmissionOutcome.markExactDuplicate.allowsDevelopmentProcessing)
    }
}
