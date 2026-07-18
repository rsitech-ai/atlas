import Observation

public enum CommandCenterFailure: Sendable, Equatable {
    case unavailable
    case invalidResponse
    case httpStatus(Int)
    case responseTooLarge
    case incompatibleContract

    public var title: String {
        switch self {
        case .unavailable:
            "Engine unavailable"
        case .invalidResponse, .httpStatus:
            "Engine response failed"
        case .responseTooLarge, .incompatibleContract:
            "Status contract rejected"
        }
    }

    public var message: String {
        switch self {
        case .unavailable:
            "The local engine could not be reached. No remote fallback was used."
        case .invalidResponse:
            "The local endpoint did not return an HTTP response."
        case let .httpStatus(statusCode):
            "The local engine returned HTTP \(statusCode)."
        case .responseTooLarge:
            "The local engine status exceeded the safe response limit."
        case .incompatibleContract:
            "The local engine returned an incompatible status contract."
        }
    }
}

public enum CommandCenterLoadState: Sendable, Equatable {
    case idle
    case loading
    case loaded(
        status: SystemStatus,
        isRefreshing: Bool,
        refreshFailure: CommandCenterFailure?
    )
    case failed(CommandCenterFailure)

    var currentStatus: SystemStatus? {
        guard case let .loaded(status, _, _) = self else { return nil }
        return status
    }
}

@MainActor
@Observable
public final class CommandCenterStore {
    public private(set) var state: CommandCenterLoadState = .idle
    private let loader: any EngineStatusLoading
    private var reloadGeneration = 0

    public init(loader: any EngineStatusLoading) {
        self.loader = loader
    }

    public func reload() async {
        reloadGeneration += 1
        let generation = reloadGeneration
        let priorStatus = state.currentStatus
        if let priorStatus {
            state = .loaded(status: priorStatus, isRefreshing: true, refreshFailure: nil)
        } else {
            state = .loading
        }
        do {
            let status = try await loader.loadStatus()
            guard generation == reloadGeneration else { return }
            state = .loaded(status: status, isRefreshing: false, refreshFailure: nil)
        } catch is CancellationError {
            guard generation == reloadGeneration else { return }
            if let priorStatus {
                state = .loaded(status: priorStatus, isRefreshing: false, refreshFailure: nil)
            } else {
                state = .idle
            }
        } catch {
            guard generation == reloadGeneration else { return }
            let failure = Self.failure(for: error)
            if let priorStatus {
                state = .loaded(
                    status: priorStatus,
                    isRefreshing: false,
                    refreshFailure: failure
                )
            } else {
                state = .failed(failure)
            }
        }
    }

    private static func failure(for error: any Error) -> CommandCenterFailure {
        guard let clientError = error as? EngineClientError else {
            return .unavailable
        }
        switch clientError {
        case .invalidResponse:
            return .invalidResponse
        case let .httpStatus(statusCode):
            return .httpStatus(statusCode)
        case .responseTooLarge:
            return .responseTooLarge
        case .incompatibleContract:
            return .incompatibleContract
        }
    }
}
