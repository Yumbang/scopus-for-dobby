import SwiftUI

/// The GUI's bulk sorting tool: every collection as a checkbox, checked means
/// "filed under this project". Two modes share one list — ``edit`` for an
/// existing project, ``create`` which adds a name field so a project can be
/// made and filled in one go.
///
/// A collection belongs to at most one project, so checking one that is filed
/// elsewhere *moves* it. The row says where it lives now and the summary says
/// how many moves Apply will make, so that is never a surprise.
struct AssignCollectionsSheet: View {
    enum Mode: Equatable {
        case create
        case edit(project: String)
    }

    let mode: Mode
    /// Every collection, in sidebar (name) order.
    let collections: [CollectionInfo]
    /// Existing project names — create mode refuses one of these rather than
    /// silently filing into the existing project.
    let projectNames: [String]
    /// Checked on open. Edit mode passes the current members; create mode
    /// passes whatever the user right-clicked, if anything.
    let initiallyChecked: Set<String>
    /// ``AppState.lastError``, live. The window's error toast sits behind
    /// the sheet, so a failed Apply repeats the message here.
    var lastError: String? = nil
    /// Returns true on success; the sheet stays open (with its checks) on
    /// failure so nothing the user sorted is lost.
    var onApply: (_ project: String, _ members: Set<String>) async -> Bool

    @Environment(\.dismiss) private var dismiss
    @State private var name: String = ""
    @State private var filter: String = ""
    @State private var checked: Set<String> = []
    @State private var isApplying = false
    @State private var applyFailed = false
    @FocusState private var focus: Field?

    private enum Field { case name, filter }

    var body: some View {
        VStack(spacing: 0) {
            head
            body_
            foot
        }
        .frame(width: 480)
        .background(Theme.paper)
        .onAppear {
            checked = initiallyChecked
            DispatchQueue.main.async { focus = (mode == .create) ? .name : .filter }
        }
    }

    // MARK: - Derived

    private var targetName: String {
        switch mode {
        case .create: return name.trimmingCharacters(in: .whitespaces)
        case .edit(let project): return project
        }
    }

    private var currentMembers: Set<String> {
        guard case .edit(let project) = mode else { return [] }
        return Set(collections.filter { $0.project == project }.map(\.name))
    }

    private var shown: [CollectionInfo] {
        collections.filter { matches($0.name) }
    }

    /// Case-insensitive substring match; a ``*`` or ``?`` switches to a
    /// whole-name glob, so ``r1-*`` picks a naming scheme out of a long list.
    private func matches(_ collection: String) -> Bool {
        let q = filter.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty else { return true }
        if q.contains("*") || q.contains("?") {
            return Self.globMatches(q, collection)
        }
        return collection.localizedCaseInsensitiveContains(q)
    }

    /// Whole-string, case-insensitive glob: ``*`` is any run, ``?`` any one
    /// character, everything else literal. Not ``NSPredicate LIKE``: that
    /// treats ``\`` as an escape and raises an uncatchable Objective-C
    /// exception on a trailing one, so typing ``r1-*\`` crashed the app.
    nonisolated static func globMatches(_ pattern: String, _ name: String) -> Bool {
        let p = Array(pattern.lowercased()), s = Array(name.lowercased())
        var pi = 0, si = 0
        var star: Int? = nil, starSi = 0
        while si < s.count {
            if pi < p.count, p[pi] == "?" || (p[pi] != "*" && p[pi] == s[si]) {
                pi += 1; si += 1
            } else if pi < p.count, p[pi] == "*" {
                star = pi; starSi = si; pi += 1
            } else if let st = star {
                pi = st + 1; starSi += 1; si = starSi
            } else {
                return false
            }
        }
        while pi < p.count, p[pi] == "*" { pi += 1 }
        return pi == p.count
    }

    /// Filed elsewhere right now, i.e. a check here is a move, not an add.
    private func otherProject(of c: CollectionInfo) -> String? {
        guard let p = c.project, p != targetName || mode == .create else { return nil }
        return p
    }

    private var changes: (added: Int, moved: Int, removed: Int) {
        let incoming = collections.filter { checked.contains($0.name) && !currentMembers.contains($0.name) }
        let moved = incoming.filter { otherProject(of: $0) != nil }.count
        return (incoming.count - moved, moved, currentMembers.subtracting(checked).count)
    }

    private var nameClash: Bool {
        mode == .create && projectNames.contains(targetName)
    }

    /// The daemon refuses these (a project name is one URL path segment), so
    /// say so here rather than in an error toast hidden behind the sheet.
    private var nameUnaddressable: Bool {
        mode == .create && (targetName.contains("/") || targetName == "." || targetName == "..")
    }

    private var canApply: Bool {
        guard !isApplying else { return false }
        switch mode {
        case .create:
            return !targetName.isEmpty && !nameClash && !nameUnaddressable
        case .edit:
            let c = changes
            return c.added + c.moved + c.removed > 0
        }
    }

    private var summary: String {
        let c = changes
        var parts: [String] = []
        if c.added > 0 { parts.append("\(c.added) to add") }
        if c.moved > 0 { parts.append("\(c.moved) moved from other projects") }
        if c.removed > 0 { parts.append("\(c.removed) to remove") }
        if parts.isEmpty {
            return mode == .create ? "Creates an empty project" : "No changes"
        }
        return parts.joined(separator: " · ")
    }

    // MARK: - Sections

    private var head: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(mode == .create ? "NEW PROJECT" : "PROJECT")
                .font(.system(size: 10.5, weight: .semibold))
                .tracking(1.2)
                .foregroundStyle(Theme.inkMute)
            Group {
                if case .edit(let project) = mode {
                    Text("Choose collections for “\(project)”")
                } else {
                    Text("Name your project")
                }
            }
            .font(.serif(18, weight: .medium))
            .foregroundStyle(Theme.ink)
            .lineLimit(1)
            .truncationMode(.middle)
            Text("A project groups collections; selecting it shows their papers together. A collection belongs to at most one project, so checking one filed elsewhere moves it here. Nothing is deleted.")
                .font(.system(size: 12))
                .foregroundStyle(Theme.inkSoft)
                .lineSpacing(2)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 22)
        .padding(.top, 18)
        .padding(.bottom, 10)
    }

    private var body_: some View {
        VStack(alignment: .leading, spacing: 6) {
            if mode == .create {
                eyebrow("NAME")
                field("Thesis chapter 3", text: $name, focused: .name)
                    .onSubmit(apply)
                if nameClash {
                    Text("A project named “\(targetName)” already exists — use Choose collections… on it instead.")
                        .font(.system(size: 11))
                        .foregroundStyle(Theme.warn)
                        .fixedSize(horizontal: false, vertical: true)
                } else if nameUnaddressable {
                    Text("A project name can't contain “/” or be “.” or “..”.")
                        .font(.system(size: 11))
                        .foregroundStyle(Theme.warn)
                        .fixedSize(horizontal: false, vertical: true)
                }
                eyebrow(collections.isEmpty ? "COLLECTIONS" : "COLLECTIONS · OPTIONAL")
                    .padding(.top, 8)
            } else {
                eyebrow("COLLECTIONS")
            }

            HStack(spacing: 8) {
                HStack(spacing: 6) {
                    Image(systemName: "line.3.horizontal.decrease")
                        .font(.system(size: 11))
                        .foregroundStyle(focus == .filter ? Theme.accentDeep : Theme.inkMute)
                    TextField("Filter — substring, or a glob like r1-*", text: $filter)
                        .textFieldStyle(.plain)
                        .font(.system(size: 12))
                        .foregroundStyle(Theme.ink)
                        .focused($focus, equals: .filter)
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
                .background(Theme.paper, in: RoundedRectangle(cornerRadius: 6))
                .overlay(
                    RoundedRectangle(cornerRadius: 6)
                        .stroke(focus == .filter ? Theme.accent : Theme.paperEdge,
                                lineWidth: focus == .filter ? 1.5 : 1)
                )
                linkButton("All shown") { checked.formUnion(shown.map(\.name)) }
                    .disabled(shown.isEmpty)
                linkButton("None") { checked.subtract(shown.map(\.name)) }
                    .disabled(shown.isEmpty)
            }

            list
                .frame(height: 260)
                .background(Theme.paperDeep, in: RoundedRectangle(cornerRadius: 6))
                .overlay(
                    RoundedRectangle(cornerRadius: 6).stroke(Theme.paperEdge, lineWidth: 1)
                )

            Text(summary)
                .font(.system(size: 11))
                .monospacedDigit()
                .foregroundStyle(Theme.inkMute)
                .lineLimit(1)
            if applyFailed, let lastError {
                Text(lastError)
                    .font(.system(size: 11))
                    .foregroundStyle(Theme.bad)
                    .lineLimit(3)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 22)
        .padding(.vertical, 14)
    }

    @ViewBuilder
    private var list: some View {
        if collections.isEmpty {
            placeholder("No collections yet.")
        } else if shown.isEmpty {
            placeholder("Nothing matches “\(filter)”.")
        } else {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 1) {
                    ForEach(shown) { c in row(c) }
                }
                .padding(4)
            }
        }
    }

    private func row(_ c: CollectionInfo) -> some View {
        let isOn = checked.contains(c.name)
        let elsewhere = otherProject(of: c)
        return Button {
            if isOn { checked.remove(c.name) } else { checked.insert(c.name) }
        } label: {
            HStack(spacing: 8) {
                Image(systemName: isOn ? "checkmark.square.fill" : "square")
                    .font(.system(size: 13))
                    .foregroundStyle(isOn ? Theme.accent : Theme.inkMute)
                    .frame(width: 14)
                Text(c.name)
                    .font(.system(size: 13))
                    .foregroundStyle(c.articleCount == 0 ? Theme.inkMute : Theme.ink)
                    .lineLimit(1)
                    .truncationMode(.tail)
                    .layoutPriority(1)
                if let elsewhere {
                    // Once checked, the same fact reads as a consequence.
                    Text(isOn ? "moves from \(elsewhere)" : "in \(elsewhere)")
                        .font(.system(size: 11))
                        .foregroundStyle(isOn ? Theme.warn : Theme.inkMute)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
                Spacer(minLength: 4)
                Text("\(c.articleCount)")
                    .font(.system(size: 11))
                    .monospacedDigit()
                    .foregroundStyle(Theme.inkMute)
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
            .background(isOn ? Theme.accentSoft.opacity(0.5) : Color.clear,
                        in: RoundedRectangle(cornerRadius: 5))
        }
        .buttonStyle(.plain)
    }

    private var foot: some View {
        HStack {
            Button("Cancel") { dismiss() }
                .buttonStyle(.plain)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(Theme.inkSoft)
                .keyboardShortcut(.cancelAction)
                .padding(.horizontal, 12)
                .padding(.vertical, 6)
            Spacer()
            if isApplying {
                ProgressView().controlSize(.small).padding(.trailing, 6)
            }
            Button(action: apply) {
                HStack(spacing: 6) {
                    Image(systemName: "checkmark")
                        .font(.system(size: 11, weight: .semibold))
                    Text(mode == .create ? "Create" : "Apply")
                }
            }
            .buttonStyle(PrimaryButtonStyle())
            .keyboardShortcut(.defaultAction)
            .disabled(!canApply)
            .opacity(canApply ? 1 : 0.5)
        }
        .padding(.horizontal, 22)
        .padding(.vertical, 14)
        .background(Theme.paperDeep)
        .overlay(alignment: .top) {
            Rectangle().fill(Theme.paperEdge).frame(height: 1)
        }
    }

    // MARK: - Pieces

    private func eyebrow(_ s: String) -> some View {
        Text(s)
            .font(.system(size: 10.5, weight: .semibold))
            .tracking(1.2)
            .foregroundStyle(Theme.inkMute)
    }

    private func field(_ prompt: String, text: Binding<String>, focused f: Field) -> some View {
        TextField(prompt, text: text)
            .textFieldStyle(.plain)
            .font(.system(size: 13))
            .foregroundStyle(Theme.ink)
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .background(Theme.paper, in: RoundedRectangle(cornerRadius: 6))
            .overlay(
                RoundedRectangle(cornerRadius: 6)
                    .stroke(focus == f ? Theme.accent : Theme.paperEdge,
                            lineWidth: focus == f ? 1.5 : 1)
            )
            .focused($focus, equals: f)
    }

    private func linkButton(_ title: String, action: @escaping () -> Void) -> some View {
        Button(title, action: action)
            .buttonStyle(.plain)
            .font(.system(size: 11, weight: .medium))
            .foregroundStyle(Theme.accentDeep)
    }

    private func placeholder(_ s: String) -> some View {
        Text(s)
            .font(.system(size: 12))
            .foregroundStyle(Theme.inkMute)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func apply() {
        guard canApply else { return }
        let project = targetName
        let members = checked.intersection(collections.map(\.name))
        isApplying = true
        applyFailed = false
        Task {
            let ok = await onApply(project, members)
            isApplying = false
            if ok { dismiss() } else { applyFailed = true }
        }
    }
}
