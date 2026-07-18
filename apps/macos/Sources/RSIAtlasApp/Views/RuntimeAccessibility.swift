import RSIAtlasCore

enum RuntimeAccessibility {
    static let profile = "runtime.profile"
    static let loading = "runtime.loading"
    static let staleStatus = "runtime.stale_status"
    static let retry = "runtime.retry"
    static let overallState = "runtime.overall_state"
    static let checkedAt = "runtime.checked_at"
    static let refresh = "runtime.refresh"
    static let errorState = "runtime.error_state"

    static func group(_ group: ComponentGroup) -> String {
        "runtime.group.\(group.rawValue)"
    }

    static func component(_ componentID: String) -> String {
        "runtime.component.\(componentID)"
    }

    static func remediation(_ componentID: String) -> String {
        "runtime.remediation.\(componentID)"
    }
}
