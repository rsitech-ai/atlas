import Foundation

enum WorkspaceDestination: String, CaseIterable, Identifiable {
    case commandCenter
    case evidence

    var id: Self { self }

    var title: String {
        switch self {
        case .commandCenter:
            "Command Center"
        case .evidence:
            "Evidence"
        }
    }

    var systemImage: String {
        switch self {
        case .commandCenter:
            "gauge.with.dots.needle.67percent"
        case .evidence:
            "doc.badge.plus"
        }
    }
}
