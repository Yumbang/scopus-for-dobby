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
    let affiliations: [String]?
    let indexKeywords: [String]?
    let subjectAreas: [String]?
    let tags: [String]?
    let notes: String?
    let addedAt: String?
    let updatedAt: String?
    let openalexId: String?
    let oaStatus: String?
    let oaUrl: String?
    let openalexCitedBy: Int?
    let openalexTopics: [String]?
    let openalexEnrichedAt: String?
    let fulltextFetchedAt: String?

    /// Collection membership. Only ``GET /articles/{eid}`` carries it; list
    /// rows come straight out of ``SELECT * FROM articles`` and have no such
    /// column, so this is nil for every row in a list response.
    let collections: [String]?

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
        case affiliations
        case indexKeywords = "index_keywords"
        case subjectAreas = "subject_areas"
        // Daemon emits user-metadata fields under leading-underscore names
        // (``_tags``, ``_notes``, ``_added_at``, ``_updated_at``) to distinguish
        // them from Scopus-imported columns. Match the wire format.
        case tags = "_tags"
        case notes = "_notes"
        case addedAt = "_added_at"
        case updatedAt = "_updated_at"
        case openalexId = "openalex_id"
        case oaStatus = "oa_status"
        case oaUrl = "oa_url"
        case openalexCitedBy = "openalex_cited_by"
        case openalexTopics = "openalex_topics"
        case openalexEnrichedAt = "openalex_enriched_at"
        case fulltextFetchedAt = "fulltext_fetched_at"
        case collections
    }

    /// Hand-written rather than synthesized so the five JSON-array columns can
    /// be decoded leniently. Their element shape is *not* uniform on the wire:
    /// ``affiliations`` is ``[String]`` when the row came from a Scopus search
    /// (``_normalize_entry``) and ``[{"name","city","country"}]`` when it came
    /// from an abstract fetch (``core/abstract.py``); ``subject_areas`` is
    /// always ``[{"name","code","abbrev"}]``. A strict ``[String]`` decode
    /// would throw on those, and because ``LossyArticle`` catches per *row*,
    /// one such throw silently drops the whole article from the list rather
    /// than one field. See ``LabelList``.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        eid = try c.decode(String.self, forKey: .eid)
        scopusId = try c.decodeIfPresent(String.self, forKey: .scopusId)
        doi = try c.decodeIfPresent(String.self, forKey: .doi)
        title = try c.decodeIfPresent(String.self, forKey: .title)
        firstAuthor = try c.decodeIfPresent(String.self, forKey: .firstAuthor)
        allAuthors = try c.decodeIfPresent([Author].self, forKey: .allAuthors)
        journal = try c.decodeIfPresent(String.self, forKey: .journal)
        volume = try c.decodeIfPresent(String.self, forKey: .volume)
        issue = try c.decodeIfPresent(String.self, forKey: .issue)
        pages = try c.decodeIfPresent(String.self, forKey: .pages)
        coverDate = try c.decodeIfPresent(String.self, forKey: .coverDate)
        citedBy = try c.decodeIfPresent(Int.self, forKey: .citedBy)
        openAccess = try c.decodeIfPresent(Bool.self, forKey: .openAccess)
        abstract = try c.decodeIfPresent(String.self, forKey: .abstract)
        keywords = try c.decodeIfPresent(String.self, forKey: .keywords)
        issn = try c.decodeIfPresent(String.self, forKey: .issn)
        sourceType = try c.decodeIfPresent(String.self, forKey: .sourceType)
        affiliations = LabelList.labels(in: c, forKey: .affiliations)
        indexKeywords = LabelList.labels(in: c, forKey: .indexKeywords)
        subjectAreas = LabelList.labels(in: c, forKey: .subjectAreas)
        tags = try c.decodeIfPresent([String].self, forKey: .tags)
        notes = try c.decodeIfPresent(String.self, forKey: .notes)
        addedAt = try c.decodeIfPresent(String.self, forKey: .addedAt)
        updatedAt = try c.decodeIfPresent(String.self, forKey: .updatedAt)
        openalexId = try c.decodeIfPresent(String.self, forKey: .openalexId)
        oaStatus = try c.decodeIfPresent(String.self, forKey: .oaStatus)
        oaUrl = try c.decodeIfPresent(String.self, forKey: .oaUrl)
        openalexCitedBy = try c.decodeIfPresent(Int.self, forKey: .openalexCitedBy)
        openalexTopics = LabelList.labels(in: c, forKey: .openalexTopics)
        openalexEnrichedAt = try c.decodeIfPresent(String.self, forKey: .openalexEnrichedAt)
        fulltextFetchedAt = try c.decodeIfPresent(String.self, forKey: .fulltextFetchedAt)
        collections = LabelList.labels(in: c, forKey: .collections)
    }
}

// MARK: - Derived conveniences
//
// Presentation-agnostic reads over columns whose meaning is spread across
// several fields. Kept on the model so the list row and the detail pane can
// never disagree about whether a paper is free to read.

extension Article {
    /// The OA colour OpenAlex assigned (gold/green/hybrid/bronze/closed),
    /// lowercased. Nil when the column is empty — "never enriched", which is
    /// a different statement from ``"closed"`` ("enriched, and there is no
    /// free copy").
    var openAccessStatus: String? {
        let s = (oaStatus ?? "").trimmingCharacters(in: .whitespaces).lowercased()
        return s.isEmpty ? nil : s
    }

    /// Link to a free copy (PDF or landing page) when OpenAlex found one.
    var freeCopyURL: URL? {
        let raw = (oaUrl ?? "").trimmingCharacters(in: .whitespaces)
        guard !raw.isEmpty else { return nil }
        return URL(string: raw)
    }

    /// True when something says this is readable for free: the OpenAlex OA
    /// colour (anything but "closed") or, absent enrichment, Scopus's own
    /// ``open_access`` flag.
    var isFreeToRead: Bool {
        if let status = openAccessStatus { return status != "closed" }
        return openAccess == true
    }

    /// True once ``fulltext`` has written the Elsevier XML to disk.
    var hasCachedFulltext: Bool { !(fulltextFetchedAt ?? "").isEmpty }

    var hasNote: Bool {
        !(notes ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
}

struct Author: Decodable, Hashable {
    let auid: String?
    let name: String?
}

/// A JSON-array column read as a flat list of labels, whatever its elements
/// happen to be: plain strings pass through, objects give up their label under
/// the first key that has one, and anything else is skipped. Mirrors the key
/// list in ``core/text_analysis.py::_LABEL_KEYS``, which solves the same
/// problem on the Python side.
///
/// Decoding never throws — see ``Article.init(from:)`` for why that matters.
private struct LabelList: Decodable {
    let values: [String]

    /// Keys an entry may hide its label under. ``$`` is the raw Scopus JSON
    /// convention, in case unnormalized data leaks through.
    private static let labelKeys = ["name", "label", "display_name", "term", "$"]

    init(from decoder: Decoder) throws {
        if var arr = try? decoder.unkeyedContainer() {
            var out: [String] = []
            out.reserveCapacity(arr.count ?? 0)
            while !arr.isAtEnd {
                // ``Element.init`` cannot throw, so the container always
                // advances — no risk of spinning on an element we can't read.
                let element = try arr.decode(Element.self)
                if let label = element.label { out.append(label) }
            }
            values = out
            return
        }
        // A scalar where an array was expected: keep it rather than lose it.
        if let single = try? decoder.singleValueContainer().decode(String.self),
           !single.isEmpty {
            values = [single]
            return
        }
        values = []
    }

    /// Decode ``key`` as a label list, or nil when the key is absent, null, or
    /// unreadable. Never throws.
    static func labels(
        in container: KeyedDecodingContainer<Article.CodingKeys>,
        forKey key: Article.CodingKeys
    ) -> [String]? {
        // ``decodeNil`` before ``decode``: a custom Decodable is handed a
        // decoder over the null and would report an empty list, conflating
        // "column is NULL" (``affiliations`` has no DDL default) with "column
        // holds []" (every v2 column does).
        guard container.contains(key),
              (try? container.decodeNil(forKey: key)) == false,
              let list = try? container.decode(LabelList.self, forKey: key)
        else { return nil }
        return list.values
    }

    private struct Element: Decodable {
        let label: String?

        init(from decoder: Decoder) throws {
            if let s = try? decoder.singleValueContainer().decode(String.self) {
                label = s.isEmpty ? nil : s
                return
            }
            if let obj = try? decoder.container(keyedBy: AnyKey.self) {
                for name in LabelList.labelKeys {
                    guard let key = AnyKey(stringValue: name),
                          let v = try? obj.decode(String.self, forKey: key),
                          !v.isEmpty
                    else { continue }
                    label = v
                    return
                }
            }
            label = nil
        }
    }

    private struct AnyKey: CodingKey {
        let stringValue: String
        var intValue: Int? { nil }
        init?(stringValue: String) { self.stringValue = stringValue }
        init?(intValue: Int) { return nil }
    }
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
