import Foundation
import Testing

@testable import RSIAtlasCore

struct LocalEngineSupervisorTests {
    @Test
    func launchesExactExecutableWithAllowlistedEnvironmentAndStopsByInterrupt() async throws {
        let root = FileManager.default.temporaryDirectory
            .appending(path: "rsi-supervisor-\(UUID().uuidString)", directoryHint: .isDirectory)
        let executable = root.appending(path: "RSIAtlasEngine")
        let data = root.appending(path: "data", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        try """
        #!/bin/sh
        printf '%s\n' "$@" > "$RSI_ATLAS_DATA_ROOT/arguments.txt"
        /usr/bin/env > "$RSI_ATLAS_DATA_ROOT/environment.txt"
        trap 'exit 0' INT
        while true; do /bin/sleep 1; done
        """.write(to: executable, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o700],
            ofItemAtPath: executable.path
        )
        let supervisor = LocalEngineSupervisor(
            launchConfiguration: LocalEngineLaunchConfiguration(
                engineExecutable: executable,
                dataRoot: data
            ),
            readinessProbe: { _ in
                guard FileManager.default.fileExists(
                    atPath: data.appending(path: "arguments.txt").path
                ) else {
                    throw LocalEngineSupervisorError.readinessTimedOut
                }
            }
        )

        try await supervisor.startAndWait(timeoutSeconds: 3)

        #expect(await supervisor.isRunning())
        let arguments = try String(
            contentsOf: data.appending(path: "arguments.txt"),
            encoding: .utf8
        )
        #expect(arguments.split(whereSeparator: \.isNewline) == ["serve", "--release-ipc"])
        let environment = try String(
            contentsOf: data.appending(path: "environment.txt"),
            encoding: .utf8
        )
        #expect(environment.contains("RSI_ATLAS_RELEASE_IPC=1"))
        #expect(environment.contains("RSI_ATLAS_DATA_ROOT=\(data.path)"))
        #expect(!environment.contains("PYTHONPATH="))
        #expect(!environment.contains("DYLD_INSERT_LIBRARIES="))

        await supervisor.stop(graceSeconds: 3)
        #expect(!(await supervisor.isRunning()))
    }

    @Test
    func releaseConfigurationUsesOnlyBundleRelativeEngineAndApplicationSupportData() {
        let bundle = URL(fileURLWithPath: "/Applications/RSIAtlas.app", isDirectory: true)
        let home = URL(fileURLWithPath: "/Users/tester", isDirectory: true)

        let configuration = LocalEngineLaunchConfiguration.release(
            bundleURL: bundle,
            environment: [:],
            homeDirectory: home
        )

        #expect(
            configuration.engineExecutable.path
                == "/Applications/RSIAtlas.app/Contents/MacOS/RSIAtlasEngine"
        )
        #expect(
            configuration.dataRoot.path
                == "/Users/tester/Library/Application Support/ai.rsitech.RSIAtlas"
        )
    }

    @Test
    func restartCooldownFailsClosedAfterAStoppedLaunch() async throws {
        let root = FileManager.default.temporaryDirectory
            .appending(path: "rsi-supervisor-\(UUID().uuidString)", directoryHint: .isDirectory)
        let executable = root.appending(path: "RSIAtlasEngine")
        let data = root.appending(path: "data", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        try "#!/bin/sh\ntrap 'exit 0' INT\nwhile true; do /bin/sleep 1; done\n".write(
            to: executable,
            atomically: true,
            encoding: .utf8
        )
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o700],
            ofItemAtPath: executable.path
        )
        let supervisor = LocalEngineSupervisor(
            launchConfiguration: LocalEngineLaunchConfiguration(
                engineExecutable: executable,
                dataRoot: data
            ),
            readinessProbe: { _ in }
        )
        try await supervisor.startAndWait(timeoutSeconds: 2)
        await supervisor.stop(graceSeconds: 3)

        await #expect(throws: LocalEngineSupervisorError.restartCooldown) {
            try await supervisor.startAndWait(timeoutSeconds: 2)
        }
    }
}
