import Foundation

enum WorkspaceDestination: String, CaseIterable, Identifiable {
    case commandCenter
    case evidence
    case research
    case comparison
    case chunks

    var id: Self { self }

    var title: String {
        switch self {
        case .commandCenter:
            "Command Center"
        case .evidence:
            "Evidence"
        case .research:
            "Research"
        case .comparison:
            "Comparison"
        case .chunks:
            "Chunks"
        }
    }

    var systemImage: String {
        switch self {
        case .commandCenter:
            "gauge.with.dots.needle.67percent"
        case .evidence:
            "doc.badge.plus"
        case .research:
            "text.book.closed"
        case .comparison:
            "rectangle.split.2x1"
        case .chunks:
            "square.stack.3d.up"
        }
    }
}
