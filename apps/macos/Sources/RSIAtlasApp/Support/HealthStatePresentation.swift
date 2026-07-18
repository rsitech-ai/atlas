import RSIAtlasCore
import SwiftUI

extension HealthState {
    var displayName: String {
        switch self {
        case .healthy: "Foundation healthy"
        case .degraded: "Foundation degraded"
        case .blocked: "Foundation blocked"
        case .unsafe: "Foundation unsafe"
        case .repairable: "Repair available"
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
        case .repairable: .blue
        }
    }
}
