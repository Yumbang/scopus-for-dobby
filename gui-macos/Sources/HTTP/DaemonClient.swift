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
        let (data, response) = try await URLSession.shared.data(from: url)
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
        var components = URLComponents()
        components.path = "/articles"
        var items = [URLQueryItem(name: "limit", value: "\(limit)")]
        if let collection { items.append(URLQueryItem(name: "collection", value: collection)) }
        components.queryItems = items
        let resp: ArticleListResponse = try await get(components.path + "?" + (components.percentEncodedQuery ?? ""))
        return resp.articles
    }

    func article(eid: String) async throws -> Article {
        return try await get("/articles/\(eid.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? eid)")
    }

    func events(since: Int, limit: Int = 200) async throws -> EventsResponse {
        return try await get("/events?since=\(since)&limit=\(limit)")
    }

    // MARK: - private

    private func resolved(_ path: String) throws -> URL {
        let base = try (baseURL ?? discover())
        return base.appendingPathComponent(path.hasPrefix("/") ? String(path.dropFirst()) : path)
    }

    private func get<T: Decodable>(_ path: String) async throws -> T {
        let url = try resolved(path)
        let (data, response) = try await URLSession.shared.data(from: url)
        guard let http = response as? HTTPURLResponse else {
            throw DaemonError.badResponse(-1, "no HTTP response")
        }
        guard (200..<300).contains(http.statusCode) else {
            throw DaemonError.badResponse(http.statusCode,
                                          String(data: data, encoding: .utf8) ?? "")
        }
        return try decoder.decode(T.self, from: data)
    }
}
