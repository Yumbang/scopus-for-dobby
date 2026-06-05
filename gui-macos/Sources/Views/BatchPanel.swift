import SwiftUI

/// Detail-pane content shown while ``AppState.multiSelection`` has more than
/// one entry. Offers bulk operations on the selected articles: apply tag,
/// remove tag, add to a collection, remove from the current collection. Each
/// action is fire-and-forget — the events poll loop refreshes the list within
/// ~1.5s and the row chips/colors will reflect the change.
///
/// Design follows the warm-paper detail-pane idiom (see ``ArticleDetailView``)
/// so the swap doesn't feel like a different app.
struct BatchPanel: View {
    @EnvironmentObject private var state: AppState

    @State private var tagDraft: String = ""
    @State private var collectionDraft: String = ""
    @State private var actionInFlight: Bool = false
    @State private var actionStatus: String? = nil

    var body: some View {
        VStack(spacing: 0) {
            header
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    summarySection
                    tagSection
                    collectionSection
                    if let status = actionStatus {
                        Text(status)
                            .font(.system(size: 11))
                            .foregroundStyle(Theme.inkSoft)
                            .padding(.top, 4)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 32)
                .padding(.top, 28)
                .padding(.bottom, 40)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Theme.paper)
    }

    private var header: some View {
        HStack(spacing: 8) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 12))
                .foregroundStyle(Theme.accentDeep)
            Text("\(state.multiSelection.count) articles selected")
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(Theme.ink)
            Spacer()
            Button("Clear selection") { state.clearMultiSelection() }
                .buttonStyle(.plain)
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(Theme.inkSoft)
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 10)
        .overlay(alignment: .bottom) {
            Rectangle().fill(Theme.paperEdge).frame(height: 1)
        }
    }

    private var summarySection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("BATCH ACTIONS")
                .font(.system(size: 10.5, weight: .semibold))
                .tracking(1.2)
                .foregroundStyle(Theme.inkMute)
            Text("Apply changes to all \(state.multiSelection.count) selected articles. Operations run as one round-trip; the list refreshes when the events poll picks up the change.")
                .font(.serif(13))
                .foregroundStyle(Theme.inkSoft)
                .lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var tagSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            label("TAG")
            HStack(spacing: 8) {
                TextField("tag-name (comma-separated for multiple)", text: $tagDraft)
                    .textFieldStyle(.plain)
                    .font(.system(size: 12))
                    .foregroundStyle(Theme.ink)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 6)
                    .background(Theme.paperDeep, in: RoundedRectangle(cornerRadius: 5))
                    .overlay(
                        RoundedRectangle(cornerRadius: 5)
                            .stroke(Theme.paperEdge, lineWidth: 1)
                    )
                Button("Apply") {
                    Task { await runTag(.apply) }
                }
                .buttonStyle(PrimaryButtonStyle())
                .disabled(actionInFlight || parsedTags.isEmpty)

                Button("Remove") {
                    Task { await runTag(.remove) }
                }
                .buttonStyle(.plain)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(Theme.inkSoft)
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
                .overlay(
                    RoundedRectangle(cornerRadius: 5)
                        .stroke(Theme.paperEdge, lineWidth: 1)
                )
                .disabled(actionInFlight || parsedTags.isEmpty)
            }
        }
    }

    private var collectionSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            label("COLLECTION")
            HStack(spacing: 8) {
                Picker("", selection: $collectionDraft) {
                    Text("Pick a collection…").tag("")
                    ForEach(state.collections, id: \.name) { c in
                        Text(c.name).tag(c.name)
                    }
                }
                .labelsHidden()
                .pickerStyle(.menu)
                .frame(maxWidth: 260)
                Button("Add") {
                    Task { await runCollection(.add) }
                }
                .buttonStyle(PrimaryButtonStyle())
                .disabled(actionInFlight || collectionDraft.isEmpty)
            }
            if let current = state.selectedCollection {
                Button {
                    Task { await runCollection(.removeFromCurrent(current)) }
                } label: {
                    Text("Remove from “\(current)”")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(Theme.bad)
                }
                .buttonStyle(.plain)
                .disabled(actionInFlight)
            }
        }
    }

    private func label(_ s: String) -> some View {
        Text(s)
            .font(.system(size: 10.5, weight: .semibold))
            .tracking(1.2)
            .foregroundStyle(Theme.inkMute)
    }

    // MARK: - Actions

    private var parsedTags: [String] {
        // Split on comma only — tag values legitimately contain spaces (e.g.
        // "machine learning"). Whitespace around each comma-separated token
        // is trimmed.
        tagDraft
            .split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
    }

    private enum TagOp { case apply, remove }
    private enum CollectionOp { case add, removeFromCurrent(String) }

    private func runTag(_ op: TagOp) async {
        let eids = Array(state.multiSelection)
        let tags = parsedTags
        actionInFlight = true
        defer { actionInFlight = false }
        let ok: Bool
        let success: String
        switch op {
        case .apply:
            ok = await state.tagBatch(eids: eids, tags: tags)
            success = "Tagged \(eids.count) articles with \(tags.joined(separator: ", "))."
        case .remove:
            ok = await state.untagBatch(eids: eids, tags: tags)
            success = "Removed \(tags.joined(separator: ", ")) from \(eids.count) articles."
        }
        if ok {
            actionStatus = success
            tagDraft = ""
        } else {
            actionStatus = nil  // footer's ``state.lastError`` already shows the cause
        }
    }

    private func runCollection(_ op: CollectionOp) async {
        let eids = Array(state.multiSelection)
        actionInFlight = true
        defer { actionInFlight = false }
        let ok: Bool
        let success: String
        switch op {
        case .add:
            ok = await state.addBatchToCollection(name: collectionDraft, eids: eids)
            success = "Added \(eids.count) articles to “\(collectionDraft)”."
        case .removeFromCurrent(let name):
            ok = await state.removeBatchFromCollection(name: name, eids: eids)
            success = "Removed \(eids.count) articles from “\(name)”."
        }
        if ok {
            actionStatus = success
            if case .add = op { collectionDraft = "" }
        } else {
            actionStatus = nil
        }
    }
}
