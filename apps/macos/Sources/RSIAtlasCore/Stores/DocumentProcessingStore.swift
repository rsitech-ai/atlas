import Foundation
import Observation

public enum DocumentProcessingFailure: Sendable, Equatable {
    case unavailable
    case httpStatus(Int)
    case incompatibleContract
    case pageOutOfBounds

    public var title: String {
        switch self {
        case .unavailable:
            "Local engine unavailable"
        case .httpStatus, .incompatibleContract:
            "Processing response rejected"
        case .pageOutOfBounds:
            "Page unavailable"
        }
    }

    public var message: String {
        switch self {
        case .unavailable:
            "The local engine could not be reached. No remote fallback was used."
        case let .httpStatus(code):
            "The local engine returned HTTP \(code)."
        case .incompatibleContract:
            "The local engine returned incompatible processing evidence."
        case .pageOutOfBounds:
            "The requested canonical page is out of bounds."
        }
    }
}

public enum DocumentProcessingViewState: Sendable, Equatable {
    case idle
    case running
    case loaded(status: DocumentProcessingStatus, page: CanonicalPageEvidence?)
    case failed(DocumentProcessingFailure)
}

@MainActor
@Observable
public final class DocumentProcessingStore {
    public private(set) var state: DocumentProcessingViewState = .idle
    public private(set) var selectedPage = 1
    public private(set) var showNormalizedText = false
    private let client: any DocumentProcessing
    private var generation = 0

    public init(client: any DocumentProcessing) {
        self.client = client
    }

    public func process(acquisitionID: UUID) async {
        generation += 1
        let token = generation
        state = .running
        do {
            let status = try await client.startProcessing(acquisitionID: acquisitionID)
            guard token == generation else { return }
            var page: CanonicalPageEvidence?
            if let version = status.documentVersionID, status.state == .canonicalized {
                page = try await client.canonicalPage(documentVersionID: version, pageNumber: 1)
                selectedPage = 1
            }
            guard token == generation else { return }
            state = .loaded(status: status, page: page)
        } catch {
            guard token == generation else { return }
            state = .failed(Self.failure(for: error))
        }
    }

    public func selectPage(_ pageNumber: Int) async {
        guard case let .loaded(status, _) = state, let version = status.documentVersionID else {
            return
        }
        generation += 1
        let token = generation
        do {
            let page = try await client.canonicalPage(documentVersionID: version, pageNumber: pageNumber)
            guard token == generation else { return }
            selectedPage = pageNumber
            state = .loaded(status: status, page: page)
        } catch {
            guard token == generation else { return }
            state = .failed(Self.failure(for: error))
        }
    }

    public func toggleNormalizedText() {
        showNormalizedText.toggle()
    }

    private static func failure(for error: any Error) -> DocumentProcessingFailure {
        guard let clientError = error as? DocumentProcessingClientError else {
            return .unavailable
        }
        switch clientError {
        case .transportUnavailable, .invalidResponse:
            return .unavailable
        case let .httpStatus(code):
            return .httpStatus(code)
        case .incompatibleContract:
            return .incompatibleContract
        case .pageOutOfBounds:
            return .pageOutOfBounds
        }
    }
}
