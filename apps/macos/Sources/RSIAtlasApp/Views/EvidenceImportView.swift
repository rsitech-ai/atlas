import RSIAtlasCore
import SwiftUI
import UniformTypeIdentifiers

struct EvidenceImportView: View {
    @Bindable var store: DocumentImportStore
    @Bindable var processingStore: DocumentProcessingStore
    @State private var isFileImporterPresented = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider()
            content
        }
        .toolbar {
            ToolbarItem {
                importButton
            }
        }
        .fileImporter(
            isPresented: $isFileImporterPresented,
            allowedContentTypes: [.pdf],
            allowsMultipleSelection: false
        ) { result in
            switch result {
            case let .success(urls):
                guard let url = urls.first else {
                    store.selectionFailed()
                    return
                }
                Task { await store.importPDF(url) }
            case .failure:
                store.selectionFailed()
            }
        }
    }

    private var header: some View {
        HStack(alignment: .firstTextBaseline, spacing: 16) {
            VStack(alignment: .leading, spacing: 8) {
                Text("Evidence")
                    .font(.largeTitle.weight(.semibold))
                Text("Preserve one local PDF as immutable raw evidence before any parsing or indexing.")
                    .foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(24)
    }

    private var importButton: some View {
        Button {
            isFileImporterPresented = true
        } label: {
            Label("Import PDF", systemImage: "doc.badge.plus")
        }
        .keyboardShortcut("i", modifiers: [.command, .shift])
        .disabled(isImporting)
        .help("Import one local PDF as raw evidence (⇧⌘I)")
        .accessibilityIdentifier(EvidenceAccessibility.importButton)
    }

    @ViewBuilder
    private var content: some View {
        switch store.state {
        case .idle:
            ContentUnavailableView {
                Label("No evidence imported", systemImage: "doc.text.magnifyingglass")
            } description: {
                Text("Choose one local PDF. Raw bytes are retained before conservative safety review.")
            } actions: {
                importButton
            }

        case let .importing(filename):
            ProgressView("Preserving \(filename) as immutable raw evidence…")
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .accessibilityIdentifier(EvidenceAccessibility.progress)

        case let .loaded(record):
            VStack(spacing: 0) {
                admissionList(record)
                Divider()
                processingControls(for: record)
                CanonicalPageEvidenceView(store: processingStore)
                    .frame(minHeight: 220)
            }

        case let .failed(filename, failure):
            VStack(spacing: 12) {
                Label(failure.title, systemImage: "exclamationmark.triangle")
                    .font(.title3.weight(.semibold))
                    .accessibilityElement(children: .combine)
                    .accessibilityIdentifier(EvidenceAccessibility.error)

                Text("\(filename): \(failure.message)")
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)

                HStack(spacing: 12) {
                    Button("Retry") {
                        Task { await store.retry() }
                    }
                    .keyboardShortcut(.defaultAction)
                    .accessibilityIdentifier(EvidenceAccessibility.retry)

                    Button("Choose Another PDF") {
                        isFileImporterPresented = true
                    }
                }
            }
            .accessibilityElement(children: .contain)
            .padding(24)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    private func admissionList(_ record: DocumentAdmissionRecord) -> some View {
        List {
            Section("Durable decision") {
                Label(record.outcome.displayName, systemImage: record.outcome.systemImage)
                    .font(.headline)
                    .foregroundStyle(record.outcome.tint)
                    .accessibilityIdentifier(EvidenceAccessibility.outcome)

                LabeledContent("File", value: record.request.originalFilename)
                Text(record.outcome.boundaryMessage)
                    .font(.callout.weight(.medium))

                LabeledContent("Lifecycle", value: record.lifecycle.rawValue)
                LabeledContent("Recorded", value: record.recordedAt.formatted())
            }

            Section("Immutable raw artifact") {
                VStack(alignment: .leading, spacing: 6) {
                    Text("SHA-256")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text(record.artifact.digest)
                        .font(.system(.callout, design: .monospaced))
                        .textSelection(.enabled)
                }
                .accessibilityElement(children: .combine)
                .accessibilityIdentifier(EvidenceAccessibility.rawArtifact)

                LabeledContent(
                    "Size",
                    value: ByteCountFormatter.string(
                        fromByteCount: Int64(record.artifact.sizeBytes),
                        countStyle: .file
                    )
                )

                if let duplicateID = record.duplicateOfAcquisitionID {
                    LabeledContent("Duplicates acquisition", value: duplicateID.uuidString.lowercased())
                }
            }

            Section("Safety evidence") {
                ForEach(record.profile.checks) { check in
                    HStack(spacing: 10) {
                        Label(check.title, systemImage: check.state.systemImage)
                            .foregroundStyle(check.state.tint)
                        Spacer()
                        Text(check.state.displayName)
                            .foregroundStyle(.secondary)
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel("\(check.title), \(check.state.displayName)")
                }
            }
            .accessibilityIdentifier(EvidenceAccessibility.safetyChecks)

            Section("Decision reasons") {
                ForEach(record.reasonCodes, id: \.self) { reason in
                    VStack(alignment: .leading, spacing: 3) {
                        Text(reason.admissionReasonDisplayName)
                        Text(reason)
                            .font(.caption.monospaced())
                            .foregroundStyle(.secondary)
                            .textSelection(.enabled)
                    }
                }
            }
            .accessibilityIdentifier(EvidenceAccessibility.reasons)
        }
        .listStyle(.inset)
    }

    private func processingControls(for record: DocumentAdmissionRecord) -> some View {
        HStack {
            Text(
                record.outcome.allowsDevelopmentProcessing
                    ? "Phase 2B processing inspects canonical pages without publishing search."
                    : "Processing is unavailable for this admission outcome."
            )
            .font(.callout)
            .foregroundStyle(.secondary)
            Spacer()
            Button("Process PDF") {
                Task { await processingStore.process(acquisitionID: record.request.acquisitionID) }
            }
            .disabled({
                if !record.outcome.allowsDevelopmentProcessing { return true }
                if case .running = processingStore.state { return true }
                return false
            }())
            .accessibilityIdentifier(EvidenceAccessibility.processButton)
        }
        .padding(16)
    }

    private var isImporting: Bool {
        guard case .importing = store.state else { return false }
        return true
    }
}
