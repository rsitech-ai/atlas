import RSIAtlasCore
import SwiftUI

struct ContentView: View {
    @State private var selection: WorkspaceDestination? = .commandCenter
    @State private var store = CommandCenterStore(loader: EngineClient())
    @State private var documentImportStore: DocumentImportStore
    @State private var documentProcessingStore: DocumentProcessingStore
    @State private var researchStore: ResearchCanvasStore
    @State private var comparisonStore: ComparisonTimelineStore
    @State private var chunkStore: ChunkInspectorStore

    init() {
        let identity = LocalWorkspaceIdentity.loadOrCreate()
        documentImportStore = DocumentImportStore(
            client: DocumentImportClient(identity: identity)
        )
        documentProcessingStore = DocumentProcessingStore(
            client: DocumentProcessingClient(identity: identity)
        )
        researchStore = ResearchCanvasStore(
            client: ResearchWorkflowClient(identity: identity)
        )
        comparisonStore = ComparisonTimelineStore(
            client: ComparisonClient(identity: identity)
        )
        chunkStore = ChunkInspectorStore(
            client: ChunkInspectClient(identity: identity)
        )
    }

    var body: some View {
        NavigationSplitView {
            SidebarView(selection: $selection)
                .navigationSplitViewColumnWidth(min: 190, ideal: 220, max: 280)
        } detail: {
            switch selection {
            case .commandCenter:
                CommandCenterView(store: store)
            case .evidence:
                EvidenceImportView(
                    store: documentImportStore,
                    processingStore: documentProcessingStore
                )
            case .research:
                ResearchCanvasView(store: researchStore)
            case .comparison:
                ComparisonTimelineView(store: comparisonStore)
            case .chunks:
                ChunkInspectorView(store: chunkStore)
            case nil:
                ContentUnavailableView(
                    "Choose a workspace",
                    systemImage: "sidebar.left",
                    description: Text("Select a destination from the sidebar.")
                )
            }
        }
        .navigationTitle(selection?.title ?? "RSI Atlas")
    }
}
