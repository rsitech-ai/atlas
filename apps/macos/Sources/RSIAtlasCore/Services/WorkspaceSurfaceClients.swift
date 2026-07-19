import Foundation

public enum LoopbackClientError: Error, Equatable, LocalizedError, Sendable {
    case invalidResponse
    case httpStatus(Int)
    case incompatibleContract
    case transportUnavailable

    public var errorDescription: String? {
        switch self {
        case .invalidResponse:
            "The local engine returned an invalid response."
        case let .httpStatus(code):
            "The local engine returned HTTP \(code)."
        case .incompatibleContract:
            "The local engine returned incompatible evidence."
        case .transportUnavailable:
            "The local engine could not be reached. No remote fallback was used."
        }
    }
}

public struct ResearchStartRequest: Sendable, Equatable {
    public let queryText: String
    public let title: String
    public let queryID: UUID
    public let documentVersionID: String
    public let chunkSetID: String

    public init(
        queryText: String,
        title: String,
        queryID: UUID = UUID(),
        documentVersionID: String,
        chunkSetID: String
    ) {
        self.queryText = queryText
        self.title = title
        self.queryID = queryID
        self.documentVersionID = documentVersionID
        self.chunkSetID = chunkSetID
    }
}

public protocol ResearchWorkflowing: Sendable {
    func startWorkflow(_ request: ResearchStartRequest) async throws -> ResearchWorkflowResponse
    func resumeWorkflow(
        workflowID: UUID,
        request: ResearchStartRequest,
        action: String,
        rationale: String,
        reportID: String
    ) async throws -> ResearchWorkflowResponse
    func listWorkflows() async throws -> [ResearchWorkflowAttempt]
}

public struct ResearchWorkflowClient: ResearchWorkflowing {
    public static let maximumResponseBytes = 2_097_152
    private static let engineBaseURL = URL(string: "http://127.0.0.1:8765")!
    private let identity: LocalWorkspaceIdentity
    private let session: URLSession

    public init(identity: LocalWorkspaceIdentity, session: URLSession = .shared) {
        self.identity = identity
        self.session = session
    }

    public func startWorkflow(_ request: ResearchStartRequest) async throws -> ResearchWorkflowResponse {
        let url = Self.engineBaseURL
            .appending(path: "v1/workspaces/\(identity.workspaceID.uuidString.lowercased())/research/workflows:start")
        var httpRequest = URLRequest(url: url)
        httpRequest.httpMethod = "POST"
        httpRequest.httpBody = try JSONSerialization.data(withJSONObject: [
            "title": request.title,
            "query": Self.queryPayload(identity: identity, request: request),
        ])
        return try await send(httpRequest)
    }

    public func resumeWorkflow(
        workflowID: UUID,
        request: ResearchStartRequest,
        action: String,
        rationale: String,
        reportID: String
    ) async throws -> ResearchWorkflowResponse {
        let url = Self.engineBaseURL
            .appending(
                path: "v1/workspaces/\(identity.workspaceID.uuidString.lowercased())/research/workflows/\(workflowID.uuidString.lowercased()):resume"
            )
        var httpRequest = URLRequest(url: url)
        httpRequest.httpMethod = "POST"
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        let decision: [String: Any] = [
            "schema_version": "1.0.0",
            "decision_id": UUID().uuidString.lowercased(),
            "report_id": reportID,
            "context": [
                "tenant_id": identity.tenantID.uuidString.lowercased(),
                "workspace_id": identity.workspaceID.uuidString.lowercased(),
                "actor_id": identity.actorID.uuidString.lowercased(),
                "trace_id": UUID().uuidString.lowercased(),
            ],
            "action": action,
            "rationale": rationale,
            "recorded_at": formatter.string(from: Date()),
        ]
        httpRequest.httpBody = try JSONSerialization.data(withJSONObject: [
            "title": request.title,
            "query": Self.queryPayload(identity: identity, request: request),
            "human_decision": decision,
        ])
        return try await send(httpRequest)
    }

    public func listWorkflows() async throws -> [ResearchWorkflowAttempt] {
        let url = Self.engineBaseURL
            .appending(path: "v1/workspaces/\(identity.workspaceID.uuidString.lowercased())/research/workflows")
        let response: ResearchWorkflowListResponse = try await send(URLRequest(url: url, method: "GET"))
        return response.workflows
    }

    private func send<T: Decodable>(_ request: URLRequest) async throws -> T {
        try await LoopbackJSON.send(
            request,
            identity: identity,
            session: session,
            maximumResponseBytes: Self.maximumResponseBytes
        )
    }

    private static func queryPayload(
        identity: LocalWorkspaceIdentity,
        request: ResearchStartRequest
    ) -> [String: Any] {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return [
            "schema_version": "1.0.0",
            "query_id": request.queryID.uuidString.lowercased(),
            "context": [
                "tenant_id": identity.tenantID.uuidString.lowercased(),
                "workspace_id": identity.workspaceID.uuidString.lowercased(),
                "actor_id": identity.actorID.uuidString.lowercased(),
                "trace_id": UUID().uuidString.lowercased(),
            ],
            "text": request.queryText,
            "query_family": "narrative_explanation",
            "subject_ids": [],
            "document_version_ids": [request.documentVersionID],
            "chunk_set_ids": [request.chunkSetID],
            "as_of": formatter.string(from: Date()),
            "latency_budget_ms": 5_000,
            "context_budget_tokens": 2_048,
        ]
    }
}

public protocol ComparisonSurfacing: Sendable {
    func listObservationJSON(limit: Int) async throws -> [[String: Any]]
    func timeline(observationJSON: [[String: Any]]) async throws -> TimelinePayloadDTO
}

public struct ComparisonClient: ComparisonSurfacing {
    public static let maximumResponseBytes = 2_097_152
    private static let engineBaseURL = URL(string: "http://127.0.0.1:8765")!
    private let identity: LocalWorkspaceIdentity
    private let session: URLSession

    public init(identity: LocalWorkspaceIdentity, session: URLSession = .shared) {
        self.identity = identity
        self.session = session
    }

    public func listObservationJSON(limit: Int = 50) async throws -> [[String: Any]] {
        var components = URLComponents(
            url: Self.engineBaseURL
                .appending(path: "v1/workspaces/\(identity.workspaceID.uuidString.lowercased())/observations"),
            resolvingAgainstBaseURL: false
        )!
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        components.queryItems = [
            URLQueryItem(name: "limit", value: String(limit)),
            URLQueryItem(name: "as_of", value: formatter.string(from: Date())),
        ]
        let data = try await LoopbackJSON.data(
            URLRequest(url: components.url!, method: "GET"),
            identity: identity,
            session: session,
            maximumResponseBytes: Self.maximumResponseBytes
        )
        guard
            let root = try JSONSerialization.jsonObject(with: data) as? [String: Any],
            let observations = root["observations"] as? [[String: Any]]
        else {
            throw LoopbackClientError.incompatibleContract
        }
        return observations
    }

    public func timeline(observationJSON: [[String: Any]]) async throws -> TimelinePayloadDTO {
        let url = Self.engineBaseURL
            .appending(path: "v1/workspaces/\(identity.workspaceID.uuidString.lowercased())/monitoring:timeline")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "observations": observationJSON,
            "as_of": formatter.string(from: Date()),
        ])
        let response: TimelineResponseDTO = try await LoopbackJSON.send(
            request,
            identity: identity,
            session: session,
            maximumResponseBytes: Self.maximumResponseBytes
        )
        return response.timeline
    }
}

public protocol ChunkInspecting: Sendable {
    func listChunkSets(documentVersionID: String) async throws -> [ChunkSetSummaryDTO]
    func chunkSet(chunkSetID: String) async throws -> ChunkSetEvidenceDTO
}

public struct ChunkInspectClient: ChunkInspecting {
    public static let maximumResponseBytes = 2_097_152
    private static let engineBaseURL = URL(string: "http://127.0.0.1:8765")!
    private let identity: LocalWorkspaceIdentity
    private let session: URLSession

    public init(identity: LocalWorkspaceIdentity, session: URLSession = .shared) {
        self.identity = identity
        self.session = session
    }

    public func listChunkSets(documentVersionID: String) async throws -> [ChunkSetSummaryDTO] {
        let encoded = documentVersionID.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed)
            ?? documentVersionID
        let url = Self.engineBaseURL
            .appending(
                path: "v1/workspaces/\(identity.workspaceID.uuidString.lowercased())/canonical/\(encoded)/chunk-sets"
            )
        return try await LoopbackJSON.send(
            URLRequest(url: url, method: "GET"),
            identity: identity,
            session: session,
            maximumResponseBytes: Self.maximumResponseBytes
        )
    }

    public func chunkSet(chunkSetID: String) async throws -> ChunkSetEvidenceDTO {
        let encoded = chunkSetID.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? chunkSetID
        let url = Self.engineBaseURL
            .appending(
                path: "v1/workspaces/\(identity.workspaceID.uuidString.lowercased())/chunk-sets/\(encoded)"
            )
        return try await LoopbackJSON.send(
            URLRequest(url: url, method: "GET"),
            identity: identity,
            session: session,
            maximumResponseBytes: Self.maximumResponseBytes
        )
    }
}

enum LoopbackJSON {
    static func send<T: Decodable>(
        _ request: URLRequest,
        identity: LocalWorkspaceIdentity,
        session: URLSession,
        maximumResponseBytes: Int
    ) async throws -> T {
        let data = try await data(
            request,
            identity: identity,
            session: session,
            maximumResponseBytes: maximumResponseBytes
        )
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            throw LoopbackClientError.incompatibleContract
        }
    }

    static func data(
        _ request: URLRequest,
        identity: LocalWorkspaceIdentity,
        session: URLSession,
        maximumResponseBytes: Int
    ) async throws -> Data {
        var request = request
        request.setValue(identity.tenantID.uuidString.lowercased(), forHTTPHeaderField: "x-rsi-tenant-id")
        request.setValue(identity.actorID.uuidString.lowercased(), forHTTPHeaderField: "x-rsi-actor-id")
        request.setValue(UUID().uuidString.lowercased(), forHTTPHeaderField: "x-rsi-trace-id")
        request.setValue("application/json", forHTTPHeaderField: "accept")
        if request.httpBody != nil {
            request.setValue("application/json", forHTTPHeaderField: "content-type")
        }
        do {
            let (data, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse else {
                throw LoopbackClientError.invalidResponse
            }
            guard (200 ..< 300).contains(http.statusCode) else {
                throw LoopbackClientError.httpStatus(http.statusCode)
            }
            guard data.count <= maximumResponseBytes else {
                throw LoopbackClientError.invalidResponse
            }
            return data
        } catch let error as LoopbackClientError {
            throw error
        } catch {
            throw LoopbackClientError.transportUnavailable
        }
    }
}

private extension URLRequest {
    init(url: URL, method: String) {
        self.init(url: url)
        httpMethod = method
    }
}
