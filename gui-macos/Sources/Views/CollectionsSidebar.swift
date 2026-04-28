import SwiftUI

struct CollectionsSidebar: View {
    @EnvironmentObject private var state: AppState

    var body: some View {
        List(selection: Binding(
            get: { state.selection },
            set: { state.selectSidebar($0 ?? .allArticles) }
        )) {
            Section("Library") {
                Label("All articles", systemImage: "tray.full")
                    .tag(SidebarSelection.allArticles)
            }
            Section("Collections") {
                ForEach(state.collections) { c in
                    HStack {
                        Label(c.name, systemImage: "folder")
                        Spacer()
                        Text("\(c.articleCount)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .tag(SidebarSelection.collection(c.name))
                }
            }
        }
        .listStyle(.sidebar)
        .frame(minWidth: 200)
    }
}
