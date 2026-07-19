import Darwin
import Foundation
import Testing

@testable import RSIAtlasCore

struct LocalEngineConfigurationTests {
    @Test
    func defaultsToUnixDomainWithoutTCPFlag() {
        let home = FileManager.default.temporaryDirectory
            .appending(path: "rsi-atlas-config-\(UUID().uuidString)", directoryHint: .isDirectory)
        try? FileManager.default.createDirectory(at: home, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: home) }

        let config = LocalEngineConfiguration.resolve(
            environment: [:],
            homeDirectory: home
        )
        guard case let .unixDomain(socketPath) = config.mode else {
            Issue.record("expected unix domain mode")
            return
        }
        #expect(socketPath.lastPathComponent == "engine.sock")
        #expect(config.tokenPath.lastPathComponent == "engine.token")
        #expect(config.usesUnixDomain)
    }

    @Test
    func releaseIPCForcesUnixEvenWhenTCPFlagSet() {
        let config = LocalEngineConfiguration.resolve(
            environment: [
                "RSI_ATLAS_RELEASE_IPC": "1",
                "RSI_ATLAS_ALLOW_LOOPBACK_TCP": "1",
                "RSI_ATLAS_DATA_ROOT": "/tmp/rsi-atlas-release",
            ]
        )
        #expect(config.usesUnixDomain)
    }

    @Test
    func loopbackTCPRequiresExplicitFlag() {
        let config = LocalEngineConfiguration.resolve(
            environment: [
                "RSI_ATLAS_ALLOW_LOOPBACK_TCP": "1",
                "RSI_ATLAS_DATA_ROOT": "/tmp/rsi-atlas-unused",
                "RSI_ATLAS_ENGINE_PORT": "9876",
            ]
        )
        guard case let .loopbackTCP(baseURL) = config.mode else {
            Issue.record("expected loopback TCP mode")
            return
        }
        #expect(baseURL.absoluteString == "http://127.0.0.1:9876")
        #expect(!config.usesUnixDomain)
    }
}

struct LocalEngineHTTPTests {
    @Test
    func unixDomainConnectsWithBearerToken() async throws {
        let root = privateIPCRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let socketPath = root.appending(path: "engine.sock")
        let tokenPath = root.appending(path: "engine.token")
        let token = "test-token-\(UUID().uuidString)-pad-to-32-chars"
        try token.write(to: tokenPath, atomically: true, encoding: .utf8)

        let server = try UnixHTTPTestServer(
            socketPath: socketPath.path,
            expectedAuthorization: "Bearer \(token)",
            responseStatus: 200,
            responseBody: #"{"ok":true}"#
        )
        try await server.start()
        defer { server.stop() }

        let configuration = LocalEngineConfiguration(
            mode: .unixDomain(socketPath: socketPath),
            tokenPath: tokenPath,
            token: token
        )
        let http = LocalEngineHTTP(configuration: configuration)
        var request = URLRequest(url: configuration.httpBaseURL.appending(path: "v1/system/status"))
        request.httpMethod = "GET"
        let (data, response) = try await http.perform(request, maximumResponseBytes: 1_024)
        #expect(response.statusCode == 200)
        #expect(String(data: data, encoding: .utf8) == #"{"ok":true}"#)
    }

    @Test
    func unixDomainAuthFailureMapsToAuthenticationFailed() async throws {
        let root = privateIPCRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let socketPath = root.appending(path: "engine.sock")
        let tokenPath = root.appending(path: "engine.token")
        let token = "client-token-\(UUID().uuidString)-pad-to-32-chars"
        try token.write(to: tokenPath, atomically: true, encoding: .utf8)

        let server = try UnixHTTPTestServer(
            socketPath: socketPath.path,
            expectedAuthorization: nil,
            responseStatus: 401,
            responseBody: #"{"detail":"IPC authentication failed."}"#
        )
        try await server.start()
        defer { server.stop() }

        let configuration = LocalEngineConfiguration(
            mode: .unixDomain(socketPath: socketPath),
            tokenPath: tokenPath,
            token: token
        )
        let http = LocalEngineHTTP(configuration: configuration)
        var request = URLRequest(url: configuration.httpBaseURL.appending(path: "v1/system/status"))
        request.httpMethod = "GET"
        await #expect(throws: LocalEngineHTTPError.authenticationFailed) {
            _ = try await http.perform(request, maximumResponseBytes: 1_024)
        }
    }

    @Test
    func unixDomainMissingTokenFailsClosed() async {
        let configuration = LocalEngineConfiguration(
            mode: .unixDomain(socketPath: URL(fileURLWithPath: "/tmp/missing.sock")),
            tokenPath: URL(fileURLWithPath: "/tmp/missing.token"),
            token: nil
        )
        let http = LocalEngineHTTP(configuration: configuration)
        var request = URLRequest(url: configuration.httpBaseURL.appending(path: "v1/system/status"))
        request.httpMethod = "GET"
        await #expect(throws: LocalEngineHTTPError.authenticationRequired) {
            _ = try await http.perform(request, maximumResponseBytes: 1_024)
        }
    }
}

private func privateIPCRoot() -> URL {
    // Keep under sockaddr_un.sun_path (104) — nested UUID temp dirs are too long.
    let root = URL(fileURLWithPath: "/tmp/rsi-ipc-\(UUID().uuidString.prefix(8))", isDirectory: true)
    try? FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    return root
}

/// Minimal AF_UNIX HTTP/1.1 server for transport tests.
private final class UnixHTTPTestServer: @unchecked Sendable {
    private let socketPath: String
    private let expectedAuthorization: String?
    private let responseStatus: Int
    private let responseBody: String
    private let queue = DispatchQueue(label: "LocalEngineHTTPTests.uds")
    private var listenFD: Int32 = -1
    private var running = false

    init(
        socketPath: String,
        expectedAuthorization: String?,
        responseStatus: Int,
        responseBody: String
    ) throws {
        self.socketPath = socketPath
        self.expectedAuthorization = expectedAuthorization
        self.responseStatus = responseStatus
        self.responseBody = responseBody
        unlink(socketPath)
    }

    func start() async throws {
        listenFD = socket(AF_UNIX, SOCK_STREAM, 0)
        guard listenFD >= 0 else {
            throw LocalEngineHTTPError.transportUnavailable
        }
        var addr = sockaddr_un()
        addr.sun_family = sa_family_t(AF_UNIX)
        let pathBytes = socketPath.utf8CString
        guard pathBytes.count <= MemoryLayout.size(ofValue: addr.sun_path) else {
            throw LocalEngineHTTPError.transportUnavailable
        }
        withUnsafeMutablePointer(to: &addr.sun_path) { pointer in
            pointer.withMemoryRebound(to: CChar.self, capacity: pathBytes.count) { dest in
                for (index, byte) in pathBytes.enumerated() {
                    dest[index] = byte
                }
            }
        }
        let bindResult = withUnsafePointer(to: &addr) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { sockAddr in
                Darwin.bind(listenFD, sockAddr, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }
        guard bindResult == 0, listen(listenFD, 4) == 0 else {
            throw LocalEngineHTTPError.transportUnavailable
        }
        running = true
        queue.async { [weak self] in
            self?.acceptLoop()
        }
        // Brief settle so connect finds a listener.
        try await Task.sleep(nanoseconds: 50_000_000)
    }

    func stop() {
        running = false
        if listenFD >= 0 {
            close(listenFD)
            listenFD = -1
        }
        unlink(socketPath)
    }

    private func acceptLoop() {
        while running {
            let client = accept(listenFD, nil, nil)
            if client < 0 {
                continue
            }
            handle(client: client)
        }
    }

    private func handle(client: Int32) {
        defer { close(client) }
        var buffer = [UInt8](repeating: 0, count: 64 * 1_024)
        let readCount = read(client, &buffer, buffer.count)
        guard readCount > 0 else { return }
        let request = String(bytes: buffer.prefix(readCount), encoding: .utf8) ?? ""
        if let expectedAuthorization {
            guard request.contains("Authorization: \(expectedAuthorization)") else {
                let body = #"{"detail":"IPC authentication failed."}"#
                let response = Data(
                    "HTTP/1.1 401 Unauthorized\r\nContent-Length: \(body.utf8.count)\r\nConnection: close\r\n\r\n\(body)"
                        .utf8
                )
                _ = response.withUnsafeBytes { write(client, $0.baseAddress, response.count) }
                return
            }
        }
        let reason = responseStatus == 200 ? "OK" : "Error"
        let response = Data(
            "HTTP/1.1 \(responseStatus) \(reason)\r\nContent-Length: \(responseBody.utf8.count)\r\nConnection: close\r\n\r\n\(responseBody)"
                .utf8
        )
        _ = response.withUnsafeBytes { write(client, $0.baseAddress, response.count) }
    }
}
