import Foundation
import Testing

@testable import RSIAtlasCore

struct CommandCenterStoreTests {
    @Test @MainActor
    func reloadPublishesLoadedStatus() async throws {
        let expected = try fixtureStatus()
        let store = CommandCenterStore(loader: StubStatusLoader(result: .success(expected)))

        await store.reload()

        #expect(store.state == .loaded(expected))
    }

    @Test @MainActor
    func reloadPublishesRecoverableFailure() async {
        let store = CommandCenterStore(loader: StubStatusLoader(result: .failure(.unavailable)))

        await store.reload()

        #expect(store.state == .failed(message: "RSI Atlas Engine is unavailable."))
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

        #expect(store.state == .loaded(expected))
    }
}

private enum StubError: Error {
    case unavailable
}

private struct StubStatusLoader: EngineStatusLoading {
    let result: Result<SystemStatus, StubError>

    func loadStatus() async throws -> SystemStatus {
        try result.get()
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
        with result: Result<SystemStatus, StubError>
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
    let fixtureURL = try #require(Bundle.module.url(forResource: "system_status_v1", withExtension: "json"))
    return try SystemStatus.decoder.decode(SystemStatus.self, from: Data(contentsOf: fixtureURL))
}
