import Foundation

/// Resolved local-engine IPC endpoint (Unix domain by default; TCP only behind explicit flag).
public struct LocalEngineConfiguration: Sendable, Equatable {
    public enum Mode: Sendable, Equatable {
        case unixDomain(socketPath: URL)
        case loopbackTCP(baseURL: URL)
    }

    public let mode: Mode
    public let tokenPath: URL
    public let token: String?

    /// Synthetic HTTP base used when dialing a Unix socket (host is never resolved).
    public static let unixSyntheticBaseURL = URL(string: "http://localhost")!

    public var httpBaseURL: URL {
        switch mode {
        case let .loopbackTCP(baseURL):
            baseURL
        case .unixDomain:
            Self.unixSyntheticBaseURL
        }
    }

    public var usesUnixDomain: Bool {
        if case .unixDomain = mode { true } else { false }
    }

    public init(mode: Mode, tokenPath: URL, token: String?) {
        self.mode = mode
        self.tokenPath = tokenPath
        self.token = token
    }

    /// Resolve IPC policy from the process environment.
    ///
    /// - Default / release: Unix domain socket under `$DATA_ROOT/ipc/engine.sock` + token file.
    /// - Loopback TCP only when `RSI_ATLAS_ALLOW_LOOPBACK_TCP=1` (tests/dev).
    public static func resolve(
        environment: [String: String] = ProcessInfo.processInfo.environment,
        homeDirectory: URL? = nil
    ) -> LocalEngineConfiguration {
        let dataRoot = resolveDataRoot(environment: environment, homeDirectory: homeDirectory)
        let ipcDir = dataRoot.appending(path: "ipc", directoryHint: .isDirectory)
        let tokenPath = ipcDir.appending(path: "engine.token")
        let token = loadToken(at: tokenPath)
        let releaseMode = isTruthy(environment["RSI_ATLAS_RELEASE_IPC"])
        let allowTCP = isTruthy(environment["RSI_ATLAS_ALLOW_LOOPBACK_TCP"])
        if releaseMode || !allowTCP {
            let socketPath = ipcDir.appending(path: "engine.sock")
            return LocalEngineConfiguration(
                mode: .unixDomain(socketPath: socketPath),
                tokenPath: tokenPath,
                token: token
            )
        }
        let host = (environment["RSI_ATLAS_ENGINE_HOST"] ?? "127.0.0.1").trimmingCharacters(
            in: .whitespacesAndNewlines
        )
        let allowedHosts: Set<String> = ["127.0.0.1", "::1", "localhost"]
        let safeHost = allowedHosts.contains(host) ? host : "127.0.0.1"
        let port = Int(environment["RSI_ATLAS_ENGINE_PORT"] ?? "8765") ?? 8765
        let clamped = (1 ... 65_535).contains(port) ? port : 8765
        let base = URL(string: "http://\(safeHost):\(clamped)")!
        return LocalEngineConfiguration(
            mode: .loopbackTCP(baseURL: base),
            tokenPath: tokenPath,
            token: token
        )
    }

    private static func resolveDataRoot(
        environment: [String: String],
        homeDirectory: URL?
    ) -> URL {
        if let raw = environment["RSI_ATLAS_DATA_ROOT"]?
            .trimmingCharacters(in: .whitespacesAndNewlines),
            !raw.isEmpty
        {
            return URL(fileURLWithPath: raw, isDirectory: true)
        }
        let home = homeDirectory
            ?? FileManager.default.homeDirectoryForCurrentUser
        return home
            .appending(path: "Library/Application Support/ai.rsitech.RSIAtlas", directoryHint: .isDirectory)
    }

    private static func loadToken(at path: URL) -> String? {
        guard let raw = try? String(contentsOf: path, encoding: .utf8) else {
            return nil
        }
        let token = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        return token.isEmpty ? nil : token
    }

    private static func isTruthy(_ value: String?) -> Bool {
        guard let value else { return false }
        switch value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "1", "true", "yes", "on":
            return true
        default:
            return false
        }
    }
}
