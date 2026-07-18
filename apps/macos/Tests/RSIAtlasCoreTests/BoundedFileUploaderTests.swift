import Foundation
import Network
import Testing

@testable import RSIAtlasCore

struct BoundedFileUploaderTests {
    @Test
    func rejectsOversizedResponseFromHeadersBeforeBodyDelivery() async throws {
        let source = privateTestTemporaryDirectory()
            .appending(path: "bounded-upload-\(UUID()).pdf")
        try Data("%PDF-1.7\n%%EOF\n".utf8).write(to: source)
        defer { try? FileManager.default.removeItem(at: source) }

        var request = URLRequest(url: URL(string: "http://127.0.0.1/upload")!)
        request.httpMethod = "POST"
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [OversizedResponseURLProtocol.self]

        await #expect(throws: DocumentImportClientError.responseTooLarge) {
            try await BoundedFileUploader.upload(
                request: request,
                fileURL: source,
                maximumResponseBytes: 1_024,
                configuration: configuration
            )
        }
    }

    @Test
    func cancelsChunkedResponseAsSoonAsAccumulatedBytesExceedLimit() async throws {
        let source = privateTestTemporaryDirectory()
            .appending(path: "bounded-chunked-upload-\(UUID()).pdf")
        try Data("%PDF-1.7\n%%EOF\n".utf8).write(to: source)
        defer { try? FileManager.default.removeItem(at: source) }

        var request = URLRequest(url: URL(string: "http://127.0.0.1/chunked")!)
        request.httpMethod = "POST"
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [OversizedResponseURLProtocol.self]

        await #expect(throws: DocumentImportClientError.responseTooLarge) {
            try await BoundedFileUploader.upload(
                request: request,
                fileURL: source,
                maximumResponseBytes: 1_024,
                configuration: configuration
            )
        }
    }

    @Test
    func rejectsOversizedResponseFromARealLoopbackConnection() async throws {
        let source = privateTestTemporaryDirectory()
            .appending(path: "bounded-loopback-upload-\(UUID()).pdf")
        try Data("%PDF-1.7\n%%EOF\n".utf8).write(to: source)
        defer { try? FileManager.default.removeItem(at: source) }
        let server = try OversizedLoopbackServer(responseBytes: 2_048)
        let port = try await server.start()
        defer { server.stop() }

        var request = URLRequest(
            url: URL(string: "http://127.0.0.1:\(port)/upload")!
        )
        request.httpMethod = "POST"

        await #expect(throws: DocumentImportClientError.responseTooLarge) {
            try await BoundedFileUploader.upload(
                request: request,
                fileURL: source,
                maximumResponseBytes: 1_024
            )
        }
    }
}

private final class OversizedLoopbackServer: @unchecked Sendable {
    private let listener: NWListener
    private let queue = DispatchQueue(label: "BoundedFileUploaderTests.loopback")
    private let responseBytes: Int
    private let lock = NSLock()
    private var startContinuation: CheckedContinuation<UInt16, any Error>?
    private var started = false

    init(responseBytes: Int) throws {
        listener = try NWListener(using: .tcp, on: .any)
        self.responseBytes = responseBytes
    }

    func start() async throws -> UInt16 {
        try await withCheckedThrowingContinuation { continuation in
            lock.lock()
            startContinuation = continuation
            lock.unlock()
            listener.stateUpdateHandler = { [weak self] state in
                self?.handle(state)
            }
            listener.newConnectionHandler = { [weak self] connection in
                self?.handle(connection)
            }
            listener.start(queue: queue)
        }
    }

    func stop() {
        listener.cancel()
    }

    private func handle(_ state: NWListener.State) {
        switch state {
        case .ready:
            guard let port = listener.port?.rawValue else { return }
            finishStart(.success(port))
        case let .failed(error):
            finishStart(.failure(error))
        default:
            break
        }
    }

    private func finishStart(_ result: Result<UInt16, any Error>) {
        lock.lock()
        guard !started else {
            lock.unlock()
            return
        }
        started = true
        let continuation = startContinuation
        startContinuation = nil
        lock.unlock()
        continuation?.resume(with: result)
    }

    private func handle(_ connection: NWConnection) {
        connection.start(queue: queue)
        connection.receive(minimumIncompleteLength: 1, maximumLength: 64 * 1_024) {
            [responseBytes] _, _, _, _ in
            var response = Data(
                "HTTP/1.1 200 OK\r\nContent-Length: \(responseBytes)\r\nConnection: close\r\n\r\n"
                    .utf8
            )
            response.append(Data(repeating: 0x41, count: responseBytes))
            connection.send(content: response, completion: .contentProcessed { _ in
                connection.cancel()
            })
        }
    }
}

private final class OversizedResponseURLProtocol: URLProtocol, @unchecked Sendable {
    private let lock = NSLock()
    private var stopped = false

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        if request.url?.path == "/chunked" {
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: "HTTP/1.1",
                headerFields: nil
            )!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: Data(repeating: 0x41, count: 600))
            client?.urlProtocol(self, didLoad: Data(repeating: 0x42, count: 600))
            client?.urlProtocolDidFinishLoading(self)
            return
        }
        let response = HTTPURLResponse(
            url: request.url!,
            statusCode: 200,
            httpVersion: "HTTP/1.1",
            headerFields: ["Content-Length": "2048"]
        )!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        lock.lock()
        let shouldDeliverBody = !stopped
        lock.unlock()
        if shouldDeliverBody {
            client?.urlProtocol(self, didLoad: Data(repeating: 0x41, count: 2_048))
            client?.urlProtocolDidFinishLoading(self)
        }
    }

    override func stopLoading() {
        lock.lock()
        stopped = true
        lock.unlock()
    }
}

private func privateTestTemporaryDirectory() -> URL {
    let directory = FileManager.default.temporaryDirectory
    guard directory.path.hasPrefix("/var/") else { return directory }
    return URL(filePath: "/private\(directory.path)", directoryHint: .isDirectory)
}
