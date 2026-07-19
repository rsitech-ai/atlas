import RSIAtlasCore
import SwiftUI

struct ResearchCanvasView: View {
    @Bindable var store: ResearchCanvasStore

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider()
            form
            Divider()
            status
            if let checkpoint = store.checkpoint {
                Divider()
                checkpointPanel(checkpoint)
                if let reportID = checkpoint.reportID {
                    Divider()
                    reportStudioPanel(reportID: reportID, title: store.title)
                }
            }
            Divider()
            recentList
        }
        .task { await store.refresh() }
        .accessibilityIdentifier("research.canvas")
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Research Canvas")
                .font(.largeTitle.weight(.semibold))
                Text("Start a durable multi-specialist workflow over authenticated local IPC (Unix domain by default). Interrupt waits for human review. Report Studio panel shows the draft id when present.")
                .foregroundStyle(.secondary)
        }
        .padding(24)
    }

    private var form: some View {
        Form {
            TextField("Query", text: Binding(
                get: { store.queryText },
                set: { store.updateQueryText($0) }
            ))
            TextField("Title", text: Binding(
                get: { store.title },
                set: { store.updateTitle($0) }
            ))
            TextField("canonical:… document version", text: Binding(
                get: { store.documentVersionID },
                set: { store.updateDocumentVersionID($0) }
            ))
            TextField("chunkset:… id", text: Binding(
                get: { store.chunkSetID },
                set: { store.updateChunkSetID($0) }
            ))
            HStack {
                Button("Start workflow") {
                    Task { await store.start() }
                }
                .disabled(store.isBusy || store.queryText.isEmpty || store.documentVersionID.isEmpty || store.chunkSetID.isEmpty)
                .accessibilityIdentifier("research.start")
                if store.checkpoint?.step == "awaiting_human" {
                    Button("Approve") {
                        Task { await store.decide(action: "approve", rationale: "Approved from Research Canvas.") }
                    }
                    .accessibilityIdentifier("research.approve")
                    Button("Reject") {
                        Task { await store.decide(action: "reject", rationale: "Rejected from Research Canvas.") }
                    }
                    .accessibilityIdentifier("research.reject")
                }
            }
        }
        .padding(16)
        .formStyle(.grouped)
    }

    private var status: some View {
        Text(store.statusMessage)
            .foregroundStyle(.secondary)
            .padding(16)
            .accessibilityIdentifier("research.status")
    }

    private func checkpointPanel(_ checkpoint: ResearchWorkflowCheckpoint) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Checkpoint")
                .font(.headline)
            LabeledContent("Step", value: checkpoint.step)
            LabeledContent("Workflow", value: checkpoint.workflowID.uuidString.lowercased())
            if let reportID = checkpoint.reportID {
                LabeledContent("Report", value: reportID)
            }
            if !checkpoint.detail.isEmpty {
                Text(checkpoint.detail)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(16)
        .accessibilityIdentifier("research.checkpoint")
    }

    private func reportStudioPanel(reportID: String, title: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Report Studio")
                .font(.headline)
            Text("Minimal native draft inspector (assertions/citations remain on the engine report record).")
                .font(.caption)
                .foregroundStyle(.secondary)
            LabeledContent("Title", value: title.isEmpty ? "Untitled" : title)
            LabeledContent("Report ID", value: reportID)
            Text("Approve or reject from the Research Canvas controls when the workflow is awaiting human review.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(16)
        .accessibilityIdentifier("research.reportStudio")
    }

    private var recentList: some View {
        List(store.recent, id: \.checkpoint.workflowID) { item in
            VStack(alignment: .leading, spacing: 4) {
                Text(item.title.isEmpty ? "Untitled" : item.title)
                Text("\(item.checkpoint.step) · \(item.checkpoint.workflowID.uuidString.lowercased())")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .accessibilityIdentifier("research.recent")
    }
}

struct ComparisonTimelineView: View {
    @Bindable var store: ComparisonTimelineStore

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Comparison")
                        .font(.largeTitle.weight(.semibold))
                    Text("Timeline events and a lightweight comparison matrix shell over local observations.")
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button("Refresh") {
                    Task { await store.refresh() }
                }
                .disabled(store.isBusy)
                .accessibilityIdentifier("comparison.refresh")
            }
            .padding(24)
            Divider()
            Text(store.statusMessage)
                .foregroundStyle(.secondary)
                .padding(16)
                .accessibilityIdentifier("comparison.status")
            Divider()
            matrixShell
            Divider()
            if store.events.isEmpty {
                ContentUnavailableView(
                    "No timeline events",
                    systemImage: "rectangle.split.2x1",
                    description: Text("Import collector fixtures, then refresh.")
                )
                .accessibilityIdentifier("comparison.timeline.empty")
            } else {
                List(store.events) { event in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(event.summary)
                        Text("\(event.eventKind) · \(event.subjectID) · \(event.eventTime)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        if let observationID = event.observationID {
                            Text(observationID)
                                .font(.caption2)
                                .foregroundStyle(.tertiary)
                        }
                    }
                }
                .accessibilityIdentifier("comparison.timeline.list")
            }
        }
        .task { await store.refresh() }
        .accessibilityIdentifier("comparison.timeline")
    }

    private var matrixShell: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Comparison Matrix")
                .font(.headline)
            Text("Observations loaded: \(store.observationCount). Full cross-axis matrix cells remain engine-backed; this shell surfaces count and timeline linkage.")
                .font(.caption)
                .foregroundStyle(.secondary)
            LabeledContent("Timeline events", value: "\(store.events.count)")
        }
        .padding(16)
        .accessibilityIdentifier("comparison.matrix")
    }
}

struct ChunkInspectorView: View {
    @Bindable var store: ChunkInspectorStore

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 8) {
                Text("Chunk Inspector")
                    .font(.largeTitle.weight(.semibold))
                Text("List and inspect chunk sets for a canonical document version over authenticated local IPC.")
                    .foregroundStyle(.secondary)
            }
            .padding(24)
            Divider()
            HStack {
                TextField("canonical:…", text: Binding(
                    get: { store.documentVersionID },
                    set: { store.updateDocumentVersionID($0) }
                ))
                Button("List chunk sets") {
                    Task { await store.loadSummaries() }
                }
                .disabled(store.isBusy || store.documentVersionID.isEmpty)
                .accessibilityIdentifier("chunks.list")
            }
            .padding(16)
            Text(store.statusMessage)
                .foregroundStyle(.secondary)
                .padding(.horizontal, 16)
                .accessibilityIdentifier("chunks.status")
            Divider()
            HSplitView {
                List(store.summaries) { summary in
                    Button {
                        Task { await store.open(summary) }
                    } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(summary.strategyID)
                            Text("\(summary.chunkCount) chunks · \(summary.chunkSetID)")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .buttonStyle(.plain)
                }
                .frame(minWidth: 240)
                .accessibilityIdentifier("chunks.summaries")

                if let selected = store.selected {
                    List(Array(selected.chunks.enumerated()), id: \.offset) { index, chunk in
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Chunk \(index + 1)")
                                .font(.headline)
                            Text(chunkPreview(chunk))
                                .lineLimit(6)
                        }
                    }
                    .accessibilityIdentifier("chunks.detail")
                } else {
                    ContentUnavailableView(
                        "Select a chunk set",
                        systemImage: "square.stack.3d.up",
                        description: Text("Choose a strategy from the list.")
                    )
                    .accessibilityIdentifier("chunks.inspector.empty")
                }
            }
        }
        .accessibilityIdentifier("chunks.inspector")
    }

    private func chunkPreview(_ chunk: [String: JSONValue]) -> String {
        for key in ["text", "raw_text", "text_preview", "content"] {
            if case let .string(text)? = chunk[key] {
                return text
            }
        }
        return "fields: \(chunk.keys.sorted().joined(separator: ", "))"
    }
}
