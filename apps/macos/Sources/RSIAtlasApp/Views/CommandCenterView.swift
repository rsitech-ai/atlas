import RSIAtlasCore
import SwiftUI

enum RuntimePresentationCopy {
    static let statusSummary =
        "Local runtime health, integrity, privacy, and resource evidence. This is not production or release readiness."
    static let modelExecutionBoundary =
        "Production-qualified model execution remains disabled; development candidates do not close production acceptance."
}

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
                .disabled(isRefreshing)
                .help("Refresh local runtime status (⌘R)")
                .accessibilityIdentifier(RuntimeAccessibility.refresh)
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text("Command Center")
                    .font(.largeTitle.weight(.semibold))
                Spacer()
                if let status = currentStatus {
                    Label(status.profile.displayName, systemImage: status.profile.systemImage)
                        .font(.callout.weight(.medium))
                        .foregroundStyle(.secondary)
                        .accessibilityIdentifier(RuntimeAccessibility.profile)
                } else {
                    Label("Local Runtime", systemImage: "desktopcomputer")
                        .font(.callout.weight(.medium))
                        .foregroundStyle(.secondary)
                        .accessibilityIdentifier(RuntimeAccessibility.profile)
                }
            }
            Text(RuntimePresentationCopy.statusSummary)
                .foregroundStyle(.secondary)
            Text(RuntimePresentationCopy.modelExecutionBoundary)
                .font(.callout)
                .foregroundStyle(.secondary)
        }
        .padding(24)
    }

    @ViewBuilder
    private var statusContent: some View {
        switch store.state {
        case .idle, .loading:
            ProgressView("Checking local runtime…")
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .accessibilityIdentifier(RuntimeAccessibility.loading)

        case let .loaded(status, isRefreshing, refreshFailure):
            List {
                if let refreshFailure {
                    Section {
                        Label {
                            VStack(alignment: .leading, spacing: 4) {
                                Text("Showing the last successful check")
                                    .font(.body.weight(.medium))
                                Text(refreshFailure.message)
                                    .font(.callout)
                                    .foregroundStyle(.secondary)
                            }
                        } icon: {
                            Image(systemName: "clock.badge.exclamationmark")
                                .foregroundStyle(.orange)
                        }
                        .accessibilityIdentifier(RuntimeAccessibility.staleStatus)

                        Button("Retry Status Check") {
                            Task { await store.reload() }
                        }
                        .accessibilityIdentifier(RuntimeAccessibility.retry)
                    }
                }

                Section {
                    HStack(alignment: .firstTextBaseline) {
                        Label(status.state.displayName, systemImage: status.state.systemImage)
                            .foregroundStyle(status.state.tint)
                            .accessibilityIdentifier(RuntimeAccessibility.overallState)
                        Spacer()
                        if isRefreshing {
                            ProgressView()
                                .controlSize(.small)
                                .accessibilityLabel("Refreshing runtime status")
                        }
                        Text(
                            "Checked \(status.checkedAt.formatted(date: .abbreviated, time: .standard))"
                        )
                        .foregroundStyle(.secondary)
                        .accessibilityIdentifier(RuntimeAccessibility.checkedAt)
                    }
                }

                ForEach(status.sections) { section in
                    Section {
                        ForEach(section.components) { component in
                            ComponentStatusRow(component: component)
                            if let remediation = component.remediation {
                                ComponentRemediationRow(
                                    componentID: component.componentID,
                                    remediation: remediation
                                )
                            }
                        }
                    } header: {
                        Text(section.title)
                            .textCase(nil)
                            .accessibilityIdentifier(RuntimeAccessibility.group(section.group))
                    }
                }
            }
            .listStyle(.inset)

        case let .failed(failure):
            ContentUnavailableView {
                Label(failure.title, systemImage: "exclamationmark.triangle")
            } description: {
                Text(failure.message)
                Text("Retry after restoring the local engine. No remote fallback will be used.")
            } actions: {
                Button("Retry") {
                    Task { await store.reload() }
                }
                .keyboardShortcut(.defaultAction)
                .accessibilityIdentifier(RuntimeAccessibility.retry)
            }
            .accessibilityIdentifier(RuntimeAccessibility.errorState)
        }
    }

    private var currentStatus: SystemStatus? {
        guard case let .loaded(status, _, _) = store.state else { return nil }
        return status
    }

    private var isRefreshing: Bool {
        switch store.state {
        case .loading:
            true
        case let .loaded(_, isRefreshing, _):
            isRefreshing
        case .idle, .failed:
            false
        }
    }
}
