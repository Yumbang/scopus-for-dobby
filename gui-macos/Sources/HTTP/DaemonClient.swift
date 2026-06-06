import Foundation

/// Talks to the local scopus-for-dobby daemon. Discovers the port via
/// ``~/.scopus-for-dobby/daemon.port`` (written by ``cli/serve.py``).
///
/// The daemon is single-process; this client is intentionally simple —
/// no retry, no connection pooling, no caching. URLSession handles the
/// rest. If the daemon isn't running, every call throws ``DaemonError.notRunning``
/// and the UI shows a "start the daemon" placeholder.
@MainActor
final class DaemonClient: ObservableObject {
    static let shared = DaemonClient()

    enum DaemonError: Error, LocalizedError {
        case notRunning
        case badResponse(Int, String)
        case invalidPort

        var errorDescription: String? {
            switch self {
            case .notRunning:
                return "scopus-for-dobby daemon is not running. Run `scopus-for-dobby serve` or any CLI subcommand to start it."
            case .badResponse(let status, let body):
                return "Daemon returned HTTP \(status): \(body)"
            case .invalidPort:
                return "daemon.port file is malformed."
            }
        }
    }

    @Published private(set) var baseURL: URL?

    /// Just the ":port" suffix the sidebar footer shows (loopback is implied,
    /// so the host is elided). ``nil`` until ``discover()`` resolves the port.
    var portLabel: String? {
        guard let baseURL, let port = baseURL.port else { return nil }
        return ":\(port)"
    }

    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        return d
    }()

    func discover() throws -> URL {
        let portFile = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".scopus-for-dobby/daemon.port")
        guard let raw = try? String(contentsOf: portFile, encoding: .utf8) else {
            baseURL = nil
            throw DaemonError.notRunning
        }
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let port = Int(trimmed),
              let url = URL(string: "http://127.0.0.1:\(port)") else {
            throw DaemonError.invalidPort
        }
        baseURL = url
        return url
    }

    func health() async throws -> Bool {
        let url = try resolved("/health")
        // Short per-request timeout: /health gates the poll cadence and a hung
        // request must not stall it past one tick. The default URLSession
        // timeout (~60s) would let a wedged daemon freeze status detection.
        var request = URLRequest(url: url)
        request.timeoutInterval = quickTimeout
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw DaemonError.badResponse(
                (response as? HTTPURLResponse)?.statusCode ?? -1,
                String(data: data, encoding: .utf8) ?? "")
        }
        return true
    }

    func collections() async throws -> [CollectionInfo] {
        let resp: CollectionsResponse = try await get("/collections")
        return resp.collections
    }

    func articles(collection: String? = nil, limit: Int = 200) async throws -> [Article] {
        var items = [URLQueryItem(name: "limit", value: "\(limit)")]
        if let collection { items.append(URLQueryItem(name: "collection", value: collection)) }
        let resp: ArticleListResponse = try await get(buildPath("/articles", queryItems: items))
        return resp.articles
    }

    func article(eid: String) async throws -> Article {
        return try await get("/articles/\(pathEscaped(eid))")
    }

    func events(since: Int, limit: Int = 200) async throws -> EventsResponse {
        // Also a poll-cadence GET (1.5s tick): a hung request here would stall
        // event detection just like /health, so give it the same short timeout.
        return try await get(buildPath("/events", queryItems: [
            URLQueryItem(name: "since", value: "\(since)"),
            URLQueryItem(name: "limit", value: "\(limit)"),
        ]), timeout: quickTimeout)
    }

    // MARK: - search

    func searchFTS(query: String, limit: Int = 100) async throws -> [Article] {
        // ``URLQueryItem`` is the only path that correctly percent-encodes
        // value-internal ``&`` and ``=``. Concatenating an
        // ``addingPercentEncoding(.urlQueryAllowed)`` string would let a
        // query like ``foo&limit=99999`` smuggle a second ``limit`` param.
        let resp: ArticleListResponse = try await get(buildPath("/search/fts", queryItems: [
            URLQueryItem(name: "query", value: query),
            URLQueryItem(name: "limit", value: "\(limit)"),
        ]))
        return resp.articles
    }

    /// Build a path + querystring tuple suitable for ``get()`` from a path and
    /// query items. Centralizes the URLComponents → ``percentEncodedQuery``
    /// dance so callers can't accidentally re-introduce string-interpolation.
    private func buildPath(_ path: String, queryItems: [URLQueryItem]) -> String {
        var c = URLComponents()
        c.path = path
        c.queryItems = queryItems
        return c.path + "?" + (c.percentEncodedQuery ?? "")
    }

    // MARK: - mutations

    func tagArticles(eids: [String], tags: [String]) async throws {
        try await mutate("POST", path: "/articles/tag", body: ["eids": eids, "tags": tags])
    }

    func untagArticles(eids: [String], tags: [String]) async throws {
        try await mutate("POST", path: "/articles/untag", body: ["eids": eids, "tags": tags])
    }

    func setNote(eid: String, note: String) async throws {
        try await mutate("POST", path: "/articles/\(pathEscaped(eid))/note", body: ["note": note])
    }

    func createCollection(name: String) async throws {
        try await mutate("POST", path: "/collections", body: ["name": name])
    }

    func deleteCollection(name: String) async throws {
        try await mutate("DELETE", path: "/collections/\(pathEscaped(name))", body: nil)
    }

    func renameCollection(old: String, new: String) async throws {
        try await mutate("POST", path: "/collections/rename", body: ["old": old, "new": new])
    }

    func mergeCollections(src: String, dst: String) async throws {
        try await mutate("POST", path: "/collections/merge", body: ["src": src, "dst": dst])
    }

    func addToCollection(name: String, eids: [String]) async throws {
        try await mutate("POST", path: "/collections/\(pathEscaped(name))/articles", body: ["eids": eids])
    }

    func removeFromCollection(name: String, eids: [String]) async throws {
        try await mutate("DELETE", path: "/collections/\(pathEscaped(name))/articles", body: ["eids": eids])
    }

    // MARK: - private

    private func resolved(_ path: String) throws -> URL {
        let base = try (baseURL ?? discover())
        // URLComponents is the only URL builder that correctly separates
        // path and query without percent-encoding ``?`` (which
        // appendingPathComponent does) or producing fragile relative URLs
        // (which URL(string:relativeTo:) does).
        guard var components = URLComponents(url: base, resolvingAgainstBaseURL: false) else {
            throw DaemonError.badResponse(-1, "bad base URL \(base)")
        }
        let parts = path.split(separator: "?", maxSplits: 1, omittingEmptySubsequences: false)
        // Use ``percentEncodedPath`` because callers already percent-encode
        // path segments (e.g. ``addingPercentEncoding(.urlPathAllowed)`` on a
        // collection name). The plain ``path`` setter re-encodes ``%`` to
        // ``%25``, which double-encodes non-ASCII names like Korean
        // collections — the daemon then sees ``%EC%82%AC...`` as a literal
        // string and replies "Collection not found."
        components.percentEncodedPath = String(parts[0])
        components.percentEncodedQuery = parts.count > 1 ? String(parts[1]) : nil
        guard let url = components.url else {
            throw DaemonError.badResponse(-1, "could not build URL from \(path)")
        }
        return url
    }

    /// Generic mutation helper. Takes a method (POST/DELETE), a path, and an
    /// optional dict body (encoded as JSON). Throws on non-2xx; ignores the
    /// response body — callers that need to read it should fetch the affected
    /// resource separately, since the events polling loop will refresh anyway.
    private func mutate(_ method: String, path: String, body: [String: Any]?) async throws {
        let url = try resolved(path)
        var request = URLRequest(url: url)
        request.httpMethod = method
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw DaemonError.badResponse(-1, "no HTTP response")
        }
        guard (200..<300).contains(http.statusCode) else {
            throw DaemonError.badResponse(http.statusCode,
                                          String(data: data, encoding: .utf8) ?? "")
        }
    }

    private func get<T: Decodable>(_ path: String, timeout: TimeInterval? = nil) async throws -> T {
        let url = try resolved(path)
        var request = URLRequest(url: url)
        if let timeout { request.timeoutInterval = timeout }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw DaemonError.badResponse(-1, "no HTTP response")
        }
        guard (200..<300).contains(http.statusCode) else {
            throw DaemonError.badResponse(http.statusCode,
                                          String(data: data, encoding: .utf8) ?? "")
        }
        return try decoder.decode(T.self, from: data)
    }

    /// Short per-request timeout for the poll-cadence GETs (/health, /events).
    /// Comfortably above a healthy daemon's response time, well below the tick
    /// interval so a hung request fails fast instead of wedging the loop.
    private let quickTimeout: TimeInterval = 3

    /// Percent-encode a single path segment (eid, collection name) so non-ASCII
    /// names like Korean collections survive the trip. Falls back to the raw
    /// value if encoding somehow fails — ``resolved(_:)`` uses
    /// ``percentEncodedPath`` and won't double-encode the result.
    private func pathEscaped(_ segment: String) -> String {
        segment.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? segment
    }
}
