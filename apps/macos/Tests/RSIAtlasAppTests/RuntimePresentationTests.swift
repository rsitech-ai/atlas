import Testing

@testable import RSIAtlasApp
@testable import RSIAtlasCore

struct RuntimePresentationTests {
    @Test
    func commandCenterUsesScopedLocalRuntimeHealthCopy() {
        #expect(
            RuntimePresentationCopy.statusSummary
                == "Local runtime health, integrity, privacy, and resource evidence. This is not production or release readiness."
        )
        #expect(
            RuntimePresentationCopy.modelExecutionBoundary
                == "Production-qualified model execution remains disabled; development candidates do not close production acceptance."
        )
    }

    @Test
    func qaPresentationOverridesAreExactAndOptIn() {
        #expect(QAPresentationOptions.parse(arguments: ["RSIAtlas"]) == QAPresentationOptions(
            forceLight: false,
            increaseContrast: false,
            useLargeText: false,
            reduceMotion: false,
            compactWindow: false
        ))
        #expect(QAPresentationOptions.parse(arguments: [
            "RSIAtlas",
            "--qa-light",
            "--qa-increase-contrast",
            "--qa-large-text",
            "--qa-reduce-motion",
            "--qa-compact-window",
        ]) == QAPresentationOptions(
            forceLight: true,
            increaseContrast: true,
            useLargeText: true,
            reduceMotion: true,
            compactWindow: true
        ))
    }

    @Test
    func exposesStableGroupAndStateIdentifiers() {
        #expect(ComponentGroup.allCases.map(RuntimeAccessibility.group) == [
            "runtime.group.storage",
            "runtime.group.privacy",
            "runtime.group.observability",
            "runtime.group.resources",
            "runtime.group.engine",
        ])
        #expect(RuntimeAccessibility.profile == "runtime.profile")
        #expect(RuntimeAccessibility.overallState == "runtime.overall_state")
        #expect(RuntimeAccessibility.checkedAt == "runtime.checked_at")
        #expect(RuntimeAccessibility.staleStatus == "runtime.stale_status")
        #expect(RuntimeAccessibility.errorState == "runtime.error_state")
        #expect(RuntimeAccessibility.refresh == "runtime.refresh")
        #expect(RuntimeAccessibility.retry == "runtime.retry")
    }

    @Test @MainActor
    func componentAndRemediationRowsExposeDistinctIdentifiersAndCompleteLabel() throws {
        let remediation = "Start the project-owned PostgreSQL runtime, then refresh."
        let component = try ComponentStatus(
            componentID: "database",
            title: "Database",
            group: .storage,
            state: .blocked,
            summary: "PostgreSQL or pgvector is unavailable.",
            remediation: remediation
        )
        let componentRow = ComponentStatusRow(component: component)
        let remediationRow = ComponentRemediationRow(
            componentID: component.componentID,
            remediation: remediation
        )

        #expect(componentRow.accessibilityIdentifier == "runtime.component.database")
        #expect(remediationRow.accessibilityIdentifier == "runtime.remediation.database")
        #expect(componentRow.accessibilityLabel.contains("Database"))
        #expect(componentRow.accessibilityLabel.contains("blocked"))
        #expect(componentRow.accessibilityLabel.contains(remediation))
    }
}
