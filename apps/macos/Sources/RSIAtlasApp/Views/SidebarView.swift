import SwiftUI

struct SidebarView: View {
    @Binding var selection: WorkspaceDestination?

    var body: some View {
        List(WorkspaceDestination.allCases, selection: $selection) { destination in
            Label(destination.title, systemImage: destination.systemImage)
                .tag(destination)
        }
        .listStyle(.sidebar)
        .navigationTitle("RSI Atlas")
        .accessibilityLabel("RSI Atlas workspaces")
    }
}
