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
        }
    }
}

public struct DocumentProcessingClient: DocumentProcessing {
    public static let maximumResponseBytes = 2_097_152
    private static let engineBaseURL = URL(string: "http://127.0.0.1:8765")!
    private let identity: LocalWorkspaceIdentity
    private let session: URLSession

    public init(identity: LocalWorkspaceIdentity, session: URLSession = .shared) {
        self.identity = identity
        self.session = session
    }

    public func startProcessing(acquisitionID: UUID) async throws -> DocumentProcessingStatus {
        let url = Self.engineBaseURL
            .appending(path: "v1/workspaces/\(identity.workspaceID.uuidString.lowercased())/acquisitions/\(acquisitionID.uuidString.lowercased())/processing:start")
        return try await send(URLRequest(url: url, method: "POST"))
    }

    public func processingStatus(acquisitionID: UUID) async throws -> DocumentProcessingStatus {
        let url = Self.engineBaseURL
            .appending(path: "v1/workspaces/\(identity.workspaceID.uuidString.lowercased())/acquisitions/\(acquisitionID.uuidString.lowercased())/processing")
        return try await send(URLRequest(url: url, method: "GET"))
    }

    public func canonicalPage(documentVersionID: String, pageNumber: Int) async throws -> CanonicalPageEvidence {
        guard pageNumber >= 1, pageNumber <= 2_000 else {
            throw DocumentProcessingClientError.pageOutOfBounds
        }
        let encodedVersion = documentVersionID.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? documentVersionID
        let url = Self.engineBaseURL
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
            let (data, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse else {
                throw DocumentProcessingClientError.invalidResponse
            }
            guard (200 ..< 300).contains(http.statusCode) else {
                throw DocumentProcessingClientError.httpStatus(http.statusCode)
            }
            guard data.count <= Self.maximumResponseBytes else {
                throw DocumentProcessingClientError.invalidResponse
            }
            do {
                return try JSONDecoder().decode(T.self, from: data)
            } catch {
                throw DocumentProcessingClientError.incompatibleContract
            }
        } catch let error as DocumentProcessingClientError {
            throw error
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
