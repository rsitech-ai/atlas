import Foundation
import Observation

public enum DocumentImportFailure: Sendable, Equatable {
    case sourceMissingOrUnsafe
    case invalidPDF
    case emptyFile
    case fileTooLarge
    case sourceChanged
    case invalidResponse
    case httpStatus(Int)
    case responseTooLarge
    case incompatibleContract
    case unavailable

    public var title: String {
        switch self {
        case .sourceMissingOrUnsafe, .invalidPDF, .emptyFile, .fileTooLarge, .sourceChanged:
            "PDF import rejected"
        case .invalidResponse, .httpStatus, .responseTooLarge, .incompatibleContract:
            "Admission response rejected"
        case .unavailable:
            "Local engine unavailable"
        }
    }

    public var message: String {
        switch self {
        case .sourceMissingOrUnsafe:
            "The selected source is missing, symlinked, or unsafe."
        case .invalidPDF:
            "Select one local PDF file."
        case .emptyFile:
            "The selected PDF is empty."
        case .fileTooLarge:
            "The selected PDF exceeds the 32 MB admission limit."
        case .sourceChanged:
            "The selected PDF changed during upload. Select it again."
        case .invalidResponse:
            "The local engine did not return an HTTP response."
        case let .httpStatus(statusCode):
            "The local engine returned HTTP \(statusCode)."
        case .responseTooLarge:
            "The local admission response exceeded the safe limit."
        case .incompatibleContract:
            "The local engine returned incompatible admission evidence."
        case .unavailable:
            "The local engine could not be reached. No remote fallback was used."
        }
    }
}

public enum DocumentImportState: Sendable, Equatable {
    case idle
    case importing(filename: String)
    case loaded(DocumentAdmissionRecord)
    case failed(filename: String, failure: DocumentImportFailure)
}

@MainActor
@Observable
public final class DocumentImportStore {
    public private(set) var state: DocumentImportState = .idle
    private let client: any DocumentImporting
    private var importGeneration = 0
    private var retryRequest: DocumentImportRequest?

    public init(client: any DocumentImporting) {
        self.client = client
    }

    public func importPDF(_ url: URL) async {
        let request = DocumentImportRequest(sourceURL: url)
        retryRequest = request
        await performImport(request)
    }

    private func performImport(_ request: DocumentImportRequest) async {
        importGeneration += 1
        let generation = importGeneration
        let url = request.sourceURL
        state = .importing(filename: url.lastPathComponent)
        do {
            let record = try await client.importPDF(request)
            guard generation == importGeneration else { return }
            state = .loaded(record)
        } catch is CancellationError {
            guard generation == importGeneration else { return }
            state = .idle
        } catch {
            guard generation == importGeneration else { return }
            state = .failed(
                filename: url.lastPathComponent,
                failure: Self.failure(for: error)
            )
        }
    }

    public func retry() async {
        guard let retryRequest else { return }
        await performImport(retryRequest)
    }

    public func selectionFailed() {
        importGeneration += 1
        retryRequest = nil
        state = .failed(filename: "PDF", failure: .sourceMissingOrUnsafe)
    }

    private static func failure(for error: any Error) -> DocumentImportFailure {
        guard let clientError = error as? DocumentImportClientError else {
            return .unavailable
        }
        switch clientError {
        case .sourceMissingOrUnsafe:
            return .sourceMissingOrUnsafe
        case .invalidPDF:
            return .invalidPDF
        case .emptyFile:
            return .emptyFile
        case .fileTooLarge:
            return .fileTooLarge
        case .sourceChanged:
            return .sourceChanged
        case .invalidResponse:
            return .invalidResponse
        case let .httpStatus(statusCode):
            return .httpStatus(statusCode)
        case .responseTooLarge:
            return .responseTooLarge
        case .incompatibleContract:
            return .incompatibleContract
        case .transportUnavailable:
            return .unavailable
        }
    }
}
