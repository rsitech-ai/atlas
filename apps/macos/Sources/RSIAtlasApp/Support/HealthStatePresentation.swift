import RSIAtlasCore
import SwiftUI

extension HealthState {
    var displayName: String {
        switch self {
        case .healthy: "Runtime healthy"
        case .degraded: "Runtime degraded"
        case .blocked: "Runtime blocked"
        case .unsafe: "Runtime unsafe"
        case .repairable: "Runtime repairable"
        }
    }

    var systemImage: String {
        switch self {
        case .healthy: "checkmark.seal.fill"
        case .degraded: "exclamationmark.triangle.fill"
        case .blocked: "xmark.octagon.fill"
        case .unsafe: "shield.slash.fill"
        case .repairable: "wrench.and.screwdriver.fill"
        }
    }

    var tint: Color {
        switch self {
        case .healthy: .green
        case .degraded: .orange
        case .blocked, .unsafe: .red
        case .repairable: .orange
        }
    }
}

extension RuntimeProfile {
    var displayName: String {
        switch self {
        case .offline: "Strict Offline"
        case .monitored: "Monitored"
        }
    }

    var systemImage: String {
        switch self {
        case .offline: "network.slash"
        case .monitored: "network"
        }
    }
}
