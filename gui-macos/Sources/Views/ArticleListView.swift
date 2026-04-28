import SwiftUI

struct ArticleListView: View {
    @EnvironmentObject private var state: AppState

    var body: some View {
        List(selection: Binding(
            get: { state.selectedArticleEid },
            set: { state.selectedArticleEid = $0 }
        )) {
            ForEach(state.articles) { a in
                ArticleRow(article: a)
                    .tag(String?.some(a.eid))
            }
        }
        .navigationTitle(state.selection.displayTitle)
        .frame(minWidth: 360)
        .overlay {
            if state.articles.isEmpty {
                ContentUnavailableView(
                    "No articles",
                    systemImage: "doc.text",
                    description: Text("Use `scopus-for-dobby search` or import to populate.")
                )
            }
        }
    }
}

private struct ArticleRow: View {
    let article: Article

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(article.title ?? "(untitled)")
                .font(.headline)
                .lineLimit(2)
            HStack(spacing: 8) {
                if let author = article.firstAuthor {
                    Text(author).font(.caption)
                }
                if let journal = article.journal {
                    Text("•").foregroundStyle(.tertiary)
                    Text(journal).font(.caption).italic()
                }
                if let year = article.coverDate?.prefix(4) {
                    Text("•").foregroundStyle(.tertiary)
                    Text(String(year)).font(.caption)
                }
                if let cited = article.citedBy, cited > 0 {
                    Spacer()
                    Label("\(cited)", systemImage: "quote.bubble")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
            .foregroundStyle(.secondary)
        }
        .padding(.vertical, 2)
    }
}
