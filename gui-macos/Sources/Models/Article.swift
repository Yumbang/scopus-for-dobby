import Foundation

/// Mirrors the ``articles`` table in ``scopus_for_dobby/core/article_db.py``.
/// All fields are optional because the daemon may omit blanks and because
/// older rows from before a column was added will decode as nil.
struct Article: Identifiable, Decodable, Hashable {
    let eid: String
    let scopusId: String?
    let doi: String?
    let title: String?
    let firstAuthor: String?
    let allAuthors: [Author]?
    let journal: String?
    let volume: String?
    let issue: String?
    let pages: String?
    let coverDate: String?
    let citedBy: Int?
    let openAccess: Bool?
    let abstract: String?
    let keywords: String?
    let issn: String?
    let sourceType: String?
    let tags: [String]?
    let notes: String?
    let addedAt: String?
    let updatedAt: String?

    var id: String { eid }

    enum CodingKeys: String, CodingKey {
        case eid
        case scopusId = "scopus_id"
        case doi, title
        case firstAuthor = "first_author"
        case allAuthors = "all_authors"
        case journal, volume, issue, pages
        case coverDate = "cover_date"
        case citedBy = "cited_by"
        case openAccess = "open_access"
        case abstract, keywords, issn
        case sourceType = "source_type"
        // Daemon emits user-metadata fields under leading-underscore names
        // (``_tags``, ``_notes``, ``_added_at``, ``_updated_at``) to distinguish
        // them from Scopus-imported columns. Match the wire format.
        case tags = "_tags"
        case notes = "_notes"
        case addedAt = "_added_at"
        case updatedAt = "_updated_at"
    }
}

struct Author: Decodable, Hashable {
    let auid: String?
    let name: String?
}

/// Response shape from ``GET /articles`` and ``GET /search/{fts,like}``.
///
/// The article list is decoded leniently: a single malformed row (e.g. a row
/// missing ``eid`` or with an unexpected type for an optional column) must not
/// poison the entire response. Past incidents had a single bad row crash the
/// list and leave the GUI in a "no articles found" state with no surfaced
/// error. We use a per-element try/catch via ``LossyArticle`` to skip bad rows.
struct ArticleListResponse: Decodable {
    let articles: [Article]
    let totalMatching: Int?
    let totalInDb: Int?
    let total: Int?

    enum CodingKeys: String, CodingKey {
        case articles
        case totalMatching = "total_matching"
        case totalInDb = "total_in_db"
        case total
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.totalMatching = try c.decodeIfPresent(Int.self, forKey: .totalMatching)
        self.totalInDb = try c.decodeIfPresent(Int.self, forKey: .totalInDb)
        self.total = try c.decodeIfPresent(Int.self, forKey: .total)

        var arr = try c.nestedUnkeyedContainer(forKey: .articles)
        var out: [Article] = []
        out.reserveCapacity(arr.count ?? 0)
        while !arr.isAtEnd {
            // ``LossyArticle.init`` uses ``try?`` internally so it never
            // throws — the container always advances. Bad rows surface as
            // ``value == nil`` and are skipped.
            let lossy = try arr.decode(LossyArticle.self)
            if let a = lossy.value { out.append(a) }
        }
        self.articles = out
    }
}

private struct LossyArticle: Decodable {
    let value: Article?
    init(from decoder: Decoder) throws {
        self.value = try? Article(from: decoder)
    }
}

