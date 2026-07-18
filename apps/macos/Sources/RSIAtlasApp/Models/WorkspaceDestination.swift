import Foundation

enum WorkspaceDestination: String, CaseIterable, Identifiable {
    case commandCenter

    var id: Self { self }

    var title: String {
        switch self {
        case .commandCenter:
            "Command Center"
        }
    }

    var systemImage: String {
        switch self {
        case .commandCenter:
            "gauge.with.dots.needle.67percent"
        }
    }
}
