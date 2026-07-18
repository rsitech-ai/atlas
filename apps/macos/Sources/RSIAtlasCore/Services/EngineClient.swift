import Foundation

public protocol EngineStatusLoading: Sendable {
    func loadStatus() async throws -> SystemStatus
}

public enum EngineClientError: Error, Equatable, LocalizedError, Sendable {
    case invalidResponse
    case httpStatus(Int)
    case responseTooLarge
    case incompatibleContract

    public var errorDescription: String? {
        switch self {
        case .invalidResponse:
            "The local engine returned an invalid response."
        case let .httpStatus(statusCode):
            "The local engine returned HTTP \(statusCode)."
        case .responseTooLarge:
            "The local engine status exceeded the safe response limit."
        case .incompatibleContract:
            "The local engine returned an incompatible status contract."
        }
    }
}

public struct EngineClient: EngineStatusLoading {
    public typealias DataLoader = @Sendable (URLRequest) async throws -> (Data, URLResponse)

    public static let maximumResponseBytes = 1_048_576
    private static let statusURL = URL(string: "http://127.0.0.1:8765/v1/system/status")!
    private let dataLoader: DataLoader

    public init(
        dataLoader: @escaping DataLoader = { request in
            try await URLSession.shared.data(for: request)
        }
    ) {
        self.dataLoader = dataLoader
    }

    public func loadStatus() async throws -> SystemStatus {
        let request = URLRequest(
            url: Self.statusURL,
            cachePolicy: .reloadIgnoringLocalAndRemoteCacheData,
            timeoutInterval: 5
        )
        let (data, response) = try await dataLoader(request)
        guard let response = response as? HTTPURLResponse else {
            throw EngineClientError.invalidResponse
        }
        guard 200 ..< 300 ~= response.statusCode else {
            throw EngineClientError.httpStatus(response.statusCode)
        }
        guard data.count <= Self.maximumResponseBytes else {
            throw EngineClientError.responseTooLarge
        }
        do {
            return try SystemStatus.decoder.decode(SystemStatus.self, from: data)
        } catch is DecodingError {
            throw EngineClientError.incompatibleContract
        }
    }
}
