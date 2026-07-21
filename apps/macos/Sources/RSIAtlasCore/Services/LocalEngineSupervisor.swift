import Darwin
import Foundation

public enum LocalEngineSupervisorError: Error, Equatable, Sendable {
    case executableMissing
    case launchFailed
    case exitedBeforeReady(Int32)
    case readinessTimedOut
    case restartCooldown
    case restartLimit
}

public struct LocalEngineLaunchConfiguration: Sendable, Equatable {
    public let engineExecutable: URL
    public let dataRoot: URL

    public init(engineExecutable: URL, dataRoot: URL) {
        self.engineExecutable = engineExecutable
        self.dataRoot = dataRoot
    }

    public static func release(
        bundleURL: URL = Bundle.main.bundleURL,
        environment: [String: String] = ProcessInfo.processInfo.environment,
        homeDirectory: URL? = nil
    ) -> LocalEngineLaunchConfiguration {
        let ipc = LocalEngineConfiguration.resolve(
            environment: environment,
            homeDirectory: homeDirectory
        )
        let dataRoot = ipc.tokenPath
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        return LocalEngineLaunchConfiguration(
            engineExecutable: bundleURL
                .appending(path: "Contents", directoryHint: .isDirectory)
                .appending(path: "MacOS", directoryHint: .isDirectory)
                .appending(path: "RSIAtlasEngine"),
            dataRoot: dataRoot
        )
    }
}

public actor LocalEngineSupervisor {
    public typealias ReadinessProbe = @Sendable (LocalEngineConfiguration) async throws -> Void

    private let launchConfiguration: LocalEngineLaunchConfiguration
    private let readinessProbe: ReadinessProbe
    private var process: Process?
    private var logHandle: FileHandle?
    private var startAttempts: [Date] = []

    public init(
        launchConfiguration: LocalEngineLaunchConfiguration = .release(),
        readinessProbe: @escaping ReadinessProbe = { configuration in
            _ = try await EngineClient(configuration: configuration).loadStatus()
        }
    ) {
        self.launchConfiguration = launchConfiguration
        self.readinessProbe = readinessProbe
    }

    public func startAndWait(timeoutSeconds: TimeInterval = 20) async throws {
        if process?.isRunning == true {
            return
        }
        let now = Date()
        startAttempts.removeAll { now.timeIntervalSince($0) >= 60 }
        if startAttempts.count >= 3 {
            throw LocalEngineSupervisorError.restartLimit
        }
        if let last = startAttempts.last, now.timeIntervalSince(last) < 1 {
            throw LocalEngineSupervisorError.restartCooldown
        }
        startAttempts.append(now)
        guard FileManager.default.isExecutableFile(atPath: launchConfiguration.engineExecutable.path) else {
            throw LocalEngineSupervisorError.executableMissing
        }
        try prepareDataRoot()
        let child = Process()
        child.executableURL = launchConfiguration.engineExecutable
        child.arguments = ["serve", "--release-ipc"]
        child.currentDirectoryURL = launchConfiguration.dataRoot
        child.environment = childEnvironment()
        let handle = try openLog()
        child.standardOutput = handle
        child.standardError = handle
        do {
            try child.run()
        } catch {
            try? handle.close()
            throw LocalEngineSupervisorError.launchFailed
        }
        process = child
        logHandle = handle
        let environment = child.environment ?? [:]
        let ipc = LocalEngineConfiguration.resolve(
            environment: environment,
            homeDirectory: launchConfiguration.dataRoot
        )
        let deadline = Date().addingTimeInterval(timeoutSeconds)
        do {
            while Date() < deadline {
                guard child.isRunning else {
                    throw LocalEngineSupervisorError.exitedBeforeReady(child.terminationStatus)
                }
                do {
                    try await readinessProbe(ipc)
                    return
                } catch {
                    try await Task.sleep(for: .milliseconds(100))
                }
            }
            throw LocalEngineSupervisorError.readinessTimedOut
        } catch {
            await stop()
            throw error
        }
    }

    public func stop(graceSeconds: TimeInterval = 10) async {
        guard let child = process else { return }
        if child.isRunning {
            child.interrupt()
            await waitUntilExit(child, seconds: graceSeconds)
        }
        if child.isRunning {
            child.terminate()
            await waitUntilExit(child, seconds: 2)
        }
        if child.isRunning {
            let ownedPID = child.processIdentifier
            if ownedPID > 1, child.processIdentifier == ownedPID {
                Darwin.kill(ownedPID, SIGKILL)
            }
            await waitUntilExit(child, seconds: 2)
        }
        if !child.isRunning {
            child.waitUntilExit()
        }
        try? logHandle?.close()
        logHandle = nil
        process = nil
    }

    public func isRunning() -> Bool {
        process?.isRunning == true
    }

    private func prepareDataRoot() throws {
        let manager = FileManager.default
        try manager.createDirectory(
            at: launchConfiguration.dataRoot,
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        try manager.setAttributes(
            [.posixPermissions: 0o700],
            ofItemAtPath: launchConfiguration.dataRoot.path
        )
        let temporary = launchConfiguration.dataRoot.appending(
            path: "tmp",
            directoryHint: .isDirectory
        )
        try manager.createDirectory(
            at: temporary,
            withIntermediateDirectories: false,
            attributes: [.posixPermissions: 0o700]
        )
    }

    private func childEnvironment() -> [String: String] {
        let dataRoot = launchConfiguration.dataRoot.path
        return [
            "HOME": FileManager.default.homeDirectoryForCurrentUser.path,
            "PATH": "/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
            "RSI_ATLAS_DATA_ROOT": dataRoot,
            "RSI_ATLAS_RELEASE_IPC": "1",
            "TMPDIR": launchConfiguration.dataRoot.appending(path: "tmp").path,
        ]
    }

    private func openLog() throws -> FileHandle {
        let logs = launchConfiguration.dataRoot.appending(path: "logs", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(
            at: logs,
            withIntermediateDirectories: false,
            attributes: [.posixPermissions: 0o700]
        )
        let log = logs.appending(path: "engine.log")
        if !FileManager.default.fileExists(atPath: log.path) {
            FileManager.default.createFile(atPath: log.path, contents: nil)
        }
        let handle = try FileHandle(forWritingTo: log)
        try handle.seekToEnd()
        return handle
    }

    private func waitUntilExit(_ child: Process, seconds: TimeInterval) async {
        let deadline = Date().addingTimeInterval(seconds)
        while child.isRunning, Date() < deadline {
            try? await Task.sleep(for: .milliseconds(50))
        }
    }
}
