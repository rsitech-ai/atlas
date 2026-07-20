import Darwin
import Foundation

public enum LocalEngineHTTPError: Error, Equatable, LocalizedError, Sendable {
    case transportUnavailable
    case authenticationFailed
    case authenticationRequired
    case invalidResponse
    case httpStatus(Int)
    case responseTooLarge

    public var errorDescription: String? {
        switch self {
        case .transportUnavailable:
            "The local engine could not be reached. No remote fallback was used."
        case .authenticationFailed:
            "Local engine IPC authentication failed."
        case .authenticationRequired:
            "Local engine IPC token is missing for Unix-domain transport."
        case .invalidResponse:
            "The local engine returned an invalid response."
        case let .httpStatus(code):
            "The local engine returned HTTP \(code)."
        case .responseTooLarge:
            "The local engine response exceeded the safe limit."
        }
    }
}

/// Authenticated local-engine HTTP client: Unix domain by default, loopback TCP only behind flag.
public struct LocalEngineHTTP: Sendable {
    public let configuration: LocalEngineConfiguration
    private let urlSession: URLSession

    public init(
        configuration: LocalEngineConfiguration = .resolve(),
        urlSession: URLSession = .shared
    ) {
        self.configuration = configuration
        self.urlSession = urlSession
    }

    public func perform(
        _ request: URLRequest,
        maximumResponseBytes: Int
    ) async throws -> (Data, HTTPURLResponse) {
        var request = request
        applyAuth(&request)
        switch configuration.mode {
        case let .loopbackTCP(baseURL):
            return try await performTCP(
                request,
                baseURL: baseURL,
                maximumResponseBytes: maximumResponseBytes
            )
        case let .unixDomain(socketPath):
            guard let token = configuration.currentToken(), !token.isEmpty else {
                throw LocalEngineHTTPError.authenticationRequired
            }
            _ = token
            return try await performUnix(
                request,
                socketPath: socketPath,
                maximumResponseBytes: maximumResponseBytes
            )
        }
    }

    public func uploadFile(
        _ request: URLRequest,
        fileURL: URL,
        maximumResponseBytes: Int
    ) async throws -> (Data, HTTPURLResponse) {
        var request = request
        applyAuth(&request)
        switch configuration.mode {
        case .loopbackTCP:
            let (data, response) = try await BoundedFileUploader.upload(
                request: request,
                fileURL: fileURL,
                maximumResponseBytes: maximumResponseBytes
            )
            guard let http = response as? HTTPURLResponse else {
                throw LocalEngineHTTPError.invalidResponse
            }
            try mapStatus(http.statusCode)
            return (data, http)
        case let .unixDomain(socketPath):
            guard configuration.currentToken() != nil else {
                throw LocalEngineHTTPError.authenticationRequired
            }
            let body = try Data(contentsOf: fileURL)
            request.httpBody = body
            if request.value(forHTTPHeaderField: "Content-Length") == nil {
                request.setValue(String(body.count), forHTTPHeaderField: "Content-Length")
            }
            return try await performUnix(
                request,
                socketPath: socketPath,
                maximumResponseBytes: maximumResponseBytes
            )
        }
    }

    private func applyAuth(_ request: inout URLRequest) {
        guard let token = configuration.currentToken(), !token.isEmpty else { return }
        if request.value(forHTTPHeaderField: "Authorization") == nil {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
    }

    private func performTCP(
        _ request: URLRequest,
        baseURL: URL,
        maximumResponseBytes: Int
    ) async throws -> (Data, HTTPURLResponse) {
        var request = request
        if let url = request.url {
            request.url = rebase(url, onto: baseURL)
        }
        do {
            let (data, response) = try await urlSession.data(for: request)
            guard let http = response as? HTTPURLResponse else {
                throw LocalEngineHTTPError.invalidResponse
            }
            guard data.count <= maximumResponseBytes else {
                throw LocalEngineHTTPError.responseTooLarge
            }
            try mapStatus(http.statusCode)
            return (data, http)
        } catch let error as LocalEngineHTTPError {
            throw error
        } catch is CancellationError {
            throw CancellationError()
        } catch let error as URLError where error.code == .cancelled {
            throw CancellationError()
        } catch {
            throw LocalEngineHTTPError.transportUnavailable
        }
    }

    private func performUnix(
        _ request: URLRequest,
        socketPath: URL,
        maximumResponseBytes: Int
    ) async throws -> (Data, HTTPURLResponse) {
        guard let url = request.url else {
            throw LocalEngineHTTPError.invalidResponse
        }
        let method = (request.httpMethod ?? "GET").uppercased()
        let path = url.path.isEmpty ? "/" : url.path
        let pathAndQuery = url.query.map { "\(path)?\($0)" } ?? path
        var headerLines: [String] = [
            "\(method) \(pathAndQuery) HTTP/1.1",
            "Host: localhost",
            "Connection: close",
        ]
        if let headers = request.allHTTPHeaderFields {
            for (key, value) in headers where key.lowercased() != "host" {
                headerLines.append("\(key): \(value)")
            }
        }
        let body = request.httpBody ?? Data()
        if request.value(forHTTPHeaderField: "Content-Length") == nil, !body.isEmpty {
            headerLines.append("Content-Length: \(body.count)")
        }
        var message = Data((headerLines.joined(separator: "\r\n") + "\r\n\r\n").utf8)
        message.append(body)

        let raw = try await Task.detached(priority: .userInitiated) {
            try UnixHTTPConnection.exchangeBlocking(
                socketPath: socketPath.path,
                request: message,
                maximumResponseBytes: maximumResponseBytes + 64 * 1_024
            )
        }.value
        let (status, headerFields, responseBody) = try HTTPMessageParser.parse(raw)
        guard responseBody.count <= maximumResponseBytes else {
            throw LocalEngineHTTPError.responseTooLarge
        }
        try mapStatus(status)
        guard let http = HTTPURLResponse(
            url: url,
            statusCode: status,
            httpVersion: "HTTP/1.1",
            headerFields: headerFields
        ) else {
            throw LocalEngineHTTPError.invalidResponse
        }
        return (responseBody, http)
    }

    private func mapStatus(_ status: Int) throws {
        switch status {
        case 200 ..< 300:
            return
        case 401, 403:
            throw LocalEngineHTTPError.authenticationFailed
        default:
            throw LocalEngineHTTPError.httpStatus(status)
        }
    }

    private func rebase(_ url: URL, onto base: URL) -> URL {
        var components = URLComponents(url: base, resolvingAgainstBaseURL: false)!
        components.path = url.path
        components.query = url.query
        return components.url ?? base
    }
}

enum HTTPMessageParser {
    static func parse(_ raw: Data) throws -> (Int, [String: String], Data) {
        guard let separator = raw.range(of: Data("\r\n\r\n".utf8)) else {
            throw LocalEngineHTTPError.invalidResponse
        }
        let head = raw.subdata(in: raw.startIndex ..< separator.lowerBound)
        let body = raw.subdata(in: separator.upperBound ..< raw.endIndex)
        guard let headText = String(data: head, encoding: .utf8) else {
            throw LocalEngineHTTPError.invalidResponse
        }
        let lines = headText.split(separator: "\r\n", omittingEmptySubsequences: false)
        guard let statusLine = lines.first else {
            throw LocalEngineHTTPError.invalidResponse
        }
        let parts = statusLine.split(separator: " ")
        guard parts.count >= 2, let status = Int(parts[1]) else {
            throw LocalEngineHTTPError.invalidResponse
        }
        var headers: [String: String] = [:]
        for line in lines.dropFirst() where !line.isEmpty {
            guard let colon = line.firstIndex(of: ":") else { continue }
            let name = String(line[..<colon]).trimmingCharacters(in: .whitespaces)
            let value = String(line[line.index(after: colon)...]).trimmingCharacters(in: .whitespaces)
            headers[name] = value
        }
        if let lengthText = headers.first(where: { $0.key.lowercased() == "content-length" })?.value,
           let length = Int(lengthText),
           length >= 0,
           body.count >= length
        {
            return (status, headers, Data(body.prefix(length)))
        }
        return (status, headers, body)
    }
}

/// ponytail: Darwin AF_UNIX stream + HTTP/1.1 framing; ceiling is single-request blocking I/O.
enum UnixHTTPConnection {
    static func exchangeBlocking(
        socketPath: String,
        request: Data,
        maximumResponseBytes: Int
    ) throws -> Data {
        let fd = socket(AF_UNIX, SOCK_STREAM, 0)
        guard fd >= 0 else {
            throw LocalEngineHTTPError.transportUnavailable
        }
        defer { close(fd) }

        var addr = sockaddr_un()
        addr.sun_family = sa_family_t(AF_UNIX)
        let pathBytes = Array(socketPath.utf8CString)
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
        let connectResult = withUnsafePointer(to: &addr) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { sockAddr in
                Darwin.connect(fd, sockAddr, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }
        guard connectResult == 0 else {
            throw LocalEngineHTTPError.transportUnavailable
        }

        var written = 0
        while written < request.count {
            let chunk = request.withUnsafeBytes { buffer -> Int in
                guard let base = buffer.baseAddress else { return -1 }
                return Darwin.write(fd, base.advanced(by: written), request.count - written)
            }
            if chunk <= 0 {
                throw LocalEngineHTTPError.transportUnavailable
            }
            written += chunk
        }

        var response = Data()
        var buffer = [UInt8](repeating: 0, count: 16 * 1_024)
        while true {
            let n = read(fd, &buffer, buffer.count)
            if n < 0 {
                throw LocalEngineHTTPError.transportUnavailable
            }
            if n == 0 {
                break
            }
            response.append(contentsOf: buffer.prefix(n))
            if response.count > maximumResponseBytes {
                throw LocalEngineHTTPError.responseTooLarge
            }
        }
        return response
    }
}
