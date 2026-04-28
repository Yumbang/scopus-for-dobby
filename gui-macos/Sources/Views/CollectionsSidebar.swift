import SwiftUI

struct CollectionsSidebar: View {
    @EnvironmentObject private var state: AppState

    var body: some View {
        List(selection: Binding(
            get: { state.selectedCollection },
            set: { state.selectCollection($0) }
        )) {
            Section("Library") {
                Label("All articles", systemImage: "tray.full")
                    .tag(String?.none)
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
                    .tag(String?.some(c.name))
                }
            }
        }
        .listStyle(.sidebar)
        .frame(minWidth: 200)
    }
}
