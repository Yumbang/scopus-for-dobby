import SwiftUI

struct CollectionsSidebar: View {
    @EnvironmentObject private var state: AppState
    @ObservedObject private var client = DaemonClient.shared
    /// Non-nil while the new-collection sheet is up; ``project`` is where
    /// the collection gets filed (nil = ungrouped).
    @State private var newCollection: NewCollectionContext? = nil
    @State private var renaming: RenameTarget? = nil
    @State private var renameDraft: String = ""
    @State private var mergingCollection: String? = nil
    @State private var projectSheet: ProjectSheetContext? = nil
    @State private var deletingProject: String? = nil
    /// Collections picked with ⌘/⇧-click for a bulk action or a drag. Only
    /// meaningful with two or more; the list still shows the single
    /// collection last plain-clicked (``state.selection``).
    @State private var picked: Set<String> = []
    /// Where a ⇧-click range starts: the last plain click (Finder/Mail).
    @State private var pickAnchor: String? = nil
    /// The drop target under an in-flight drag, for its highlight.
    @State private var dropTarget: DropTarget? = nil
    @State private var deletingCollections: [String]? = nil
    /// Expanded project names as a JSON array — ``@AppStorage`` holds only
    /// scalars. Not newline-joined: the CLI accepts a name with a newline in
    /// it, and such a project could then never be expanded.
    @AppStorage("sidebar.expandedProjects") private var expandedProjectsRaw: String = ""

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    librarySection
                    projectsSection
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
        .onChange(of: state.selection) { _, sel in reveal(sel) }
        .sheet(item: $newCollection) { ctx in
            NewCollectionSheet(project: ctx.project) { name in
                Task { await state.createCollection(name, inProject: ctx.project) }
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
        .sheet(item: $projectSheet) { ctx in
            AssignCollectionsSheet(
                mode: ctx.mode,
                collections: state.collections,
                projectNames: state.projects.map(\.name),
                initiallyChecked: ctx.initiallyChecked,
                lastError: state.lastError
            ) { project, members in
                await applyProjectSheet(mode: ctx.mode, project: project, members: members)
            }
        }
        .confirmationDialog(
            "Delete the project “\(deletingProject ?? "")”?",
            isPresented: Binding(
                get: { deletingProject != nil },
                set: { if !$0 { deletingProject = nil } }
            ),
            titleVisibility: .visible,
            presenting: deletingProject
        ) { name in
            Button("Delete Project", role: .destructive) {
                Task { await state.deleteProject(name) }
            }
            Button("Cancel", role: .cancel) {}
        } message: { name in
            let n = state.collections(in: name).count
            Text(n == 0
                 ? "The project is empty. No collections or articles are affected."
                 : "Its \(n) collection\(n == 1 ? "" : "s") are kept and move back to Collections. No articles are removed.")
        }
        .confirmationDialog(
            "Delete \(deletingCollections?.count ?? 0) collections?",
            isPresented: Binding(
                get: { deletingCollections != nil },
                set: { if !$0 { deletingCollections = nil } }
            ),
            titleVisibility: .visible,
            presenting: deletingCollections
        ) { names in
            Button("Delete \(names.count) Collections", role: .destructive) {
                picked = []
                Task { await state.deleteCollections(names) }
            }
            Button("Cancel", role: .cancel) {}
        } message: { names in
            Text(names.joined(separator: ", ") + "\n\nThe articles stay in the library.")
        }
    }

    private enum DropTarget: Equatable {
        case project(String)
        case ungrouped
    }

    private struct MergeContext: Identifiable {
        let src: String
        var id: String { src }
    }

    private struct NewCollectionContext: Identifiable {
        let project: String?
        var id: String { project ?? "" }
    }

    private struct ProjectSheetContext: Identifiable {
        let mode: AssignCollectionsSheet.Mode
        let initiallyChecked: Set<String>
        var id: String {
            switch mode {
            case .create: return "create"
            case .edit(let project): return "edit:" + project
            }
        }
    }

    /// Collections and projects share the inline rename field, but not a
    /// namespace — hence the tag.
    private enum RenameTarget: Equatable {
        case collection(String)
        case project(String)
    }

    private var librarySection: some View {
        VStack(alignment: .leading, spacing: 2) {
            sectionTitle("Library")
            // ``libraryTotal`` (the daemon's ``total_in_db``), not
            // ``articles.count`` — the latter is whatever is loaded right
            // now, so this row used to show the selected collection's size,
            // or the hit count while searching.
            sidebarRow(
                label: "All articles",
                systemImage: "tray.full",
                count: state.libraryTotal ?? state.articles.count,
                isActive: state.selection == .allArticles
            ) {
                picked = []
                state.selectSidebar(.allArticles)
            }
        }
    }

    /// Projects, each a disclosure over its member collections. The header
    /// always shows, so there is a visible place to create the first one.
    private var projectsSection: some View {
        VStack(alignment: .leading, spacing: 2) {
            sectionHeader("Projects", count: state.projects.count)
            if state.projects.isEmpty {
                Button { presentLater { projectSheet = ProjectSheetContext(mode: .create, initiallyChecked: []) } } label: {
                    Text("No projects — create one…")
                        .font(.system(size: 12))
                        .foregroundStyle(Theme.inkMute)
                        .lineLimit(1)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 4)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
            ForEach(state.projects) { p in
                projectRow(p)
                if isExpanded(p.name) {
                    let members = state.collections(in: p.name)
                    if members.isEmpty {
                        emptyProjectRow(p.name)
                    } else {
                        ForEach(members) { c in collectionRow(c, indent: Self.memberIndent) }
                    }
                }
            }
        }
    }

    /// Collections filed under no project. Grouped ones live under their
    /// project above, so the count here is the ungrouped ones only.
    private var collectionsSection: some View {
        VStack(alignment: .leading, spacing: 2) {
            sectionHeader(state.projects.isEmpty ? "Collections" : "Ungrouped collections",
                          count: state.ungroupedCollections.count)
            ForEach(state.ungroupedCollections) { c in
                collectionRow(c)
            }
        }
        // Dropping grouped collections anywhere on this section ungroups them.
        .background(
            RoundedRectangle(cornerRadius: 6)
                .stroke(Theme.accent, lineWidth: dropTarget == .ungrouped ? 1.5 : 0)
        )
        .dropDestination(for: String.self) { items, _ in
            handleDrop(items, on: .ungrouped)
        } isTargeted: { setDropTarget(.ungrouped, $0) }
    }

    private func sectionHeader(_ title: String, count: Int) -> some View {
        HStack(spacing: 6) {
            Text(title)
                .font(.system(size: 10.5, weight: .semibold))
                .tracking(1.0)
                .textCase(.uppercase)
                .foregroundStyle(Theme.inkMute)
                .lineLimit(1)
            Text("\(count)")
                .font(.system(size: 10))
                .monospacedDigit()
                .foregroundStyle(Theme.inkMute.opacity(0.7))
            Spacer()
            addMenu
        }
        .padding(.horizontal, 10)
        .padding(.top, 4)
        .padding(.bottom, 6)
        .contentShape(Rectangle())
        .contextMenu { newItems(checking: []) }
    }

    /// "New collection…" / "New project…", shared by the + menu and every
    /// context menu that offers them. ``checking`` pre-checks collections in
    /// the new-project sheet.
    @ViewBuilder
    private func newItems(checking: Set<String>, inProject project: String? = nil) -> some View {
        Button(project == nil ? "New collection…" : "New collection in project…") {
            presentLater { newCollection = NewCollectionContext(project: project) }
        }
        Button("New project…") {
            presentLater {
                projectSheet = ProjectSheetContext(mode: .create, initiallyChecked: checking)
            }
        }
    }

    /// Present a sheet on the next runloop turn. A context-menu action runs
    /// while AppKit is still tearing the menu down, and a sheet requested in
    /// that window can be silently dropped — the item looks dead. The + menu
    /// happened not to hit it; right-click did.
    private func presentLater(_ change: @escaping () -> Void) {
        DispatchQueue.main.async(execute: change)
    }

    /// Lines a member's icon up under its project's name: icon width + spacing.
    private static let memberIndent: CGFloat = 22

    private var addMenu: some View {
        Menu {
            newItems(checking: [])
        } label: {
            Image(systemName: "plus")
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(Theme.inkMute)
                .padding(.horizontal, 4)
                .padding(.vertical, 2)
                .contentShape(Rectangle())
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(.hidden)
        .fixedSize()
        .help("New collection or project")
    }

    // MARK: - Rows

    @ViewBuilder
    private func projectRow(_ p: ProjectInfo) -> some View {
        if renaming == .project(p.name) {
            inlineRenameRow(systemImage: "rectangle.stack") {
                commitRename(.project(p.name))
            }
        } else {
            sidebarRow(
                label: p.name,
                systemImage: "rectangle.stack",
                count: p.articleCount,
                isActive: state.selection == .project(p.name),
                isEmpty: p.articleCount == 0,
                isDropTarget: dropTarget == .project(p.name),
                disclosure: Disclosure(isExpanded: isExpanded(p.name)) {
                    withAnimation(.easeOut(duration: 0.15)) {
                        setExpanded(p.name, !isExpanded(p.name))
                    }
                }
            ) {
                picked = []
                state.selectSidebar(.project(p.name))
            }
            .dropDestination(for: String.self) { items, _ in
                handleDrop(items, on: .project(p.name))
            } isTargeted: { setDropTarget(.project(p.name), $0) }
            .help("\(p.collectionCount) collection\(p.collectionCount == 1 ? "" : "s") · \(p.articleCount) distinct articles")
            .contextMenu {
                Button("Choose collections…") { presentLater { chooseCollections(for: p.name) } }
                Button("Rename…") { startRename(.project(p.name), draft: p.name) }
                Divider()
                newItems(checking: [], inProject: p.name)
                Divider()
                Button("Delete \"\(p.name)\"…", role: .destructive) {
                    presentLater { deletingProject = p.name }
                }
            }
        }
    }

    /// An expanded project with nothing in it. Says so, and offers the
    /// one thing to do about it.
    private func emptyProjectRow(_ project: String) -> some View {
        Button { chooseCollections(for: project) } label: {
            Text("No collections — choose…")
                .font(.system(size: 12))
                .foregroundStyle(Theme.inkMute)
                .lineLimit(1)
                .padding(.leading, 10 + Self.memberIndent)
                .padding(.trailing, 10)
                .padding(.vertical, 4)
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    @ViewBuilder
    private func collectionRow(_ c: CollectionInfo, indent: CGFloat = 0) -> some View {
        if renaming == .collection(c.name) {
            inlineRenameRow(systemImage: "folder", indent: indent) {
                commitRename(.collection(c.name))
            }
        } else {
            sidebarRow(
                label: c.name,
                systemImage: "folder",
                count: c.articleCount,
                isActive: state.selection == .collection(c.name),
                isEmpty: c.articleCount == 0,
                isPicked: bulk.contains(c.name),
                indent: indent
            ) {
                picked = [c.name]
                pickAnchor = c.name
                state.selectSidebar(.collection(c.name))
            }
            // Modifier clicks. ``onTapGesture``/Button actions cannot see the
            // modifiers reliably (see ArticleListView), so each modifier set
            // gets its own gesture; high priority so it beats the row's
            // Button, and a plain click — which neither matches — falls
            // through to the Button.
            .highPriorityGesture(TapGesture().modifiers(.shift).onEnded { rangePick(to: c.name) })
            .highPriorityGesture(TapGesture().modifiers(.command).onEnded { togglePick(c.name) })
            .draggable(dragPayload(from: c.name)) { dragPreview(from: c.name) }
            // A drop on a row goes where that row lives: its project, or the
            // ungrouped section. So an expanded project takes drops anywhere
            // over its members, not just on its own row.
            .dropDestination(for: String.self) { items, _ in
                handleDrop(items, on: c.project.map(DropTarget.project) ?? .ungrouped)
            } isTargeted: { setDropTarget(c.project.map(DropTarget.project) ?? .ungrouped, $0) }
            .contextMenu {
                if bulk.contains(c.name) {
                    bulkMenu(bulkNames)
                } else {
                    singleMenu(c)
                }
            }
        }
    }

    @ViewBuilder
    private func singleMenu(_ c: CollectionInfo) -> some View {
                Button("Rename…") { startRename(.collection(c.name), draft: c.name) }
                Button("Merge into…") { presentLater { mergingCollection = c.name } }
                    .disabled(state.collections.count < 2)
                moveToProjectMenu(c)
                if let p = c.project {
                    Button("Remove from \"\(p)\"") {
                        Task { await state.unassignCollections([c.name], from: p) }
                    }
                }
                Divider()
                Button("Delete \"\(c.name)\"", role: .destructive) {
                    Task { await state.deleteCollection(c.name) }
                }
    }

    /// The right-click menu on any row of a multi-collection pick: every
    /// action applies to the whole pick.
    @ViewBuilder
    private func bulkMenu(_ names: [String]) -> some View {
        let n = names.count
        let grouped = state.collections.filter { names.contains($0.name) && $0.project != nil }
        Menu("Move \(n) Collections to Project") {
            ForEach(state.projects) { p in
                Button(p.name) {
                    Task { await state.assignCollections(names, to: p.name) }
                }
            }
            if !state.projects.isEmpty { Divider() }
            Button("New project…") {
                presentLater {
                    projectSheet = ProjectSheetContext(mode: .create, initiallyChecked: Set(names))
                }
            }
        }
        if !grouped.isEmpty {
            Button("Remove \(grouped.count) from Their Projects") {
                Task { await state.ungroupCollections(names) }
            }
        }
        Divider()
        Button("Deselect") { picked = [] }
        Button("Delete \(n) Collections…", role: .destructive) {
            presentLater { deletingCollections = names }
        }
    }

    private func moveToProjectMenu(_ c: CollectionInfo) -> some View {
        Menu("Move to project") {
            ForEach(state.projects) { p in
                Button {
                    Task { await state.assignCollections([c.name], to: p.name) }
                } label: {
                    if p.name == c.project {
                        Label(p.name, systemImage: "checkmark")
                    } else {
                        Text(p.name)
                    }
                }
                .disabled(p.name == c.project)
            }
            if !state.projects.isEmpty { Divider() }
            // The create flow with this collection pre-checked: typing a
            // name and pressing Return is the whole "new project" prompt,
            // and the list is there if more belong with it.
            Button("New project…") {
                presentLater {
                    projectSheet = ProjectSheetContext(mode: .create, initiallyChecked: [c.name])
                }
            }
        }
    }

    // MARK: - Multi-pick and drag

    /// The pick, when it is a multi-pick; empty otherwise. Names that have
    /// since been deleted or renamed away drop out.
    private var bulk: Set<String> {
        let live = picked.intersection(state.collections.map(\.name))
        return live.count > 1 ? live : []
    }

    /// ``bulk`` in sidebar order.
    private var bulkNames: [String] {
        visibleCollectionOrder.filter { bulk.contains($0) }
    }

    /// Collection names top to bottom as drawn: expanded projects' members,
    /// then the ungrouped. A ⇧-click range runs over this order.
    private var visibleCollectionOrder: [String] {
        state.projects.flatMap { p in
            isExpanded(p.name) ? state.collections(in: p.name).map(\.name) : []
        } + state.ungroupedCollections.map(\.name)
    }

    private func togglePick(_ name: String) {
        if picked.isEmpty, case .collection(let current) = state.selection {
            picked.insert(current)
        }
        if picked.contains(name) { picked.remove(name) } else { picked.insert(name) }
        // The anchor stays on the last plain click, as in Finder.
    }

    private func rangePick(to name: String) {
        let order = visibleCollectionOrder
        let anchor = pickAnchor ?? state.selection.collectionName ?? name
        guard let a = order.firstIndex(of: anchor), let b = order.firstIndex(of: name) else {
            picked = [name]
            return
        }
        picked = Set(order[min(a, b)...max(a, b)])
    }

    /// Drag payloads are plain strings — no custom UTType to declare — so
    /// they are tagged, and a drop ignores any string without the tag (text
    /// dragged in from elsewhere).
    private static let dragTag = "scopus-for-dobby/collections\n"

    /// Dragging a row of a multi-pick drags the whole pick; any other row
    /// drags just itself.
    private func dragNames(from name: String) -> [String] {
        bulk.contains(name) ? bulkNames : [name]
    }

    private func dragPayload(from name: String) -> String {
        let data = (try? JSONEncoder().encode(dragNames(from: name))) ?? Data("[]".utf8)
        return Self.dragTag + String(decoding: data, as: UTF8.self)
    }

    private func dragPreview(from name: String) -> some View {
        let names = dragNames(from: name)
        return Label(names.count == 1 ? name : "\(names.count) collections", systemImage: "folder")
            .font(.system(size: 12))
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(Theme.paper, in: RoundedRectangle(cornerRadius: 6))
    }

    private func setDropTarget(_ target: DropTarget, _ isTargeted: Bool) {
        if isTargeted {
            dropTarget = target
        } else if dropTarget == target {
            dropTarget = nil
        }
    }

    private func handleDrop(_ items: [String], on target: DropTarget) -> Bool {
        dropTarget = nil
        let names = items.flatMap { item -> [String] in
            guard item.hasPrefix(Self.dragTag) else { return [] }
            let json = Data(item.dropFirst(Self.dragTag.count).utf8)
            return (try? JSONDecoder().decode([String].self, from: json)) ?? []
        }
        let known = state.collections.filter { names.contains($0.name) }
        switch target {
        case .project(let project):
            let moving = known.filter { $0.project != project }.map(\.name)
            guard !moving.isEmpty else { return false }
            Task { await state.assignCollections(moving, to: project) }
        case .ungrouped:
            let grouped = known.filter { $0.project != nil }.map(\.name)
            guard !grouped.isEmpty else { return false }
            Task { await state.ungroupCollections(grouped) }
        }
        picked = []
        return true
    }

    // MARK: - Actions

    private func chooseCollections(for project: String) {
        projectSheet = ProjectSheetContext(
            mode: .edit(project: project),
            initiallyChecked: Set(state.collections(in: project).map(\.name))
        )
    }

    private func applyProjectSheet(
        mode: AssignCollectionsSheet.Mode, project: String, members: Set<String>
    ) async -> Bool {
        if case .edit = mode {
            return await state.setProjectMembers(project, to: members)
        }
        // A new project with members is created by the assign itself; an
        // empty one needs creating explicitly.
        if members.isEmpty {
            await state.createProject(project)
            guard state.projects.contains(where: { $0.name == project }) else { return false }
        } else {
            guard await state.setProjectMembers(project, to: members) else { return false }
        }
        setExpanded(project, true)
        state.selectSidebar(.project(project))
        return true
    }

    private func startRename(_ target: RenameTarget, draft: String) {
        renameDraft = draft
        renaming = target
    }

    private func commitRename(_ target: RenameTarget) {
        // The field commits on blur, and blur also fires when it is torn
        // down — after Escape, or when Rename… on another row has already
        // repointed ``renaming`` and ``renameDraft``. Without this guard the
        // stale field committed the *other* row's draft: project "A" renamed
        // to collection "B"'s name, or an Escaped edit applied anyway.
        guard renaming == target else { return }
        let trimmed = renameDraft.trimmingCharacters(in: .whitespaces)
        renaming = nil
        switch target {
        case .collection(let original):
            guard !trimmed.isEmpty, trimmed != original else { return }
            Task { await state.renameCollection(original, to: trimmed) }
        case .project(let original):
            guard !trimmed.isEmpty, trimmed != original else { return }
            // Carry the disclosure across; a failed rename leaves a stale
            // name in the set, which only ever matters if it is reused.
            if isExpanded(original) { setExpanded(trimmed, true) }
            Task { await state.renameProject(original, to: trimmed) }
        }
    }

    // MARK: - Expansion

    private var expandedProjects: Set<String> {
        let names = try? JSONDecoder().decode([String].self, from: Data(expandedProjectsRaw.utf8))
        return Set(names ?? [])
    }

    private func isExpanded(_ project: String) -> Bool {
        expandedProjects.contains(project)
    }

    private func setExpanded(_ project: String, _ on: Bool) {
        var s = expandedProjects
        if on { s.insert(project) } else { s.remove(project) }
        let data = (try? JSONEncoder().encode(s.sorted())) ?? Data("[]".utf8)
        expandedProjectsRaw = String(decoding: data, as: UTF8.self)
    }

    /// Opens the project holding a newly selected collection, so a
    /// selection made elsewhere (a chip in the detail pane) is visible here.
    /// Collapsing it again afterwards is left alone.
    private func reveal(_ sel: SidebarSelection) {
        guard let name = sel.collectionName,
              let project = state.collections.first(where: { $0.name == name })?.project,
              !isExpanded(project)
        else { return }
        withAnimation(.easeOut(duration: 0.15)) { setExpanded(project, true) }
    }

    // MARK: - Row chrome

    @ViewBuilder
    private func inlineRenameRow(
        systemImage: String,
        indent: CGFloat = 0,
        onCommit: @escaping () -> Void
    ) -> some View {
        HStack(spacing: 8) {
            Image(systemName: systemImage)
                .font(.system(size: 12))
                .foregroundStyle(Theme.accentDeep)
                .frame(width: 14)
            InlineRenameField(
                text: $renameDraft,
                onCommit: onCommit,
                onCancel: { renaming = nil }
            )
            Spacer(minLength: 4)
        }
        .padding(.leading, 10 + indent)
        .padding(.trailing, 10)
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

    /// A disclosure chevron at the row's trailing edge. Trailing rather than
    /// leading so project and ungrouped-collection icons stay in one column.
    private struct Disclosure {
        let isExpanded: Bool
        let toggle: () -> Void
    }

    @ViewBuilder
    private func sidebarRow(
        label: String,
        systemImage: String,
        count: Int,
        isActive: Bool,
        isEmpty: Bool = false,
        isPicked: Bool = false,
        isDropTarget: Bool = false,
        indent: CGFloat = 0,
        disclosure: Disclosure? = nil,
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
                if disclosure != nil {
                    // Room for the chevron overlaid below.
                    Color.clear.frame(width: 10, height: 10)
                }
            }
            .padding(.leading, 10 + indent)
            .padding(.trailing, 10)
            .padding(.vertical, 5)
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
            .background(
                isActive ? Theme.accentSoft : (isPicked ? Theme.accentSoft.opacity(0.55) : Color.clear),
                in: RoundedRectangle(cornerRadius: 6)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 6)
                    .stroke(Theme.accent, lineWidth: isDropTarget ? 1.5 : 0)
            )
        }
        .buttonStyle(.plain)
        // An overlay, not a button nested in the row's label: the top view
        // takes the click, so the chevron toggles without also selecting.
        .overlay(alignment: .trailing) {
            if let disclosure {
                Button(action: disclosure.toggle) {
                    Image(systemName: "chevron.right")
                        .font(.system(size: 9, weight: .semibold))
                        .foregroundStyle(countColor)
                        .rotationEffect(.degrees(disclosure.isExpanded ? 90 : 0))
                        .frame(width: 20, height: 22)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .padding(.trailing, 5)
                .help(disclosure.isExpanded ? "Hide collections" : "Show collections")
            }
        }
    }

    private var versionLine: String {
        var parts = ["app \(BuildInfo.version)"]
        if let built = BuildInfo.built { parts.append("built \(built)") }
        parts.append("CLI \(state.daemonVersion ?? "—")")
        return parts.joined(separator: " · ")
    }

    private var versionTooltip: String {
        let cli = state.daemonVersion.map { "CLI \($0)" } ?? "CLI version unknown — daemon has not answered"
        let built = BuildInfo.built.map { "built \($0)" } ?? "build date unavailable"
        return "App \(BuildInfo.version), \(built)\n\(cli)\n"
            + "The app and the CLI are installed separately and version independently."
    }

    private var footer: some View {
        let isUp: Bool = {
            if case .running = state.daemonStatus { return true } else { return false }
        }()
        let dotColor = isUp ? Theme.good : Theme.bad
        return VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 8) {
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
            // The app and the CLI ship separately — a rebuilt .app and a
            // `uv tool install` — so "which half is stale" is otherwise
            // unanswerable from inside the app. Their version numbers are
            // independent, so this reports both rather than comparing them;
            // the build date is what actually tells you the app is old.
            Text(versionLine)
                .font(.system(size: 10))
                .monospacedDigit()
                .foregroundStyle(Theme.inkMute)
                .opacity(0.6)
                .lineLimit(1)
                .help(versionTooltip)
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .overlay(alignment: .top) {
            Rectangle().fill(Theme.paperEdge).frame(height: 1)
        }
    }
}
