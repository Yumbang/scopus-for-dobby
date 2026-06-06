import SwiftUI

struct ArticleDetailView: View {
    @EnvironmentObject private var state: AppState
    @State private var loaded: Article? = nil
    @State private var loadError: String? = nil

    // Tag editor — visible only when the user clicks "+ Add tag".
    @State private var tagDraft: String = ""
    @State private var isAddingTag: Bool = false
    @FocusState private var tagFieldFocused: Bool

    // Note editor — read view by default; flips to TextEditor when "Edit" tapped.
    @State private var isEditingNote: Bool = false
    @State private var noteDraft: String = ""
    @FocusState private var noteFieldFocused: Bool

    var body: some View {
        Group {
            if state.multiSelection.count > 1 {
                BatchPanel()
            } else if let article = loaded {
                detail(for: article)
            } else if state.selectedArticleEid == nil {
                emptyDetail(
                    icon: "doc.text.magnifyingglass",
                    head: "Select an article",
                    sub: "Pick something from the list to read its abstract, tags, and notes."
                )
            } else if let err = loadError {
                emptyDetail(
                    icon: "exclamationmark.triangle",
                    head: "Couldn't load this one.",
                    sub: err
                )
            } else {
                ProgressView()
                    .controlSize(.small)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .frame(minWidth: 420)
        .background(Theme.paper)
        .onChange(of: state.selectedArticleEid) { _, eid in
            // Reset editor state when switching articles.
            isAddingTag = false
            isEditingNote = false
            tagDraft = ""
            Task { await load(eid: eid) }
        }
        .task(id: state.selectedArticleEid) {
            await load(eid: state.selectedArticleEid)
        }
    }

    @ViewBuilder
    private func detail(for article: Article) -> some View {
        VStack(spacing: 0) {
            detailHeader
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    Text(article.title ?? "(untitled)")
                        .font(.serif(20, weight: .medium))
                        .tracking(-0.2)
                        .foregroundStyle(Theme.ink)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.bottom, 12)

                    byline(for: article)
                        .padding(.bottom, 14)

                    statsBar(for: article)
                        .padding(.bottom, 16)
                    Rectangle()
                        .fill(Theme.paperEdge)
                        .frame(height: 1)
                        .padding(.bottom, 22)

                    if let abstract = article.abstract, !abstract.isEmpty {
                        section("Abstract") {
                            Text(abstract)
                                .font(.serif(14))
                                .foregroundStyle(Theme.ink)
                                .lineSpacing(4)
                                .textSelection(.enabled)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    if let kw = article.keywords, !kw.isEmpty {
                        section("Keywords") {
                            Text(kw)
                                .font(.system(size: 12))
                                .foregroundStyle(Theme.inkSoft)
                                .lineSpacing(2)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    section("Tags") {
                        tagsEditor(for: article)
                    }
                    sectionWithEdit(
                        "Notes",
                        editLabel: (article.notes?.isEmpty ?? true) ? "Add note" : "Edit",
                        onEdit: { startEditingNote(article) }
                    ) {
                        notesView(for: article)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 32)
                .padding(.top, 28)
                .padding(.bottom, 40)
            }
        }
    }

    private var detailHeader: some View {
        HStack(spacing: 8) {
            Image(systemName: state.selection == .allArticles ? "tray.full" : "folder.fill")
                .font(.system(size: 11))
                .foregroundStyle(Theme.inkMute)
            Text(state.selection.displayTitle)
                .font(.system(size: 12))
                .foregroundStyle(Theme.inkSoft)
                .lineLimit(1)
            Spacer()
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .overlay(alignment: .bottom) {
            Rectangle().fill(Theme.paperEdge).frame(height: 1)
        }
    }

    private func byline(for a: Article) -> some View {
        HStack(spacing: 6) {
            if let author = a.firstAuthor {
                Text(author)
            }
            if let j = a.journal {
                Text("·").foregroundStyle(Theme.inkMute).opacity(0.55)
                Text(j).italic()
            }
            if let d = a.coverDate {
                Text("·").foregroundStyle(Theme.inkMute).opacity(0.55)
                Text(d)
            }
        }
        .font(.system(size: 12))
        .foregroundStyle(Theme.inkSoft)
        .lineLimit(1)
    }

    private func statsBar(for a: Article) -> some View {
        HStack(spacing: 14) {
            if let c = a.citedBy, c > 0 {
                HStack(spacing: 6) {
                    Image(systemName: "quote.bubble")
                        .font(.system(size: 11))
                        .foregroundStyle(Theme.inkMute)
                    Text("Cited by \(c)")
                        .foregroundStyle(Theme.inkSoft)
                }
            }
            if let doi = a.doi, !doi.isEmpty {
                HStack(spacing: 6) {
                    Image(systemName: "link")
                        .font(.system(size: 11))
                        .foregroundStyle(Theme.inkMute)
                    if let url = URL(string: "https://doi.org/\(doi)") {
                        Link(doi, destination: url)
                            .foregroundStyle(Theme.accentDeep)
                    } else {
                        Text(doi).foregroundStyle(Theme.inkSoft)
                    }
                }
            }
            Spacer()
        }
        .font(.system(size: 12))
    }

    @ViewBuilder
    private func section<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title.uppercased())
                .font(.system(size: 10.5, weight: .semibold))
                .tracking(1.2)
                .foregroundStyle(Theme.inkMute)
            content()
        }
        .padding(.bottom, 26)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private func sectionWithEdit<Content: View>(
        _ title: String,
        editLabel: String,
        onEdit: @escaping () -> Void,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Text(title.uppercased())
                    .font(.system(size: 10.5, weight: .semibold))
                    .tracking(1.2)
                    .foregroundStyle(Theme.inkMute)
                Spacer()
                Button(action: onEdit) {
                    Text(editLabel)
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(Theme.accentDeep)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
            content()
        }
        .padding(.bottom, 26)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    // MARK: - Tags

    @ViewBuilder
    private func tagsEditor(for article: Article) -> some View {
        WrapHStack(spacing: 6, lineSpacing: 6) {
            ForEach(article.tags ?? [], id: \.self) { t in
                RemovableTagChip(label: t) {
                    Task { await onRemoveTag(article: article, tag: t) }
                }
            }
            if isAddingTag {
                TagInputChip(
                    text: $tagDraft,
                    focused: $tagFieldFocused,
                    onCommit: { Task { await onCommitTag(article: article) } },
                    onCancel: cancelTagEdit
                )
            } else {
                AddTagChip { startAddingTag() }
            }
        }
    }

    private func startAddingTag() {
        tagDraft = ""
        isAddingTag = true
        DispatchQueue.main.async { tagFieldFocused = true }
    }

    private func cancelTagEdit() {
        isAddingTag = false
        tagDraft = ""
        tagFieldFocused = false
    }

    private func onCommitTag(article: Article) async {
        let trimmed = tagDraft.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { cancelTagEdit(); return }
        await state.addTag(eid: article.eid, tag: trimmed)
        cancelTagEdit()
        if let fresh = await state.refetchArticle(eid: article.eid) { loaded = fresh }
    }

    private func onRemoveTag(article: Article, tag: String) async {
        await state.removeTag(eid: article.eid, tag: tag)
        if let fresh = await state.refetchArticle(eid: article.eid) { loaded = fresh }
    }

    // MARK: - Notes

    @ViewBuilder
    private func notesView(for article: Article) -> some View {
        if isEditingNote {
            VStack(alignment: .leading, spacing: 8) {
                TextEditor(text: $noteDraft)
                    .font(.serif(14))
                    .foregroundStyle(Theme.ink)
                    .scrollContentBackground(.hidden)
                    .padding(10)
                    .frame(minHeight: 120)
                    .background(Theme.paper)
                    .overlay(
                        RoundedRectangle(cornerRadius: 6)
                            .stroke(Theme.accent, lineWidth: 1.5)
                    )
                    .focused($noteFieldFocused)
                HStack(spacing: 10) {
                    Text("⌘↩ Save · Esc Discard")
                        .font(.system(size: 11))
                        .foregroundStyle(Theme.inkMute)
                    Spacer()
                    Button("Cancel") { cancelNoteEdit() }
                        .buttonStyle(.plain)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(Theme.inkSoft)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 4)
                    Button("Save") { Task { await commitNote(article: article) } }
                        .buttonStyle(PrimaryButtonStyle())
                        .keyboardShortcut(.return, modifiers: .command)
                }
            }
        } else if let notes = article.notes, !notes.isEmpty {
            Text(notes)
                .font(.serif(14))
                .foregroundStyle(Theme.ink)
                .lineSpacing(3)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
        } else {
            Text("Write a note about this article…")
                .font(.serif(14).italic())
                .foregroundStyle(Theme.inkMute)
                .onTapGesture { startEditingNote(article) }
        }
    }

    private func startEditingNote(_ article: Article) {
        noteDraft = article.notes ?? ""
        isEditingNote = true
        DispatchQueue.main.async { noteFieldFocused = true }
    }

    private func cancelNoteEdit() {
        isEditingNote = false
        noteDraft = ""
        noteFieldFocused = false
    }

    private func commitNote(article: Article) async {
        await state.setNote(eid: article.eid, note: noteDraft)
        cancelNoteEdit()
        if let fresh = await state.refetchArticle(eid: article.eid) {
            loaded = fresh
        }
        // If refetch failed, the events-poll loop will refresh the row within
        // ~1.5s; no need to maintain an optimistic local copy here.
    }

    // MARK: - Empty state + loader

    private func emptyDetail(icon: String, head: String, sub: String) -> some View {
        VStack(spacing: 10) {
            Image(systemName: icon)
                .font(.system(size: 28))
                .foregroundStyle(Theme.inkMute.opacity(0.8))
            Text(head)
                .font(.serif(17, weight: .medium))
                .foregroundStyle(Theme.ink)
            Text(sub)
                .font(.system(size: 12))
                .foregroundStyle(Theme.inkMute)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 320)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(40)
    }

    private func load(eid: String?) async {
        loadError = nil
        guard let eid else {
            loaded = nil
            return
        }
        do {
            loaded = try await DaemonClient.shared.article(eid: eid)
        } catch {
            loaded = nil
            loadError = error.localizedDescription
        }
    }
}

// MARK: - Tag chip components

private struct RemovableTagChip: View {
    let label: String
    var onRemove: () -> Void
    @State private var hovering = false

    var body: some View {
        HStack(spacing: 4) {
            Text(label)
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(Theme.tagInk)
            if hovering {
                Button(action: onRemove) {
                    Image(systemName: "xmark")
                        .font(.system(size: 8, weight: .bold))
                        .foregroundStyle(Theme.inkMute)
                        .padding(2)
                        .background(Color.black.opacity(0.06), in: Circle())
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.horizontal, 9)
        .padding(.vertical, 3)
        .background(Theme.tagBg, in: Capsule())
        .onHover { hovering = $0 }
    }
}

private struct AddTagChip: View {
    var onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            HStack(spacing: 4) {
                Image(systemName: "plus")
                    .font(.system(size: 9, weight: .medium))
                Text("Add tag")
                    .font(.system(size: 11))
            }
            .foregroundStyle(Theme.inkMute)
            .padding(.horizontal, 9)
            .padding(.vertical, 3)
            .overlay(
                Capsule().stroke(Theme.inkFaint, style: StrokeStyle(lineWidth: 1, dash: [3, 2]))
            )
        }
        .buttonStyle(.plain)
    }
}

private struct TagInputChip: View {
    @Binding var text: String
    var focused: FocusState<Bool>.Binding
    var onCommit: () -> Void
    var onCancel: () -> Void

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: "plus")
                .font(.system(size: 9, weight: .medium))
                .foregroundStyle(Theme.accent)
            TextField("new-tag", text: $text)
                .textFieldStyle(.plain)
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(Theme.ink)
                .focused(focused)
                .onSubmit(onCommit)
                .frame(minWidth: 60, idealWidth: 80, maxWidth: 120)
        }
        .padding(.horizontal, 9)
        .padding(.vertical, 3)
        .background(Theme.paper, in: Capsule())
        .overlay(Capsule().stroke(Theme.accent, lineWidth: 1.5))
        .onExitCommand(perform: onCancel)
    }
}

