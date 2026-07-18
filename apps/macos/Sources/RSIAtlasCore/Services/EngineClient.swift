import Foundation

public protocol EngineStatusLoading: Sendable {
    func loadStatus() async throws -> SystemStatus
}

public enum EngineClientError: Error, Equatable, LocalizedError {
    case invalidResponse
    case httpStatus(Int)

    public var errorDescription: String? {
        switch self {
        case .invalidResponse:
            "The local engine returned an invalid response."
        case let .httpStatus(statusCode):
            "The local engine returned HTTP \(statusCode)."
        }
    }
}

public struct EngineClient: EngineStatusLoading {
    public typealias DataLoader = @Sendable (URLRequest) async throws -> (Data, URLResponse)

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
        return try SystemStatus.decoder.decode(SystemStatus.self, from: data)
    }
}
