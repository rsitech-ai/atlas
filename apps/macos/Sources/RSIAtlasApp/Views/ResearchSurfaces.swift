import SwiftUI

/// Minimal production UX shells wired to loopback API availability (no fabricated evidence).
struct ResearchCanvasView: View {
    var body: some View {
        ContentUnavailableView(
            "Research Canvas",
            systemImage: "text.book.closed",
            description: Text(
                "Hybrid retrieve, Document Evidence specialist, and cited report drafts are available via loopback research APIs. Native plan/canvas editing ships after interrupt/resume persistence is durable in PostgreSQL."
            )
        )
        .accessibilityIdentifier("research.canvas.empty")
    }
}

struct ComparisonTimelineView: View {
    var body: some View {
        ContentUnavailableView(
            "Comparison Timeline",
            systemImage: "rectangle.split.2x1",
            description: Text(
                "Comparison matrix and cross-chain timeline payloads are available via monitoring APIs. This surface lists envelope-linked events once a native timeline client is bound."
            )
        )
        .accessibilityIdentifier("comparison.timeline.empty")
    }
}

struct ChunkInspectorView: View {
    var body: some View {
        ContentUnavailableView(
            "Chunk Inspector",
            systemImage: "square.stack.3d.up",
            description: Text(
                "Chunk sets are inspectable via loopback chunking APIs. Select an acquisition in Evidence to process pages, then open chunk inspect endpoints for family/ordinal review."
            )
        )
        .accessibilityIdentifier("chunks.inspector.empty")
    }
}
