import RSIAtlasCore
import SwiftUI

struct ContentView: View {
    @State private var selection: WorkspaceDestination? = .commandCenter
    @State private var store = CommandCenterStore(loader: EngineClient())

    var body: some View {
        NavigationSplitView {
            SidebarView(selection: $selection)
                .navigationSplitViewColumnWidth(min: 190, ideal: 220, max: 280)
        } detail: {
            if selection == .commandCenter {
                CommandCenterView(store: store)
            } else {
                ContentUnavailableView(
                    "Choose a workspace",
                    systemImage: "sidebar.left",
                    description: Text("Select Command Center from the sidebar.")
                )
            }
        }
        .navigationTitle(selection?.title ?? "RSI Atlas")
    }
}
