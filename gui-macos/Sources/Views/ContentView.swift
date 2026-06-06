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
                .background(Theme.paper)
            case .down(let msg):
                DaemonDownView(message: msg)
            case .unknown:
                ConnectingView()
            }
        }
        .overlay(alignment: .top) {
            ErrorToast()
                .animation(.easeInOut(duration: 0.18), value: state.lastError)
        }
    }
}

private struct ConnectingView: View {
    var body: some View {
        VStack(spacing: 12) {
            ProgressView().controlSize(.small)
            Text("Connecting to daemon…")
                .font(.serif(15))
                .foregroundStyle(Theme.inkMute)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Theme.paper)
    }
}

private struct DaemonDownView: View {
    let message: String
    @EnvironmentObject private var state: AppState

    var body: some View {
        VStack(spacing: 10) {
            Image(systemName: "bolt.slash")
                .font(.system(size: 28))
                .foregroundStyle(Theme.inkMute.opacity(0.8))

            Text("The daemon is asleep.")
                .font(.serif(17, weight: .medium))
                .foregroundStyle(Theme.ink)

            Text("scopus-for-dobby's local server isn't responding on :8765. Start it from a terminal, or click Retry.")
                .font(.system(size: 12))
                .foregroundStyle(Theme.inkMute)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 320)

            Text("scopus-for-dobby serve")
                .font(.system(size: 12, design: .monospaced))
                .foregroundStyle(Theme.inkSoft)
                .padding(.horizontal, 14)
                .padding(.vertical, 8)
                .background(Theme.paperDeep, in: RoundedRectangle(cornerRadius: 6))
                .overlay(
                    RoundedRectangle(cornerRadius: 6)
                        .stroke(Theme.paperEdge, lineWidth: 1)
                )
                .padding(.top, 4)

            HStack(spacing: 10) {
                Button {
                    Task { await state.launchDaemon() }
                } label: {
                    HStack(spacing: 6) {
                        if state.isLaunchingDaemon {
                            ProgressView()
                                .controlSize(.small)
                                .tint(Theme.onAccent)
                        } else {
                            Image(systemName: "bolt.fill")
                                .font(.system(size: 11, weight: .semibold))
                        }
                        Text(state.isLaunchingDaemon ? "Starting…" : "Launch daemon")
                    }
                }
                .buttonStyle(PrimaryButtonStyle())
                .keyboardShortcut(.defaultAction)
                .disabled(state.isLaunchingDaemon)

                Button("Retry") {
                    Task { await state.bootstrap() }
                }
                .buttonStyle(.plain)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(Theme.inkSoft)
                .padding(.horizontal, 12)
                .padding(.vertical, 6)
                .disabled(state.isLaunchingDaemon)
            }
            .padding(.top, 6)

            if !message.isEmpty {
                Text(message)
                    .font(.system(size: 11))
                    .foregroundStyle(Theme.inkFaint)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 360)
                    .padding(.top, 8)
            }
        }
        .padding(40)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Theme.paper)
    }
}
