import Foundation
import Observation

@MainActor
@Observable
public final class ResearchCanvasStore {
    public private(set) var queryText = ""
    public private(set) var title = "Research draft"
    public private(set) var documentVersionID = ""
    public private(set) var chunkSetID = ""
    public private(set) var statusMessage = "Enter a query plus published canonical/chunk-set ids, then start."
    public private(set) var checkpoint: ResearchWorkflowCheckpoint?
    public private(set) var recent: [ResearchWorkflowAttempt] = []
    public private(set) var isBusy = false
    public private(set) var lastRequest: ResearchStartRequest?

    private let client: any ResearchWorkflowing

    public init(client: any ResearchWorkflowing) {
        self.client = client
    }

    public func updateQueryText(_ value: String) { queryText = value }
    public func updateTitle(_ value: String) { title = value }
    public func updateDocumentVersionID(_ value: String) { documentVersionID = value }
    public func updateChunkSetID(_ value: String) { chunkSetID = value }

    public func refresh() async {
        do {
            recent = try await client.listWorkflows()
        } catch {
            statusMessage = error.localizedDescription
        }
    }

    public func start() async {
        guard !isBusy else { return }
        isBusy = true
        defer { isBusy = false }
        let request = ResearchStartRequest(
            queryText: queryText.trimmingCharacters(in: .whitespacesAndNewlines),
            title: title.trimmingCharacters(in: .whitespacesAndNewlines),
            documentVersionID: documentVersionID.trimmingCharacters(in: .whitespacesAndNewlines),
            chunkSetID: chunkSetID.trimmingCharacters(in: .whitespacesAndNewlines)
        )
        lastRequest = request
        do {
            let response = try await client.startWorkflow(request)
            checkpoint = response.checkpoint
            statusMessage = response.interrupted
                ? "Interrupted at \(response.checkpoint.step). Review required."
                : "Workflow step: \(response.checkpoint.step)."
            await refresh()
        } catch {
            statusMessage = error.localizedDescription
        }
    }

    public func decide(action: String, rationale: String) async {
        guard !isBusy, let checkpoint, let lastRequest, let reportID = checkpoint.reportID else { return }
        isBusy = true
        defer { isBusy = false }
        do {
            let response = try await client.resumeWorkflow(
                workflowID: checkpoint.workflowID,
                request: ResearchStartRequest(
                    queryText: lastRequest.queryText,
                    title: lastRequest.title,
                    queryID: checkpoint.queryID,
                    documentVersionID: lastRequest.documentVersionID,
                    chunkSetID: lastRequest.chunkSetID
                ),
                action: action,
                rationale: rationale,
                reportID: reportID
            )
            self.checkpoint = response.checkpoint
            statusMessage = "Workflow step: \(response.checkpoint.step)."
            await refresh()
        } catch {
            statusMessage = error.localizedDescription
        }
    }
}

@MainActor
@Observable
public final class ComparisonTimelineStore {
    public private(set) var events: [TimelineEventDTO] = []
    public private(set) var observationCount = 0
    public private(set) var statusMessage = "Load observations from the local collectors plane."
    public private(set) var isBusy = false
    private let client: any ComparisonSurfacing

    public init(client: any ComparisonSurfacing) {
        self.client = client
    }

    public func refresh() async {
        guard !isBusy else { return }
        isBusy = true
        defer { isBusy = false }
        do {
            let observations = try await client.listObservationJSON(limit: 50)
            observationCount = observations.count
            guard !observations.isEmpty else {
                events = []
                statusMessage = "No observations yet. Import fixtures via collectors APIs first."
                return
            }
            let timeline = try await client.timeline(observationJSON: observations)
            events = timeline.events
            statusMessage = "Timeline \(timeline.timelineID) · \(events.count) events"
        } catch {
            events = []
            statusMessage = error.localizedDescription
        }
    }
}

@MainActor
@Observable
public final class ChunkInspectorStore {
    public private(set) var documentVersionID = ""
    public private(set) var summaries: [ChunkSetSummaryDTO] = []
    public private(set) var selected: ChunkSetEvidenceDTO?
    public private(set) var statusMessage = "Paste a canonical document version id to list chunk sets."
    public private(set) var isBusy = false
    private let client: any ChunkInspecting

    public init(client: any ChunkInspecting) {
        self.client = client
    }

    public func updateDocumentVersionID(_ value: String) { documentVersionID = value }

    public func loadSummaries() async {
        guard !isBusy else { return }
        isBusy = true
        defer { isBusy = false }
        selected = nil
        do {
            summaries = try await client.listChunkSets(
                documentVersionID: documentVersionID.trimmingCharacters(in: .whitespacesAndNewlines)
            )
            statusMessage = summaries.isEmpty
                ? "No chunk sets for that document version."
                : "Loaded \(summaries.count) chunk set(s)."
        } catch {
            summaries = []
            statusMessage = error.localizedDescription
        }
    }

    public func open(_ summary: ChunkSetSummaryDTO) async {
        guard !isBusy else { return }
        isBusy = true
        defer { isBusy = false }
        do {
            selected = try await client.chunkSet(chunkSetID: summary.chunkSetID)
            statusMessage = "Inspecting \(summary.strategyID) · \(summary.chunkCount) chunks"
        } catch {
            selected = nil
            statusMessage = error.localizedDescription
        }
    }
}
