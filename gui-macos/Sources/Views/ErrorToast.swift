import SwiftUI

/// Top-of-window error banner for daemon errors that the user needs to
/// actually read (e.g. "Collection not found", validation errors). Replaces
/// the previous tiny footer overlay that clipped messages to two 9pt lines.
///
/// Drives off ``AppState.lastError``: appears whenever it's non-nil; the
/// user can dismiss it (clears ``lastError``) or it auto-dismisses after
/// 8 seconds. New errors replace the current one in place.
struct ErrorToast: View {
    @EnvironmentObject private var state: AppState
    @State private var dismissTask: Task<Void, Never>? = nil

    var body: some View {
        if let err = state.lastError, !err.isEmpty {
            content(err)
                .transition(.move(edge: .top).combined(with: .opacity))
                .onAppear { scheduleAutoDismiss() }
                .onChange(of: err) { _, _ in scheduleAutoDismiss() }
        }
    }

    private func content(_ err: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 13))
                .foregroundStyle(Theme.bad)
                .padding(.top, 1)
            VStack(alignment: .leading, spacing: 2) {
                Text("Daemon error")
                    .font(.system(size: 11, weight: .semibold))
                    .tracking(0.4)
                    .foregroundStyle(Theme.ink)
                Text(err)
                    .font(.system(size: 12))
                    .foregroundStyle(Theme.inkSoft)
                    .textSelection(.enabled)
                    .lineLimit(6)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 12)
            Button { dismiss() } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(Theme.inkMute)
                    .padding(4)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .frame(maxWidth: 520, alignment: .leading)
        .background(Theme.paper, in: RoundedRectangle(cornerRadius: 8))
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(Theme.bad.opacity(0.4), lineWidth: 1)
        )
        .shadow(color: Color.black.opacity(0.18), radius: 8, x: 0, y: 4)
        .padding(.top, 12)
    }

    private func scheduleAutoDismiss() {
        dismissTask?.cancel()
        dismissTask = Task { [weak state = state] in
            try? await Task.sleep(nanoseconds: 8_000_000_000)
            guard !Task.isCancelled else { return }
            await MainActor.run { state?.lastError = nil }
        }
    }

    private func dismiss() {
        dismissTask?.cancel()
        state.lastError = nil
    }
}
