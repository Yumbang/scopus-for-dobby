import SwiftUI

/// Three-pane root: collections sidebar → article list → detail.
struct ContentView: View {
    @EnvironmentObject private var state: AppState

    var body: some View {
        Group {
            switch state.daemonStatus {
            case .running:
                NavigationSplitView {
                    CollectionsSidebar()
                } content: {
                    ArticleListView()
                } detail: {
                    ArticleDetailView()
                }
            case .down(let msg):
                DaemonDownView(message: msg)
            case .unknown:
                ProgressView("Connecting to daemon…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
    }
}

private struct DaemonDownView: View {
    let message: String
    @EnvironmentObject private var state: AppState

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "bolt.slash")
                .font(.system(size: 48))
                .foregroundStyle(.secondary)
            Text("Daemon not reachable")
                .font(.title2)
            Text(message)
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 480)
            Button("Retry") {
                Task { await state.bootstrap() }
            }
            .keyboardShortcut(.defaultAction)
        }
        .padding()
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
