import SwiftUI

struct CollectionsSidebar: View {
    @EnvironmentObject private var state: AppState
    @ObservedObject private var client = DaemonClient.shared
    @State private var showingNewCollection = false
    @State private var renamingCollection: String? = nil
    @State private var renameDraft: String = ""
    @State private var mergingCollection: String? = nil

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    librarySection
                    collectionsSection
                }
                .padding(.horizontal, 8)
                .padding(.top, 14)
                .padding(.bottom, 12)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            footer
        }
        .frame(minWidth: 220)
        .background(Theme.paperDeep)
        .overlay(alignment: .trailing) {
            Rectangle().fill(Theme.paperEdge).frame(width: 1)
        }
        .sheet(isPresented: $showingNewCollection) {
            NewCollectionSheet { name in
                Task { await state.createCollection(name) }
            }
        }
        .sheet(item: Binding(
            get: { mergingCollection.map(MergeContext.init) },
            set: { mergingCollection = $0?.src }
        )) { ctx in
            MergeCollectionSheet(
                src: ctx.src,
                candidates: state.collections.map(\.name).filter { $0 != ctx.src }
            ) { dst in
                Task { await state.mergeCollections(src: ctx.src, into: dst) }
            }
        }
    }

    private struct MergeContext: Identifiable {
        let src: String
        var id: String { src }
    }

    private var librarySection: some View {
        VStack(alignment: .leading, spacing: 2) {
            sectionTitle("Library")
            sidebarRow(
                label: "All articles",
                systemImage: "tray.full",
                count: state.articles.count,
                isActive: state.selection == .allArticles
            ) {
                state.selectSidebar(.allArticles)
            }
        }
    }

    private var collectionsSection: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 6) {
                Text("Collections")
                    .font(.system(size: 10.5, weight: .semibold))
                    .tracking(1.0)
                    .textCase(.uppercase)
                    .foregroundStyle(Theme.inkMute)
                Text("\(state.collections.count)")
                    .font(.system(size: 10))
                    .monospacedDigit()
                    .foregroundStyle(Theme.inkMute.opacity(0.7))
                Spacer()
                Button { showingNewCollection = true } label: {
                    Image(systemName: "plus")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(Theme.inkMute)
                        .padding(.horizontal, 4)
                        .padding(.vertical, 2)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .help("New collection")
            }
            .padding(.horizontal, 10)
            .padding(.top, 4)
            .padding(.bottom, 6)

            ForEach(state.collections) { c in
                if renamingCollection == c.name {
                    inlineRenameRow(name: c.name)
                } else {
                    sidebarRow(
                        label: c.name,
                        systemImage: "folder",
                        count: c.articleCount,
                        isActive: state.selection == .collection(c.name),
                        isEmpty: c.articleCount == 0
                    ) {
                        state.selectSidebar(.collection(c.name))
                    }
                    .contextMenu {
                        Button("Rename…") { startRename(c.name) }
                        Button("Merge into…") { mergingCollection = c.name }
                            .disabled(state.collections.count < 2)
                        Divider()
                        Button("Delete \"\(c.name)\"", role: .destructive) {
                            Task { await state.deleteCollection(c.name) }
                        }
                    }
                }
            }
        }
    }

    private func startRename(_ name: String) {
        renameDraft = name
        renamingCollection = name
    }

    private func commitRename(original: String) {
        let trimmed = renameDraft.trimmingCharacters(in: .whitespaces)
        renamingCollection = nil
        guard !trimmed.isEmpty, trimmed != original else { return }
        Task { await state.renameCollection(original, to: trimmed) }
    }

    @ViewBuilder
    private func inlineRenameRow(name: String) -> some View {
        HStack(spacing: 8) {
            Image(systemName: "folder")
                .font(.system(size: 12))
                .foregroundStyle(Theme.accentDeep)
                .frame(width: 14)
            InlineRenameField(
                text: $renameDraft,
                onCommit: { commitRename(original: name) },
                onCancel: { renamingCollection = nil }
            )
            Spacer(minLength: 4)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            Theme.paper,
            in: RoundedRectangle(cornerRadius: 6)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 6)
                .stroke(Theme.accent, lineWidth: 1.5)
        )
    }

    private func sectionTitle(_ s: String) -> some View {
        Text(s)
            .font(.system(size: 10.5, weight: .semibold))
            .tracking(1.0)
            .textCase(.uppercase)
            .foregroundStyle(Theme.inkMute)
            .padding(.horizontal, 10)
            .padding(.top, 4)
            .padding(.bottom, 6)
    }

    @ViewBuilder
    private func sidebarRow(
        label: String,
        systemImage: String,
        count: Int,
        isActive: Bool,
        isEmpty: Bool = false,
        action: @escaping () -> Void
    ) -> some View {
        let labelColor: Color = isActive ? Theme.accentInk : (isEmpty ? Theme.inkMute : Theme.ink)
        let iconColor: Color  = isActive ? Theme.accentInk : Theme.inkSoft
        let countColor: Color = isActive ? Theme.accentInk.opacity(0.75) : Theme.inkMute

        Button(action: action) {
            HStack(spacing: 8) {
                Image(systemName: systemImage)
                    .font(.system(size: 12))
                    .foregroundStyle(iconColor)
                    .frame(width: 14)
                Text(label)
                    .font(.system(size: 13, weight: isActive ? .medium : .regular))
                    .foregroundStyle(labelColor)
                    .lineLimit(1)
                    .truncationMode(.tail)
                Spacer(minLength: 4)
                Text("\(count)")
                    .font(.system(size: 11))
                    .monospacedDigit()
                    .foregroundStyle(countColor)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
            .background(
                isActive ? Theme.accentSoft : Color.clear,
                in: RoundedRectangle(cornerRadius: 6)
            )
        }
        .buttonStyle(.plain)
    }

    private var footer: some View {
        let isUp: Bool = {
            if case .running = state.daemonStatus { return true } else { return false }
        }()
        let dotColor = isUp ? Theme.good : Theme.bad
        return HStack(spacing: 8) {
            ZStack {
                Circle()
                    .fill(dotColor.opacity(0.22))
                    .frame(width: 13, height: 13)
                Circle()
                    .fill(dotColor)
                    .frame(width: 7, height: 7)
            }
            Text(isUp ? "Daemon · live" : "Daemon · offline")
                .font(.system(size: 11))
                .foregroundStyle(Theme.inkMute)
            Spacer()
            Text(client.portLabel ?? "—")
                .font(.system(size: 11))
                .monospacedDigit()
                .foregroundStyle(Theme.inkMute)
                .opacity(0.7)
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .overlay(alignment: .top) {
            Rectangle().fill(Theme.paperEdge).frame(height: 1)
        }
    }
}
