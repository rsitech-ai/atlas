import Foundation

enum BoundedFileUploader {
    static func upload(
        request: URLRequest,
        fileURL: URL,
        maximumResponseBytes: Int,
        configuration: URLSessionConfiguration = .ephemeral
    ) async throws -> (Data, URLResponse) {
        let operation = BoundedUploadOperation(
            maximumResponseBytes: maximumResponseBytes,
            configuration: configuration
        )
        return try await withTaskCancellationHandler {
            try await operation.run(request: request, fileURL: fileURL)
        } onCancel: {
            operation.cancel()
        }
    }
}

private final class BoundedUploadOperation: NSObject, URLSessionDataDelegate, @unchecked Sendable {
    private let maximumResponseBytes: Int
    private let configuration: URLSessionConfiguration
    private let lock = NSLock()
    private var continuation: CheckedContinuation<(Data, URLResponse), any Error>?
    private var session: URLSession?
    private var task: URLSessionUploadTask?
    private var response: URLResponse?
    private var responseData = Data()
    private var finished = false

    init(maximumResponseBytes: Int, configuration: URLSessionConfiguration) {
        self.maximumResponseBytes = maximumResponseBytes
        self.configuration = configuration
    }

    func run(request: URLRequest, fileURL: URL) async throws -> (Data, URLResponse) {
        try await withCheckedThrowingContinuation { continuation in
            lock.lock()
            guard !finished else {
                lock.unlock()
                continuation.resume(throwing: CancellationError())
                return
            }
            self.continuation = continuation
            let session = URLSession(
                configuration: configuration,
                delegate: self,
                delegateQueue: nil
            )
            let task = session.uploadTask(with: request, fromFile: fileURL)
            self.session = session
            self.task = task
            lock.unlock()
            task.resume()
        }
    }

    func cancel() {
        finish(.failure(CancellationError()), cancelTransport: true)
    }

    func urlSession(
        _ session: URLSession,
        dataTask: URLSessionDataTask,
        didReceive response: URLResponse,
        completionHandler: @escaping @Sendable (URLSession.ResponseDisposition) -> Void
    ) {
        if response.expectedContentLength > Int64(maximumResponseBytes) {
            finish(
                .failure(DocumentImportClientError.responseTooLarge),
                cancelTransport: true
            )
            completionHandler(.cancel)
            return
        }
        lock.lock()
        self.response = response
        let shouldContinue = !finished
        lock.unlock()
        completionHandler(shouldContinue ? .allow : .cancel)
    }

    func urlSession(
        _ session: URLSession,
        dataTask: URLSessionDataTask,
        didReceive data: Data
    ) {
        lock.lock()
        let wouldExceedLimit = responseData.count > maximumResponseBytes - data.count
        if !finished, !wouldExceedLimit {
            responseData.append(data)
        }
        lock.unlock()
        if wouldExceedLimit {
            finish(
                .failure(DocumentImportClientError.responseTooLarge),
                cancelTransport: true
            )
        }
    }

    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        didCompleteWithError error: (any Error)?
    ) {
        if let error {
            if (error as? URLError)?.code == .cancelled {
                finish(.failure(CancellationError()), cancelTransport: false)
            } else {
                finish(.failure(error), cancelTransport: false)
            }
            return
        }

        lock.lock()
        let response = response
        let data = responseData
        lock.unlock()
        guard let response else {
            finish(
                .failure(DocumentImportClientError.invalidResponse),
                cancelTransport: false
            )
            return
        }
        finish(.success((data, response)), cancelTransport: false)
    }

    private func finish(
        _ result: Result<(Data, URLResponse), any Error>,
        cancelTransport: Bool
    ) {
        lock.lock()
        guard !finished else {
            lock.unlock()
            return
        }
        finished = true
        let continuation = continuation
        self.continuation = nil
        let task = task
        let session = session
        self.task = nil
        self.session = nil
        lock.unlock()

        if cancelTransport {
            task?.cancel()
            session?.invalidateAndCancel()
        } else {
            session?.finishTasksAndInvalidate()
        }
        continuation?.resume(with: result)
    }
}
