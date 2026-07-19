import Foundation

public protocol EngineStatusLoading: Sendable {
    func loadStatus() async throws -> SystemStatus
}

public enum EngineClientError: Error, Equatable, LocalizedError, Sendable {
    case invalidResponse
    case httpStatus(Int)
    case responseTooLarge
    case incompatibleContract
    case authenticationFailed
    case authenticationRequired
    case transportUnavailable

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
        case .authenticationFailed:
            "Local engine IPC authentication failed."
        case .authenticationRequired:
            "Local engine IPC token is missing for Unix-domain transport."
        case .transportUnavailable:
            "The local engine could not be reached. No remote fallback was used."
        }
    }

    public static func from(_ error: LocalEngineHTTPError) -> EngineClientError {
        switch error {
        case .invalidResponse:
            .invalidResponse
        case let .httpStatus(code):
            .httpStatus(code)
        case .responseTooLarge:
            .responseTooLarge
        case .authenticationFailed:
            .authenticationFailed
        case .authenticationRequired:
            .authenticationRequired
        case .transportUnavailable:
            .transportUnavailable
        }
    }
}

public struct EngineClient: EngineStatusLoading {
    public typealias DataLoader = @Sendable (URLRequest) async throws -> (Data, URLResponse)

    public static let maximumResponseBytes = 1_048_576
    private let configuration: LocalEngineConfiguration
    private let dataLoader: DataLoader?

    public init(
        configuration: LocalEngineConfiguration = .resolve(),
        dataLoader: DataLoader? = nil
    ) {
        self.configuration = configuration
        self.dataLoader = dataLoader
    }

    /// Test seam: inject a response loader (loopback URL still used for request shape).
    public init(dataLoader: @escaping DataLoader) {
        configuration = .resolve(environment: ["RSI_ATLAS_ALLOW_LOOPBACK_TCP": "1"])
        self.dataLoader = dataLoader
    }

    public func loadStatus() async throws -> SystemStatus {
        let url = configuration.httpBaseURL.appending(path: "v1/system/status")
        let request = URLRequest(
            url: url,
            cachePolicy: .reloadIgnoringLocalAndRemoteCacheData,
            timeoutInterval: 5
        )
        let data: Data
        let response: URLResponse
        do {
            if let dataLoader {
                (data, response) = try await dataLoader(request)
            } else {
                (data, response) = try await LocalEngineHTTP(configuration: configuration)
                    .perform(request, maximumResponseBytes: Self.maximumResponseBytes)
            }
        } catch is CancellationError {
            throw CancellationError()
        } catch let error as URLError where error.code == .cancelled {
            throw CancellationError()
        } catch let error as LocalEngineHTTPError {
            throw EngineClientError.from(error)
        } catch let error as EngineClientError {
            throw error
        } catch {
            throw EngineClientError.transportUnavailable
        }
        guard let response = response as? HTTPURLResponse else {
            throw EngineClientError.invalidResponse
        }
        guard 200 ..< 300 ~= response.statusCode else {
            if response.statusCode == 401 || response.statusCode == 403 {
                throw EngineClientError.authenticationFailed
            }
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
