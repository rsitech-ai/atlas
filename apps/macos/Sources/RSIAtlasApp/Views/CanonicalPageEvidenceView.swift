import RSIAtlasCore
import SwiftUI

struct CanonicalPageEvidenceView: View {
    @Bindable var store: DocumentProcessingStore

    var body: some View {
        switch store.state {
        case .idle:
            ContentUnavailableView(
                "Canonical pages unavailable",
                systemImage: "doc.richtext",
                description: Text("Run processing on an admitted PDF to inspect canonical page evidence.")
            )

        case .running:
            ProgressView("Running governed parse and canonicalization…")
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .accessibilityIdentifier(EvidenceAccessibility.processingProgress)

        case let .loaded(status, page):
            loaded(status: status, page: page)

        case let .failed(failure):
            ContentUnavailableView {
                Label(failure.title, systemImage: "exclamationmark.triangle")
            } description: {
                Text(failure.message)
            }
        }
    }

    @ViewBuilder
    private func loaded(status: DocumentProcessingStatus, page: CanonicalPageEvidence?) -> some View {
        List {
            Section("Processing") {
                LabeledContent("State", value: status.state.rawValue)
                if let version = status.documentVersionID {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Canonical version")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text(version)
                            .font(.system(.caption, design: .monospaced))
                            .textSelection(.enabled)
                    }
                }
                if let hash = status.canonicalContentHash {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Canonical SHA-256")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text(hash)
                            .font(.system(.caption, design: .monospaced))
                            .textSelection(.enabled)
                    }
                }
                if let pageCount = status.pageCount {
                    LabeledContent("Pages", value: String(pageCount))
                }
            }

            if let page {
                Section("Page \(page.pageNumber)") {
                    Picker("Page", selection: Binding(
                        get: { store.selectedPage },
                        set: { newValue in
                            Task { await store.selectPage(newValue) }
                        }
                    )) {
                        ForEach(1 ... (status.pageCount ?? page.pageNumber), id: \.self) { number in
                            Text("Page \(number)").tag(number)
                        }
                    }
                    .accessibilityIdentifier(EvidenceAccessibility.pagePicker)

                    Toggle("Show normalized text", isOn: Binding(
                        get: { store.showNormalizedText },
                        set: { _ in store.toggleNormalizedText() }
                    ))

                    Text(store.showNormalizedText ? page.normalizedText : page.rawText)
                        .font(.body.monospaced())
                        .textSelection(.enabled)
                        .accessibilityIdentifier(EvidenceAccessibility.pageText)

                    LabeledContent("Parser", value: "\(page.parserName) \(page.parserVersion)")
                    LabeledContent("Elements", value: String(page.elementCount))
                    LabeledContent("Raw artifact", value: String(page.sourceArtifactDigest.prefix(16)) + "…")
                }

                Section("Elements") {
                    ForEach(page.elements) { element in
                        VStack(alignment: .leading, spacing: 4) {
                            Text("\(element.kind) · \(element.role ?? "unknown") · order \(element.readingOrder)")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Text(store.showNormalizedText ? element.normalizedText : element.rawText)
                            Text(element.sourceSpanID)
                                .font(.caption2.monospaced())
                                .foregroundStyle(.secondary)
                        }
                        .accessibilityElement(children: .combine)
                    }
                }
            }
        }
        .listStyle(.inset)
    }
}
