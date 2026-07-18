import Observation

public enum CommandCenterLoadState: Sendable, Equatable {
    case idle
    case loading
    case loaded(SystemStatus)
    case failed(message: String)
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
        state = .loading
        do {
            let status = try await loader.loadStatus()
            guard generation == reloadGeneration else { return }
            state = .loaded(status)
        } catch {
            guard generation == reloadGeneration else { return }
            state = .failed(message: "RSI Atlas Engine is unavailable.")
        }
    }
}
