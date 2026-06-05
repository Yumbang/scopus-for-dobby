import SwiftUI

struct ArticleListView: View {
    @EnvironmentObject private var state: AppState
    @FocusState private var searchFocused: Bool

    var body: some View {
        let visible = state.sortedArticles()
        return VStack(spacing: 0) {
            header
            if visible.isEmpty {
                emptyState
            } else {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        ForEach(Array(visible.enumerated()), id: \.element.eid) { index, a in
                            ArticleRow(
                                article: a,
                                isSelected: state.selectedArticleEid == a.eid,
                                isInMultiSelection: state.multiSelection.contains(a.eid)
                            )
                            .contentShape(Rectangle())
                            // SwiftUI's ``onTapGesture`` does not deliver
                            // modifier state to the closure (NSEvent.modifierFlags
                            // is unreliable here — by the time the closure runs
                            // the event has often ended). Dispatch by composing
                            // three gestures, one per modifier set, so SwiftUI
                            // routes the click based on modifiers held at
                            // click-time. Order matters: most-specific first.
                            .gesture(TapGesture().modifiers(.shift).onEnded {
                                handleShiftTap(eid: a.eid, index: index, visible: visible)
                            })
                            .gesture(TapGesture().modifiers(.command).onEnded {
                                handleCommandTap(eid: a.eid)
                            })
                            .onTapGesture { handlePlainTap(eid: a.eid) }
                            Rectangle()
                                .fill(Theme.paperEdge)
                                .frame(height: 1)
                        }
                    }
                }
            }
        }
        .frame(minWidth: 380)
        .background(Theme.paper)
        .overlay(alignment: .trailing) {
            Rectangle().fill(Theme.paperEdge).frame(width: 1)
        }
        .onChange(of: state.searchQuery) { _, _ in
            state.runSearchDebounced()
        }
    }

    private func handlePlainTap(eid: String) {
        state.multiSelection.removeAll()
        state.selectedArticleEid = eid
        state.multiSelectAnchor = eid
    }

    private func handleCommandTap(eid: String) {
        if state.multiSelection.contains(eid) {
            state.multiSelection.remove(eid)
        } else {
            if state.multiSelection.isEmpty, let anchor = state.selectedArticleEid {
                state.multiSelection.insert(anchor)
            }
            state.multiSelection.insert(eid)
        }
        state.selectedArticleEid = eid
        // Don't move multiSelectAnchor — Finder/Mail keep the shift-anchor
        // pinned to the last plain click, so subsequent shift-clicks range
        // from there rather than from each ⌘-click.
    }

    private func handleShiftTap(eid: String, index: Int, visible: [Article]) {
        let anchorEid = state.multiSelectAnchor ?? state.selectedArticleEid ?? eid
        if let anchorIdx = visible.firstIndex(where: { $0.eid == anchorEid }) {
            let lo = min(anchorIdx, index)
            let hi = max(anchorIdx, index)
            state.multiSelection = Set(visible[lo...hi].map(\.eid))
        } else {
            state.multiSelection = [eid]
        }
        state.selectedArticleEid = eid
    }

    private var header: some View {
        HStack(spacing: 10) {
            HStack(spacing: 6) {
                Image(systemName: state.selection == .allArticles ? "tray.full" : "folder.fill")
                    .font(.system(size: 13))
                    .foregroundStyle(Theme.accentDeep)
                Text(state.selection.displayTitle)
                    .font(.system(size: 15, weight: .semibold))
                    .tracking(-0.15)
                    .foregroundStyle(Theme.ink)
                    .lineLimit(1)
                Text("· \(state.articles.count)")
                    .font(.system(size: 12))
                    .monospacedDigit()
                    .foregroundStyle(Theme.inkMute)
                if state.multiSelection.count > 1 {
                    Text("· \(state.multiSelection.count) selected")
                        .font(.system(size: 11, weight: .medium))
                        .tracking(0.2)
                        .foregroundStyle(Theme.accentInk)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 1)
                        .background(Theme.accentSoft, in: Capsule())
                }
            }
            Spacer()
            sortMenu
            searchField
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .overlay(alignment: .bottom) {
            Rectangle().fill(Theme.paperEdge).frame(height: 1)
        }
    }

    private var sortMenu: some View {
        Menu {
            ForEach(SortAxis.allCases) { axis in
                Button {
                    state.sortAxis = axis
                } label: {
                    if state.sortAxis == axis {
                        Label(axis.label, systemImage: "checkmark")
                    } else {
                        Text(axis.label)
                    }
                }
            }
        } label: {
            HStack(spacing: 4) {
                Image(systemName: "arrow.up.arrow.down")
                    .font(.system(size: 10, weight: .medium))
                Text(state.sortAxis.label)
                    .font(.system(size: 11, weight: .medium))
            }
            .foregroundStyle(Theme.inkSoft)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(Theme.paperEdge.opacity(0.5), in: RoundedRectangle(cornerRadius: 5))
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(.hidden)
        .fixedSize()
    }

    private var searchField: some View {
        let active = !state.searchQuery.isEmpty || searchFocused
        return HStack(spacing: 8) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 11))
                .foregroundStyle(active ? Theme.accentDeep : Theme.inkMute)
            TextField("Search title, abstract, keywords…", text: $state.searchQuery)
                .textFieldStyle(.plain)
                .font(.system(size: 12))
                .foregroundStyle(Theme.ink)
                .focused($searchFocused)
                .frame(minWidth: 140, maxWidth: 220)
            if state.selection != .allArticles, !state.searchQuery.isEmpty {
                Text("in \(state.selection.displayTitle)")
                    .font(.system(size: 10.5))
                    .tracking(0.3)
                    .foregroundStyle(Theme.accentInk)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 1)
                    .background(Theme.accentSoft, in: Capsule())
                    .lineLimit(1)
            }
            if !state.searchQuery.isEmpty {
                Button { state.clearSearch() } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.system(size: 11))
                        .foregroundStyle(Theme.inkMute)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 4)
        .frame(height: 28)
        .background(active ? Theme.paper : Theme.paperEdge,
                    in: RoundedRectangle(cornerRadius: 6))
        .overlay(
            RoundedRectangle(cornerRadius: 6)
                .stroke(active ? Theme.accent : Color.clear, lineWidth: 1.5)
        )
    }

    private var emptyState: some View {
        VStack(spacing: 10) {
            Image(systemName: state.selection == .allArticles ? "tray" : "folder")
                .font(.system(size: 28))
                .foregroundStyle(Theme.inkMute.opacity(0.8))
            Text(state.selection == .allArticles
                 ? "Your library is empty."
                 : "Nothing in this collection yet.")
                .font(.serif(17, weight: .medium))
                .foregroundStyle(Theme.ink)
            Text(state.selection == .allArticles
                 ? "Run a search from the CLI — articles you collect there will appear here."
                 : "Drag articles here from any list, or use Add to collection from a selection.")
                .font(.system(size: 12))
                .foregroundStyle(Theme.inkMute)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 280)
            if state.selection == .allArticles {
                Text(#"scopus-for-dobby search "membrane fouling""#)
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
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(40)
    }
}

private struct ArticleRow: View {
    let article: Article
    let isSelected: Bool
    let isInMultiSelection: Bool

    private var stripeColor: Color {
        if isInMultiSelection { return Theme.accent }
        if isSelected { return Theme.accent }
        return .clear
    }

    private var rowBackground: Color {
        if isInMultiSelection { return Theme.accentSoft.opacity(0.7) }
        if isSelected { return Theme.accentSoft }
        return .clear
    }

    var body: some View {
        HStack(spacing: 0) {
            Rectangle()
                .fill(stripeColor)
                .frame(width: 3)
            VStack(alignment: .leading, spacing: 4) {
                Text(article.title ?? "(untitled)")
                    .font(.system(size: 13, weight: .semibold))
                    .tracking(-0.07)
                    .foregroundStyle(Theme.ink)
                    .lineLimit(2)
                    .frame(maxWidth: .infinity, alignment: .leading)

                HStack(spacing: 6) {
                    if let author = article.firstAuthor {
                        Text(author).foregroundStyle(Theme.inkSoft)
                    }
                    if let journal = article.journal {
                        Text("·").foregroundStyle(Theme.inkMute).opacity(0.55)
                        Text(journal).italic().foregroundStyle(Theme.inkSoft)
                    }
                    if let year = article.coverDate?.prefix(4), !year.isEmpty {
                        Text("·").foregroundStyle(Theme.inkMute).opacity(0.55)
                        Text(String(year)).foregroundStyle(Theme.inkSoft)
                    }
                    Spacer(minLength: 6)
                    if let cited = article.citedBy, cited > 0 {
                        Image(systemName: "quote.bubble")
                            .font(.system(size: 10))
                            .foregroundStyle(Theme.inkMute)
                        Text("\(cited)")
                            .font(.system(size: 11))
                            .monospacedDigit()
                            .foregroundStyle(Theme.inkMute)
                    }
                }
                .font(.system(size: 12))
                .lineLimit(1)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(rowBackground)
    }
}
