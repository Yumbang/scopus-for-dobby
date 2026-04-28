import Foundation
import SwiftUI

/// Single source of truth for what the views render. Owns the
/// daemon-discovery lifecycle and the events-table polling loop.
@MainActor
final class AppState: ObservableObject {
    @Published var daemonStatus: DaemonStatus = .unknown
    @Published var collections: [CollectionInfo] = []
    @Published var articles: [Article] = []
    @Published var selectedCollection: String? = nil  // nil = "All"
    @Published var selectedArticleEid: String? = nil
    @Published var lastError: String? = nil

    /// Highest event id we've already reflected in the views; used as the
    /// ``?since=`` cursor for ``GET /events``.
    private var lastSeenEventId: Int = 0
    private var pollingTask: Task<Void, Never>? = nil

    enum DaemonStatus: Equatable {
        case unknown
        case running
        case down(String)  // user-facing message
    }

    func bootstrap() async {
        await refreshDaemonStatus()
        guard daemonStatus == .running else { return }
        // Establish cursor at MAX(id) so a cold start doesn't replay history.
        if let evs = try? await DaemonClient.shared.events(since: 0, limit: 1) {
            lastSeenEventId = evs.maxId
        }
        await reloadAll()
        startPolling()
    }

    func reloadAll() async {
        do {
            async let cols = DaemonClient.shared.collections()
            async let arts = DaemonClient.shared.articles(collection: selectedCollection)
            self.collections = try await cols
            self.articles = try await arts
        } catch {
            self.lastError = error.localizedDescription
        }
    }

    func selectCollection(_ name: String?) {
        selectedCollection = name
        Task { await reloadArticles() }
    }

    func reloadArticles() async {
        do {
            self.articles = try await DaemonClient.shared.articles(collection: selectedCollection)
        } catch {
            self.lastError = error.localizedDescription
        }
    }

    func refreshDaemonStatus() async {
        do {
            _ = try DaemonClient.shared.discover()
            _ = try await DaemonClient.shared.health()
            daemonStatus = .running
            lastError = nil
        } catch {
            daemonStatus = .down(error.localizedDescription)
        }
    }

    private func startPolling() {
        pollingTask?.cancel()
        pollingTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 1_500_000_000)  // 1.5s
                await self?.tick()
            }
        }
    }

    private func tick() async {
        do {
            let resp = try await DaemonClient.shared.events(since: lastSeenEventId, limit: 200)
            guard !resp.events.isEmpty else { return }
            lastSeenEventId = resp.maxId
            // Coarse refresh: any event in the visible scope re-pulls. Step 7
            // can refine to per-kind invalidation once usage patterns settle.
            await reloadAll()
        } catch {
            // Polling failures are noisy on transient network blips — don't
            // surface them in the UI; flip daemon status if it persists.
            await refreshDaemonStatus()
        }
    }

    deinit { pollingTask?.cancel() }
}
