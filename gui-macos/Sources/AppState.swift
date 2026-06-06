import Foundation
import SwiftUI

/// Single source of truth for what the views render. Owns the
/// daemon-discovery lifecycle and the events-table polling loop.
/// Sidebar selection. macOS ``List(selection:)`` does not play well with
/// ``String?`` sentinels (the ``.tag(String?.none)`` row stays inert), so we
/// encode the choice as an enum and derive the collection-name filter from it.
/// Sort axes for the article list. Sorting is local because the daemon
/// already returns the corpus order we want as a default (added desc), and
/// the visible list is bounded by ``DaemonClient.articles(limit:)``.
enum SortAxis: String, CaseIterable, Identifiable {
    case added           // _added_at desc
    case coverDate       // cover_date desc
    case title           // title asc
    case citations       // cited_by desc
    case updated         // _updated_at desc

    var id: String { rawValue }
    var label: String {
        switch self {
        case .added: return "Added"
        case .coverDate: return "Cover date"
        case .title: return "Title"
        case .citations: return "Citations"
        case .updated: return "Last updated"
        }
    }
}

enum SidebarSelection: Hashable {
    case allArticles
    case collection(String)

    var collectionName: String? {
        switch self {
        case .allArticles: return nil
        case .collection(let name): return name
        }
    }

    var displayTitle: String {
        switch self {
        case .allArticles: return "All articles"
        case .collection(let name): return name
        }
    }
}

@MainActor
final class AppState: ObservableObject {
    @Published var daemonStatus: DaemonStatus = .unknown
    @Published var collections: [CollectionInfo] = []
    @Published var articles: [Article] = []
    @Published var selection: SidebarSelection = .allArticles
    @Published var selectedArticleEid: String? = nil
    @Published var lastError: String? = nil

    /// Multi-selection set in the article list. When this set has more than
    /// one entry the detail pane swaps to a batch panel; ``selectedArticleEid``
    /// continues to track "the focused row for single-row affordances" (last
    /// click).
    @Published var multiSelection: Set<String> = []

    /// Anchor row for shift-click range selection. Distinct from
    /// ``selectedArticleEid`` so a Cmd-click that toggles a row off doesn't
    /// move the anchor — matches Finder/Mail behavior.
    var multiSelectAnchor: String? = nil

    /// Local sort axis applied client-side after fetching. Persisting this
    /// across launches is a future improvement; for now it resets to ``.added``.
    @Published var sortAxis: SortAxis = .added

    /// Live FTS query. Empty = list shows the current collection's articles;
    /// non-empty = list shows the latest /search/fts response, intersected
    /// with the current collection filter (when set).
    @Published var searchQuery: String = ""

    /// True while a search request is in flight. UI dims the search field hint.
    @Published var isSearching: Bool = false

    var selectedCollection: String? { selection.collectionName }

    /// Highest event id we've already reflected in the views; used as the
    /// ``?since=`` cursor for ``GET /events``.
    private var lastSeenEventId: Int = 0

    /// True once the event cursor has been established at ``MAX(id)``. When the
    /// bootstrap fetch that seeds the cursor fails, this stays ``false`` and the
    /// first ``tick()`` re-seeds the cursor (fetching the max id) instead of
    /// replaying the entire event history from id 0.
    private var eventCursorReady: Bool = false

    /// Consecutive ``tick()`` failures. A single transient blip must not flip
    /// the daemon to ``.down`` — only a sustained streak does (see ``tick()``).
    private var consecutivePollFailures: Int = 0

    private var pollingTask: Task<Void, Never>? = nil
    private var searchTask: Task<Void, Never>? = nil

    enum DaemonStatus: Equatable {
        case unknown
        case running
        case down(String)  // user-facing message
    }

    func bootstrap() async {
        await refreshDaemonStatus()
        guard daemonStatus == .running else { return }
        // Establish cursor at MAX(id) so a cold start doesn't replay history.
        // If this fails, leave ``eventCursorReady`` false so the first tick
        // re-seeds the cursor instead of replaying every historical event.
        await seedEventCursor()
        await reloadAll()
        startPolling()
    }

    /// Seed ``lastSeenEventId`` from the daemon's current ``MAX(id)``. Retries
    /// once on failure; on a second failure the cursor stays unseeded
    /// (``eventCursorReady`` false) and ``tick()`` retries the seed before it
    /// would otherwise replay history from id 0.
    private func seedEventCursor() async {
        for attempt in 1...2 {
            do {
                let evs = try await DaemonClient.shared.events(since: 0, limit: 1)
                lastSeenEventId = evs.maxId
                eventCursorReady = true
                return
            } catch {
                NSLog("scopus-for-dobby: event cursor seed failed (attempt \(attempt)): \(error.localizedDescription)")
            }
        }
        eventCursorReady = false
    }

    /// Refresh both panes. Each fetch runs in its own do/catch so a transient
    /// failure on one (e.g. a daemon hiccup that returns a 500 on /articles)
    /// doesn't blank out the other (the recurring "collections empty" UX bug).
    /// The first error encountered surfaces in ``lastError``; subsequent
    /// successful fetches do not clear it on the assumption that *some* pane
    /// is stale and the user should know.
    func reloadAll() async {
        async let colsTask = DaemonClient.shared.collections()
        async let artsTask = articlesForCurrentSelection()

        var firstError: Error? = nil
        do {
            self.collections = try await colsTask
        } catch {
            firstError = firstError ?? error
        }
        do {
            self.articles = try await artsTask
        } catch {
            firstError = firstError ?? error
        }
        if let err = firstError {
            self.lastError = err.localizedDescription
        } else {
            self.lastError = nil
        }
    }

    func selectSidebar(_ s: SidebarSelection) {
        selection = s
        // Drop multi-selection: the previous eids belong to whatever the user
        // was looking at before. Leaving them set means a subsequent batch op
        // (especially "remove from current collection") would target a stale
        // collection scope. Architect review caught this.
        multiSelection.removeAll()
        multiSelectAnchor = nil
        Task { await reloadArticles() }
    }

    func reloadArticles() async {
        do {
            self.articles = try await articlesForCurrentSelection()
        } catch {
            self.lastError = error.localizedDescription
        }
    }

    /// Search-aware article fetch. Always honors the current sidebar selection.
    private func articlesForCurrentSelection() async throws -> [Article] {
        let q = searchQuery.trimmingCharacters(in: .whitespaces)
        if q.isEmpty {
            // Effectively-unbounded: covers 100k+ libraries. SwiftUI's
            // ``LazyVStack`` only realizes visible rows so render cost is flat
            // in the visible window; the cost paid is JSON decode + lossy
            // filter, which is fine at this scale on M-series Macs. Anything
            // larger should move to true server-side pagination — see plan
            // §scale.
            return try await DaemonClient.shared.articles(collection: selectedCollection,
                                                          limit: 200_000)
        }
        let hits = try await DaemonClient.shared.searchFTS(query: q, limit: 1000)
        guard let coll = selectedCollection else { return hits }
        let allowed = Set(try await DaemonClient.shared.articles(collection: coll, limit: 200_000)
                          .map(\.eid))
        return hits.filter { allowed.contains($0.eid) }
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

    /// True while ``launchDaemon()`` is spawning + waiting for ``/health``.
    @Published var isLaunchingDaemon: Bool = false

    /// Spawn the local daemon (``scopus-for-dobby serve --background``) and
    /// poll ``/health`` until it's up, then re-bootstrap. Resolves the binary
    /// the same way the design spec recommends for the CLIRunner: env override
    /// → ``~/.local/bin`` (uv tool install default) → known package locations
    /// → login-shell ``which`` (catches Finder-launched apps that don't inherit
    /// the user's PATH). Surfaces the exact path tried in ``lastError`` if all
    /// candidates fail, so the user can fix it instead of guessing.
    func launchDaemon() async {
        guard !isLaunchingDaemon else { return }
        isLaunchingDaemon = true
        defer { isLaunchingDaemon = false }

        guard let binary = DaemonLauncher.resolveBinaryPath() else {
            lastError = "Couldn't find scopus-for-dobby on PATH. Install it with `uv tool install --editable \".[cli,export]\"` or set SCOPUS_FOR_DOBBY_BIN."
            return
        }

        do {
            try DaemonLauncher.spawn(binary: binary)
        } catch {
            lastError = "Spawn failed (\(binary)): \(error.localizedDescription)"
            return
        }

        // Poll /health for up to ~6s. The daemon usually answers in 0.5–1s.
        for _ in 0..<30 {
            try? await Task.sleep(nanoseconds: 200_000_000)
            do {
                _ = try DaemonClient.shared.discover()
                _ = try await DaemonClient.shared.health()
                await bootstrap()
                return
            } catch {
                continue
            }
        }
        lastError = "Daemon spawned but didn't answer /health within 6s. Check ~/.scopus-for-dobby/daemon.log."
    }

    // MARK: - Search

    /// Debounced search runner. Call from a view's ``onChange(of: searchQuery)``.
    /// Cancels in-flight searches when the query changes again, then waits a
    /// short moment so a fast typist doesn't fire a request per keystroke.
    func runSearchDebounced() {
        searchTask?.cancel()
        searchTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 200_000_000)  // 200ms
            guard let self, !Task.isCancelled else { return }
            self.isSearching = true
            await self.reloadArticles()
            self.isSearching = false
        }
    }

    func clearSearch() {
        searchQuery = ""
        searchTask?.cancel()
        Task { await reloadArticles() }
    }

    // MARK: - Mutations
    //
    // All mutations are thin proxies onto the daemon. We don't optimistically
    // update local state; the events-poll loop will refresh within ~1.5s, and
    // for the active detail pane the caller can re-fetch the article directly
    // (see ``refetchArticle(_:)``).

    /// Apply ``sortAxis`` to the in-memory ``articles`` array. Local-only sort:
    /// the corpus is already capped at ~200 rows by the fetch limit, and the
    /// daemon's default order is "added desc" which we treat as ``axis=.added``.
    func sortedArticles() -> [Article] {
        switch sortAxis {
        case .added:
            return articles.sorted { ($0.addedAt ?? "") > ($1.addedAt ?? "") }
        case .coverDate:
            return articles.sorted { ($0.coverDate ?? "") > ($1.coverDate ?? "") }
        case .title:
            return articles.sorted {
                ($0.title ?? "").localizedCaseInsensitiveCompare($1.title ?? "") == .orderedAscending
            }
        case .citations:
            return articles.sorted { ($0.citedBy ?? -1) > ($1.citedBy ?? -1) }
        case .updated:
            return articles.sorted { ($0.updatedAt ?? "") > ($1.updatedAt ?? "") }
        }
    }

    // MARK: - Batch mutations
    //
    // The single-article wrappers below (addTag/removeTag/setNote) are kept
    // for the detail-pane editor. The batch variants take a list of eids and
    // hit the corresponding bulk endpoints in one round-trip.

    /// Batch tag mutations return ``true`` on a 2xx daemon response. Callers
    /// (BatchPanel) use the bool to decide whether to render a success status
    /// or stay silent (footer already shows the error from ``lastError``).
    func tagBatch(eids: [String], tags: [String]) async -> Bool {
        let cleanTags = tags.map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
        guard !eids.isEmpty, !cleanTags.isEmpty else { return false }
        do { try await DaemonClient.shared.tagArticles(eids: eids, tags: cleanTags); return true }
        catch { self.lastError = error.localizedDescription; return false }
    }

    func untagBatch(eids: [String], tags: [String]) async -> Bool {
        guard !eids.isEmpty, !tags.isEmpty else { return false }
        do { try await DaemonClient.shared.untagArticles(eids: eids, tags: tags); return true }
        catch { self.lastError = error.localizedDescription; return false }
    }

    func addBatchToCollection(name: String, eids: [String]) async -> Bool {
        guard !eids.isEmpty, !name.isEmpty else { return false }
        do { try await DaemonClient.shared.addToCollection(name: name, eids: eids); return true }
        catch { self.lastError = error.localizedDescription; return false }
    }

    func removeBatchFromCollection(name: String, eids: [String]) async -> Bool {
        guard !eids.isEmpty, !name.isEmpty else { return false }
        do { try await DaemonClient.shared.removeFromCollection(name: name, eids: eids); return true }
        catch { self.lastError = error.localizedDescription; return false }
    }

    func clearMultiSelection() {
        multiSelection.removeAll()
    }

    func addTag(eid: String, tag: String) async {
        let trimmed = tag.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { return }
        do { try await DaemonClient.shared.tagArticles(eids: [eid], tags: [trimmed]) }
        catch { self.lastError = error.localizedDescription }
    }

    func removeTag(eid: String, tag: String) async {
        do { try await DaemonClient.shared.untagArticles(eids: [eid], tags: [tag]) }
        catch { self.lastError = error.localizedDescription }
    }

    func setNote(eid: String, note: String) async {
        do { try await DaemonClient.shared.setNote(eid: eid, note: note) }
        catch { self.lastError = error.localizedDescription }
    }

    func createCollection(_ name: String) async {
        let trimmed = name.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { return }
        do {
            try await DaemonClient.shared.createCollection(name: trimmed)
            await reloadAll()
        } catch {
            self.lastError = error.localizedDescription
        }
    }

    func renameCollection(_ old: String, to new: String) async {
        let trimmed = new.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty, trimmed != old else { return }
        do {
            try await DaemonClient.shared.renameCollection(old: old, new: trimmed)
            if selection == .collection(old) {
                selection = .collection(trimmed)
            }
            await reloadAll()
        } catch {
            self.lastError = error.localizedDescription
        }
    }

    func mergeCollections(src: String, into dst: String) async {
        guard !src.isEmpty, !dst.isEmpty, src != dst else { return }
        do {
            try await DaemonClient.shared.mergeCollections(src: src, dst: dst)
            if selection == .collection(src) {
                selection = .collection(dst)
            }
            await reloadAll()
        } catch {
            self.lastError = error.localizedDescription
        }
    }

    func deleteCollection(_ name: String) async {
        do {
            try await DaemonClient.shared.deleteCollection(name: name)
            // If we were viewing the deleted collection, fall back to All.
            if selection == .collection(name) {
                selection = .allArticles
            }
            await reloadAll()
        } catch {
            self.lastError = error.localizedDescription
        }
    }

    /// Fetches a single article fresh from the daemon. Used by the detail
    /// pane to reflect a tag/note edit without waiting for the poll loop.
    func refetchArticle(eid: String) async -> Article? {
        do { return try await DaemonClient.shared.article(eid: eid) }
        catch {
            self.lastError = error.localizedDescription
            return nil
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

    /// Mark the daemon ``.down`` only after this many consecutive poll failures.
    /// A single transient blip (one dropped /events request) must not blank the
    /// status; any success resets the streak.
    private static let pollFailureThreshold = 3

    private func tick() async {
        // If the bootstrap seed never landed, re-seed before polling so we don't
        // replay history from id 0 on the first successful fetch.
        if !eventCursorReady {
            await seedEventCursor()
            guard eventCursorReady else { return }
        }
        do {
            let resp = try await DaemonClient.shared.events(since: lastSeenEventId, limit: 200)
            consecutivePollFailures = 0
            guard !resp.events.isEmpty else { return }
            lastSeenEventId = resp.maxId
            // Coarse refresh: any event in the visible scope re-pulls. Step 7
            // can refine to per-kind invalidation once usage patterns settle.
            await reloadAll()
        } catch {
            // Polling failures are noisy on transient network blips — don't
            // surface them in the UI, and don't flip status on a lone failure.
            // Only a sustained streak triggers a real status check that can mark
            // the daemon .down().
            consecutivePollFailures += 1
            if consecutivePollFailures >= Self.pollFailureThreshold {
                await refreshDaemonStatus()
                // Reset so a recovered daemon isn't re-probed every tick, and a
                // still-down one takes another full streak before the next check.
                consecutivePollFailures = 0
            }
        }
    }

    deinit { pollingTask?.cancel(); searchTask?.cancel() }
}
