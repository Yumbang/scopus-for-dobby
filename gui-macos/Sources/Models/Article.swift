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
        case tags, notes
        case addedAt = "added_at"
        case updatedAt = "updated_at"
    }
}

struct Author: Decodable, Hashable {
    let auid: String?
    let name: String?
}

/// Response shape from ``GET /articles`` and ``GET /search/{fts,like}``.
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
}
