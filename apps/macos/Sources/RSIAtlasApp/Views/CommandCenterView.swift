import RSIAtlasCore
import SwiftUI

struct CommandCenterView: View {
    @Bindable var store: CommandCenterStore

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider()
            statusContent
        }
        .task {
            if store.state == .idle {
                await store.reload()
            }
        }
        .toolbar {
            ToolbarItem {
                Button {
                    Task { await store.reload() }
                } label: {
                    Label("Refresh Runtime Status", systemImage: "arrow.clockwise")
                }
                .keyboardShortcut("r", modifiers: .command)
                .disabled(store.state == .loading)
                .help("Refresh local runtime status (⌘R)")
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text("Command Center")
                    .font(.largeTitle.weight(.semibold))
                Spacer()
                Label("Strict Offline", systemImage: "network.slash")
                    .font(.callout.weight(.medium))
                    .foregroundStyle(.secondary)
            }
            Text("Local runtime readiness and policy enforcement for the RSI Atlas foundation.")
                .foregroundStyle(.secondary)
            Text("Persistence, collectors, document intelligence, and model services are not enabled in this slice.")
                .font(.callout)
                .foregroundStyle(.secondary)
        }
        .padding(24)
    }

    @ViewBuilder
    private var statusContent: some View {
        switch store.state {
        case .idle, .loading:
            VStack(spacing: 12) {
                ProgressView()
                Text("Checking local runtime…")
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

        case let .loaded(status):
            List {
                Section {
                    ForEach(status.components) { component in
                        ComponentStatusRow(component: component)
                    }
                } header: {
                    HStack {
                        Label(status.state.displayName, systemImage: status.state.systemImage)
                            .foregroundStyle(status.state.tint)
                        Spacer()
                        Text("Checked \(status.checkedAt.formatted(date: .abbreviated, time: .standard))")
                            .foregroundStyle(.secondary)
                    }
                    .textCase(nil)
                }
            }
            .listStyle(.inset)

        case let .failed(message):
            ContentUnavailableView {
                Label("Engine unavailable", systemImage: "exclamationmark.triangle")
            } description: {
                Text(message)
                Text("Start the local engine, then retry. No remote fallback will be used.")
            } actions: {
                Button("Retry") {
                    Task { await store.reload() }
                }
                .keyboardShortcut(.defaultAction)
            }
        }
    }
}
