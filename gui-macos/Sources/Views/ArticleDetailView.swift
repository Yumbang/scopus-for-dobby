import SwiftUI

struct ArticleDetailView: View {
    @EnvironmentObject private var state: AppState
    @State private var loaded: Article? = nil
    @State private var loadError: String? = nil

    var body: some View {
        Group {
            if let article = loaded {
                detail(for: article)
            } else if state.selectedArticleEid == nil {
                ContentUnavailableView("Select an article",
                                       systemImage: "doc.text.magnifyingglass")
            } else if let err = loadError {
                ContentUnavailableView("Failed to load",
                                       systemImage: "exclamationmark.triangle",
                                       description: Text(err))
            } else {
                ProgressView()
            }
        }
        .frame(minWidth: 360)
        .onChange(of: state.selectedArticleEid) { _, eid in
            Task { await load(eid: eid) }
        }
        .task(id: state.selectedArticleEid) {
            await load(eid: state.selectedArticleEid)
        }
    }

    @ViewBuilder
    private func detail(for article: Article) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text(article.title ?? "(untitled)")
                    .font(.title2)
                    .fontWeight(.semibold)

                HStack(spacing: 12) {
                    if let a = article.firstAuthor { Text(a) }
                    if let j = article.journal {
                        Text("•").foregroundStyle(.tertiary)
                        Text(j).italic()
                    }
                    if let d = article.coverDate {
                        Text("•").foregroundStyle(.tertiary)
                        Text(d)
                    }
                }
                .font(.subheadline)
                .foregroundStyle(.secondary)

                if let cited = article.citedBy, cited > 0 {
                    Label("\(cited) citations", systemImage: "quote.bubble")
                        .font(.caption)
                }

                if let doi = article.doi, !doi.isEmpty {
                    LabeledContent("DOI") {
                        if let url = URL(string: "https://doi.org/\(doi)") {
                            Link(doi, destination: url)
                        } else {
                            Text(doi)
                        }
                    }
                }

                if let abstract = article.abstract, !abstract.isEmpty {
                    Text("Abstract").font(.headline).padding(.top, 8)
                    Text(abstract).textSelection(.enabled)
                }

                if let kw = article.keywords, !kw.isEmpty {
                    Text("Keywords").font(.headline).padding(.top, 8)
                    Text(kw)
                }

                if let tags = article.tags, !tags.isEmpty {
                    Text("Tags").font(.headline).padding(.top, 8)
                    HStack { ForEach(tags, id: \.self) { Text($0).padding(.horizontal, 6).padding(.vertical, 2).background(Color.secondary.opacity(0.15)).clipShape(Capsule()) } }
                }

                if let notes = article.notes, !notes.isEmpty {
                    Text("Notes").font(.headline).padding(.top, 8)
                    Text(notes).textSelection(.enabled)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(20)
        }
    }

    private func load(eid: String?) async {
        loadError = nil
        guard let eid else { loaded = nil; return }
        do {
            loaded = try await DaemonClient.shared.article(eid: eid)
        } catch {
            loaded = nil
            loadError = error.localizedDescription
        }
    }
}
