import Foundation
import Testing

@testable import RSIAtlasCore

struct CommandCenterStoreTests {
    @Test @MainActor
    func initialReloadPublishesLoadedStatus() async throws {
        let expected = try fixtureStatus()
        let store = CommandCenterStore(loader: StubStatusLoader(result: .success(expected)))

        await store.reload()

        #expect(
            store.state == .loaded(
                status: expected,
                isRefreshing: false,
                refreshFailure: nil
            )
        )
    }

    @Test @MainActor
    func initialFailureUsesSanitizedTypedReasonAndRetryCanRecover() async throws {
        let expected = try fixtureStatus()
        let loader = ControlledStatusLoader()
        let store = CommandCenterStore(loader: loader)

        let failedReload = Task { await store.reload() }
        await loader.waitUntilRequestCount(1)
        await loader.completeRequest(at: 0, with: .failure(EngineClientError.incompatibleContract))
        await failedReload.value

        #expect(store.state == .failed(.incompatibleContract))

        let recoveredReload = Task { await store.reload() }
        await loader.waitUntilRequestCount(2)
        await loader.completeRequest(at: 1, with: .success(expected))
        await recoveredReload.value

        #expect(
            store.state == .loaded(
                status: expected,
                isRefreshing: false,
                refreshFailure: nil
            )
        )
    }

    @Test @MainActor
    func refreshPreservesStatusAndFailureMarksItStale() async throws {
        let expected = try fixtureStatus()
        let loader = ControlledStatusLoader()
        let store = CommandCenterStore(loader: loader)
        let firstReload = Task { await store.reload() }
        await loader.waitUntilRequestCount(1)
        await loader.completeRequest(at: 0, with: .success(expected))
        await firstReload.value

        let refresh = Task { await store.reload() }
        await loader.waitUntilRequestCount(2)
        #expect(
            store.state == .loaded(
                status: expected,
                isRefreshing: true,
                refreshFailure: nil
            )
        )
        await loader.completeRequest(at: 1, with: .failure(StubError.unavailable))
        await refresh.value

        #expect(
            store.state == .loaded(
                status: expected,
                isRefreshing: false,
                refreshFailure: .unavailable
            )
        )
    }

    @Test @MainActor
    func cancellationDoesNotPublishEngineUnavailable() async {
        let store = CommandCenterStore(loader: CancellingStatusLoader())

        await store.reload()

        #expect(store.state == .idle)
    }

    @Test @MainActor
    func olderReloadCannotOverwriteANewerResult() async throws {
        let expected = try fixtureStatus()
        let loader = ControlledStatusLoader()
        let store = CommandCenterStore(loader: loader)

        let olderReload = Task { await store.reload() }
        await loader.waitUntilRequestCount(1)
        let newerReload = Task { await store.reload() }
        await loader.waitUntilRequestCount(2)

        await loader.completeRequest(at: 1, with: .success(expected))
        await newerReload.value
        await loader.completeRequest(at: 0, with: .failure(StubError.unavailable))
        await olderReload.value

        #expect(
            store.state == .loaded(
                status: expected,
                isRefreshing: false,
                refreshFailure: nil
            )
        )
    }
}

private enum StubError: Error, Sendable {
    case unavailable
}

private struct StubStatusLoader: EngineStatusLoading {
    let result: Result<SystemStatus, any Error>

    func loadStatus() async throws -> SystemStatus {
        try result.get()
    }
}

private struct CancellingStatusLoader: EngineStatusLoading {
    func loadStatus() async throws -> SystemStatus {
        throw CancellationError()
    }
}

private actor ControlledStatusLoader: EngineStatusLoading {
    private var continuations: [CheckedContinuation<SystemStatus, any Error>] = []

    func loadStatus() async throws -> SystemStatus {
        try await withCheckedThrowingContinuation { continuation in
            continuations.append(continuation)
        }
    }

    func waitUntilRequestCount(_ expectedCount: Int) async {
        while continuations.count < expectedCount {
            await Task.yield()
        }
    }

    func completeRequest(
        at index: Int,
        with result: Result<SystemStatus, any Error>
    ) {
        switch result {
        case let .success(status):
            continuations[index].resume(returning: status)
        case let .failure(error):
            continuations[index].resume(throwing: error)
        }
    }
}

private func fixtureStatus() throws -> SystemStatus {
    let fixtureURL = try #require(
        Bundle.module.url(forResource: "system_status_v1_1", withExtension: "json")
    )
    return try SystemStatus.decoder.decode(
        SystemStatus.self,
        from: Data(contentsOf: fixtureURL)
    )
}
