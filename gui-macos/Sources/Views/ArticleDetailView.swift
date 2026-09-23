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

    /// Author lists run to the hundreds on consortium papers; show a handful
    /// and let the user ask for the rest.
    @State private var showAllAuthors: Bool = false
    private static let authorPreviewCount = 12

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
            showAllAuthors = false
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
            detailHeader(for: article)
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
                    authorsSection(for: article)
                    chipSection("Topics", article.openalexTopics, tone: .accent)
                    if let kw = article.keywords, !kw.isEmpty {
                        section("Keywords") {
                            Text(kw)
                                .font(.system(size: 12))
                                .foregroundStyle(Theme.inkSoft)
                                .lineSpacing(2)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    chipSection("Index keywords", article.indexKeywords)
                    chipSection("Subject areas", article.subjectAreas)
                    chipSection("Affiliations", article.affiliations)
                    chipSection("Projects", article.projects)
                    chipSection("Collections", article.collections)
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
                    recordSection(for: article)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 32)
                .padding(.top, 28)
                .padding(.bottom, 40)
            }
        }
    }

    /// Breadcrumb. Prefers where the article actually lives over where the
    /// user happens to be standing: ``GET /articles/{eid}`` carries collection
    /// membership, so while browsing All articles the header can name the
    /// collections this paper belongs to instead of repeating "All articles".
    /// With a collection selected, that selection stays — it is true, and it
    /// keeps the header stable as the user arrows down the list.
    ///
    /// A project holds nothing directly, so with one selected the header names
    /// which of *its* collections hold this paper — the part of "where it
    /// lives" that the selection does not already say. A collection filed
    /// under a project is shown as "project › collection" wherever it appears.
    private func detailHeader(for article: Article) -> some View {
        let memberships = article.collections ?? []
        let crumbs: [String]
        switch state.selection {
        case .allArticles:
            crumbs = memberships.map(crumb)
        case .collection(let name):
            crumbs = [crumb(name)]
        case .project(let name):
            let members = Set(state.collections(in: name).map(\.name))
            let holding = memberships.filter(members.contains)
            crumbs = holding.isEmpty ? [name] : holding.map { "\(name) › \($0)" }
        }
        let icon: String
        switch state.selection {
        case .allArticles: icon = crumbs.isEmpty ? "tray.full" : "folder.fill"
        case .collection: icon = "folder.fill"
        case .project: icon = "rectangle.stack.fill"
        }
        let title = crumbs.isEmpty ? state.selection.displayTitle : crumbs.joined(separator: " · ")
        return HStack(spacing: 8) {
            Image(systemName: icon)
                .font(.system(size: 11))
                .foregroundStyle(Theme.inkMute)
            Text(title)
                .font(.system(size: 12))
                .foregroundStyle(Theme.inkSoft)
                .lineLimit(1)
                .truncationMode(.tail)
            Spacer()
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .overlay(alignment: .bottom) {
            Rectangle().fill(Theme.paperEdge).frame(height: 1)
        }
    }

    /// A collection's name, prefixed with its project when it is filed under one.
    private func crumb(_ collection: String) -> String {
        guard let project = state.collections.first(where: { $0.name == collection })?.project
        else { return collection }
        return "\(project) › \(collection)"
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
            if let locator = volumeIssue(for: a) {
                Text("·").foregroundStyle(Theme.inkMute).opacity(0.55)
                Text(locator)
            }
            if let p = a.pages, !p.isEmpty {
                Text("·").foregroundStyle(Theme.inkMute).opacity(0.55)
                Text("pp. \(p)")
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

    /// Journal locator in the form citations use: ``12(3)``, or just ``12``
    /// when the issue is unknown. Nil when there is no volume to anchor it.
    private func volumeIssue(for a: Article) -> String? {
        let vol = (a.volume ?? "").trimmingCharacters(in: .whitespaces)
        let iss = (a.issue ?? "").trimmingCharacters(in: .whitespaces)
        if vol.isEmpty { return iss.isEmpty ? nil : "no. \(iss)" }
        return iss.isEmpty ? vol : "\(vol)(\(iss))"
    }

    /// ``WrapHStack`` rather than the original ``HStack`` + ``Spacer()``: with
    /// OA, free-copy, full-text, source-type and ISSN all added, a single row
    /// runs past the 420pt minimum pane width and clips. Order is unchanged.
    private func statsBar(for a: Article) -> some View {
        WrapHStack(spacing: 14, lineSpacing: 8) {
            if let c = a.citedBy, c > 0 {
                statItem("quote.bubble", "Cited by \(c)")
            }
            if let c = a.openalexCitedBy, c > 0 {
                statItem("chart.bar.doc.horizontal", "OpenAlex \(c)")
                    .help("Citations OpenAlex counted, which rarely matches Scopus")
            }
            openAccessBadge(for: a)
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
                .font(.system(size: 12))
            }
            if let free = a.freeCopyURL {
                HStack(spacing: 6) {
                    Image(systemName: "arrow.down.doc")
                        .font(.system(size: 11))
                        .foregroundStyle(Theme.inkMute)
                    Link("Free copy", destination: free)
                        .foregroundStyle(Theme.accentDeep)
                }
                .font(.system(size: 12))
                .help(free.absoluteString)
            }
            if a.hasCachedFulltext {
                statItem("doc.text.fill", "Full text cached")
                    .help(prettyTimestamp(a.fulltextFetchedAt).map { "Fetched \($0)" }
                          ?? "Fetched by `scopus-for-dobby fulltext`")
            }
            if let type = a.sourceType, !type.isEmpty {
                statItem("books.vertical", type)
            }
            if let issn = a.issn, !issn.isEmpty {
                statItem("number", issn).help("ISSN")
            }
        }
        .font(.system(size: 12))
    }

    private func statItem(_ icon: String, _ label: String) -> some View {
        HStack(spacing: 6) {
            Image(systemName: icon)
                .font(.system(size: 11))
                .foregroundStyle(Theme.inkMute)
            Text(label)
                .foregroundStyle(Theme.inkSoft)
        }
        .font(.system(size: 12))
    }

    /// OA badge. The OpenAlex colour when the row has been enriched — gold,
    /// green and hybrid all mean "there is a free copy", bronze means "free
    /// today, on the publisher's goodwill" — otherwise Scopus's own flag,
    /// which says only yes/no. Nothing is shown for a row that was never
    /// enriched and that Scopus did not flag: "unknown" is not a badge.
    @ViewBuilder
    private func openAccessBadge(for a: Article) -> some View {
        if let status = a.openAccessStatus {
            switch status {
            case "closed":
                Chip(label: "Closed", systemImage: "lock.fill", tone: .neutral)
                    .help("OpenAlex found no free copy")
            case "bronze":
                Chip(label: "Bronze OA", systemImage: "lock.open.fill", tone: .warn)
                    .help("Free on the publisher's site, with no open licence")
            default:
                Chip(label: "\(status.capitalized) OA",
                     systemImage: "lock.open.fill", tone: .good)
            }
        } else if a.openAccess == true {
            Chip(label: "Open access", systemImage: "lock.open.fill", tone: .good)
                .help("Flagged open access by Scopus; not enriched from OpenAlex")
        }
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

    // MARK: - Read-only sections

    /// A labelled row of chips, rendered only when there is something in it.
    /// Every list-shaped column in the model comes through here so they all
    /// look alike and none of them can quietly drift.
    @ViewBuilder
    private func chipSection(_ title: String, _ items: [String]?, tone: ChipTone = .neutral) -> some View {
        let values = (items ?? []).filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
        if !values.isEmpty {
            section(title) {
                chipRow(values, tone: tone)
            }
        }
    }

    private func chipRow(_ values: [String], tone: ChipTone) -> some View {
        // Index-keyed: these columns are not deduplicated upstream, and two
        // equal strings would collide as ForEach identities.
        WrapHStack(spacing: 6, lineSpacing: 6) {
            ForEach(Array(values.enumerated()), id: \.offset) { _, value in
                Chip(label: chipLabel(value), tone: tone)
                    .help(value)
            }
        }
    }

    /// ``WrapHStack`` places subviews at their natural width, so an uncapped
    /// institution name runs past the pane edge instead of wrapping. Cap what
    /// is drawn; the full string stays reachable as the chip's tooltip.
    private func chipLabel(_ s: String, max: Int = 48) -> String {
        guard s.count > max else { return s }
        return s.prefix(max - 1).trimmingCharacters(in: .whitespaces) + "…"
    }

    /// ``all_authors`` is decoded on every row and, until now, only
    /// ``first_author`` was ever drawn. Long author lists are collapsed
    /// rather than truncated — nothing is unreachable.
    @ViewBuilder
    private func authorsSection(for article: Article) -> some View {
        let names = (article.allAuthors ?? []).compactMap { $0.name }
            .filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
        if !names.isEmpty {
            let shown = showAllAuthors ? names : Array(names.prefix(Self.authorPreviewCount))
            section("Authors") {
                VStack(alignment: .leading, spacing: 8) {
                    chipRow(shown, tone: .neutral)
                    if names.count > Self.authorPreviewCount {
                        Button {
                            showAllAuthors.toggle()
                        } label: {
                            Text(showAllAuthors
                                 ? "Show fewer"
                                 : "Show all \(names.count) authors")
                                .font(.system(size: 11, weight: .medium))
                                .foregroundStyle(Theme.accentDeep)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
    }

    /// Provenance: when this row entered the library, when it last changed,
    /// and the identifiers the CLI and OpenAlex know it by. ``addedAt`` and
    /// ``updatedAt`` drive the sort menu but were never shown anywhere.
    @ViewBuilder
    private func recordSection(for article: Article) -> some View {
        let candidates: [(String, String?)] = [
            ("Added", prettyTimestamp(article.addedAt)),
            ("Updated", prettyTimestamp(article.updatedAt)),
            ("Enriched", prettyTimestamp(article.openalexEnrichedAt)),
            ("EID", article.eid),
        ]
        let rows: [(String, String)] = candidates.compactMap { pair in
            guard let value = pair.1, !value.isEmpty else { return nil }
            return (pair.0, value)
        }
        if !rows.isEmpty || article.openalexId?.isEmpty == false {
            section("Record") {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(rows, id: \.0) { pair in
                        recordRow(pair.0, Text(pair.1).foregroundStyle(Theme.inkSoft))
                    }
                    if let oid = article.openalexId, !oid.isEmpty {
                        recordRow("OpenAlex", openalexLink(oid))
                    }
                }
                .font(.system(size: 11.5))
                .textSelection(.enabled)
            }
        }
    }

    private func recordRow<V: View>(_ label: String, _ value: V) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(label)
                .foregroundStyle(Theme.inkMute)
                .frame(width: 66, alignment: .leading)
            value
            Spacer(minLength: 0)
        }
    }

    @ViewBuilder
    private func openalexLink(_ id: String) -> some View {
        // Stored either bare ("W2741809807") or as the full API URL.
        let slug = id.hasPrefix("http") ? String(id.split(separator: "/").last ?? "") : id
        if let url = URL(string: "https://openalex.org/\(slug)") {
            Link(slug, destination: url).foregroundStyle(Theme.accentDeep)
        } else {
            Text(id).foregroundStyle(Theme.inkSoft)
        }
    }

    /// Timestamps are written as ``"%Y-%m-%d %H:%M:%S"``
    /// (``core/article_db.py::_now``); older rows and fixtures use the ISO
    /// ``T`` separator. Drop the seconds, parse nothing, guess no locale.
    private func prettyTimestamp(_ raw: String?) -> String? {
        guard let raw = raw?.trimmingCharacters(in: .whitespaces), !raw.isEmpty else { return nil }
        let parts = raw.split(whereSeparator: { $0 == "T" || $0 == " " })
        guard let day = parts.first else { return raw }
        guard parts.count > 1 else { return String(day) }
        return "\(day) \(parts[1].prefix(5))"
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

/// A ``Chip`` that reveals a remove button on hover. The pill itself comes
/// from ``ChipShell`` so it cannot drift from the read-only chips beside it.
private struct RemovableTagChip: View {
    let label: String
    var onRemove: () -> Void
    @State private var hovering = false

    var body: some View {
        ChipShell(tone: .neutral, size: .regular) {
            HStack(spacing: 4) {
                Text(label)
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(ChipTone.neutral.ink)
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
        }
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
            // Outline, not a fill — this is an affordance, not a chip — but
            // it sits in the same row, so it borrows ``ChipShell``'s geometry.
            .padding(.horizontal, ChipSize.regular.hPadding)
            .padding(.vertical, ChipSize.regular.vPadding)
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
        .padding(.horizontal, ChipSize.regular.hPadding)
        .padding(.vertical, ChipSize.regular.vPadding)
        .background(Theme.paper, in: Capsule())
        .overlay(Capsule().stroke(Theme.accent, lineWidth: 1.5))
        .onExitCommand(perform: onCancel)
    }
}

