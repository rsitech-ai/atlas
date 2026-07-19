import Foundation

public protocol DocumentProcessing: Sendable {
    func startProcessing(acquisitionID: UUID) async throws -> DocumentProcessingStatus
    func processingStatus(acquisitionID: UUID) async throws -> DocumentProcessingStatus
    func canonicalPage(documentVersionID: String, pageNumber: Int) async throws -> CanonicalPageEvidence
}

public enum DocumentProcessingClientError: Error, Equatable, LocalizedError, Sendable {
    case invalidResponse
    case httpStatus(Int)
    case incompatibleContract
    case transportUnavailable
    case pageOutOfBounds
    case authenticationFailed
    case authenticationRequired

    public var errorDescription: String? {
        switch self {
        case .invalidResponse:
            "The local engine returned an invalid processing response."
        case let .httpStatus(code):
            "The local engine returned HTTP \(code)."
        case .incompatibleContract:
            "The local engine returned incompatible processing evidence."
        case .transportUnavailable:
            "The local engine could not be reached. No remote fallback was used."
        case .pageOutOfBounds:
            "The requested canonical page is out of bounds."
        case .authenticationFailed:
            "Local engine IPC authentication failed."
        case .authenticationRequired:
            "Local engine IPC token is missing for Unix-domain transport."
        }
    }

    public static func from(_ error: LocalEngineHTTPError) -> DocumentProcessingClientError {
        switch error {
        case .invalidResponse, .responseTooLarge:
            .invalidResponse
        case let .httpStatus(code):
            .httpStatus(code)
        case .transportUnavailable:
            .transportUnavailable
        case .authenticationFailed:
            .authenticationFailed
        case .authenticationRequired:
            .authenticationRequired
        }
    }
}

public struct DocumentProcessingClient: DocumentProcessing {
    public static let maximumResponseBytes = 2_097_152
    private let configuration: LocalEngineConfiguration
    private let identity: LocalWorkspaceIdentity
    private let http: LocalEngineHTTP

    public init(
        identity: LocalWorkspaceIdentity,
        configuration: LocalEngineConfiguration = .resolve(),
        session: URLSession = .shared
    ) {
        self.identity = identity
        self.configuration = configuration
        http = LocalEngineHTTP(configuration: configuration, urlSession: session)
    }

    public func startProcessing(acquisitionID: UUID) async throws -> DocumentProcessingStatus {
        let url = configuration.httpBaseURL
            .appending(path: "v1/workspaces/\(identity.workspaceID.uuidString.lowercased())/acquisitions/\(acquisitionID.uuidString.lowercased())/processing:start")
        return try await send(URLRequest(url: url, method: "POST"))
    }

    public func processingStatus(acquisitionID: UUID) async throws -> DocumentProcessingStatus {
        let url = configuration.httpBaseURL
            .appending(path: "v1/workspaces/\(identity.workspaceID.uuidString.lowercased())/acquisitions/\(acquisitionID.uuidString.lowercased())/processing")
        return try await send(URLRequest(url: url, method: "GET"))
    }

    public func canonicalPage(documentVersionID: String, pageNumber: Int) async throws -> CanonicalPageEvidence {
        guard pageNumber >= 1, pageNumber <= 2_000 else {
            throw DocumentProcessingClientError.pageOutOfBounds
        }
        let encodedVersion = documentVersionID.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? documentVersionID
        let url = configuration.httpBaseURL
            .appending(path: "v1/workspaces/\(identity.workspaceID.uuidString.lowercased())/canonical/\(encodedVersion)/pages/\(pageNumber)")
        return try await send(URLRequest(url: url, method: "GET"))
    }

    private func send<T: Decodable>(_ request: URLRequest) async throws -> T {
        var request = request
        request.setValue(identity.tenantID.uuidString.lowercased(), forHTTPHeaderField: "x-rsi-tenant-id")
        request.setValue(identity.actorID.uuidString.lowercased(), forHTTPHeaderField: "x-rsi-actor-id")
        request.setValue(UUID().uuidString.lowercased(), forHTTPHeaderField: "x-rsi-trace-id")
        request.setValue("application/json", forHTTPHeaderField: "accept")
        do {
            let (data, _) = try await http.perform(request, maximumResponseBytes: Self.maximumResponseBytes)
            do {
                return try JSONDecoder().decode(T.self, from: data)
            } catch {
                throw DocumentProcessingClientError.incompatibleContract
            }
        } catch let error as DocumentProcessingClientError {
            throw error
        } catch let error as LocalEngineHTTPError {
            throw DocumentProcessingClientError.from(error)
        } catch {
            throw DocumentProcessingClientError.transportUnavailable
        }
    }
}

private extension URLRequest {
    init(url: URL, method: String) {
        self.init(url: url)
        httpMethod = method
    }
}
