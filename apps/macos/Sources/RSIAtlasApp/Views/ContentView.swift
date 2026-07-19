import RSIAtlasCore
import SwiftUI

struct ContentView: View {
    @State private var selection: WorkspaceDestination? = .commandCenter
    @State private var store = CommandCenterStore(loader: EngineClient())
    @State private var documentImportStore: DocumentImportStore
    @State private var documentProcessingStore: DocumentProcessingStore

    init() {
        let identity = LocalWorkspaceIdentity.loadOrCreate()
        documentImportStore = DocumentImportStore(
            client: DocumentImportClient(identity: identity)
        )
        documentProcessingStore = DocumentProcessingStore(
            client: DocumentProcessingClient(identity: identity)
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
                ResearchCanvasView()
            case .comparison:
                ComparisonTimelineView()
            case .chunks:
                ChunkInspectorView()
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
