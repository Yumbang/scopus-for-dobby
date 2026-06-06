import SwiftUI

/// Modal sheet for creating a new collection. Mirrors the design's
/// `NewCollectionSheet` (states.jsx) — eyebrow + serif title + text field +
/// Cancel/Create footer, on warm-paper background.
struct NewCollectionSheet: View {
    var onCreate: (String) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var name: String = ""
    @FocusState private var nameFocused: Bool

    var body: some View {
        VStack(spacing: 0) {
            head
            body_
            foot
        }
        .frame(width: 420)
        .background(Theme.paper)
        .onAppear { DispatchQueue.main.async { nameFocused = true } }
    }

    private var head: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("NEW COLLECTION")
                .font(.system(size: 10.5, weight: .semibold))
                .tracking(1.2)
                .foregroundStyle(Theme.inkMute)
            Text("Name your collection")
                .font(.serif(18, weight: .medium))
                .foregroundStyle(Theme.ink)
            Text("Collections are buckets for articles. An article can live in many. Names can include any language.")
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
            Text("NAME")
                .font(.system(size: 10.5, weight: .semibold))
                .tracking(1.2)
                .foregroundStyle(Theme.inkMute)
            TextField("Membrane fouling — chapter 3", text: $name)
                .textFieldStyle(.plain)
                .font(.system(size: 13))
                .foregroundStyle(Theme.ink)
                .padding(.horizontal, 10)
                .padding(.vertical, 7)
                .background(Theme.paper, in: RoundedRectangle(cornerRadius: 6))
                .overlay(
                    RoundedRectangle(cornerRadius: 6)
                        .stroke(nameFocused ? Theme.accent : Theme.paperEdge,
                                lineWidth: nameFocused ? 1.5 : 1)
                )
                .focused($nameFocused)
                .onSubmit(commit)
            Text("Tip: keep it short. You can rename later.")
                .font(.system(size: 11))
                .foregroundStyle(Theme.inkMute)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 22)
        .padding(.vertical, 14)
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
            Button(action: commit) {
                HStack(spacing: 6) {
                    Image(systemName: "checkmark")
                        .font(.system(size: 11, weight: .semibold))
                    Text("Create")
                }
            }
            .buttonStyle(PrimaryButtonStyle())
            .keyboardShortcut(.defaultAction)
            .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty)
        }
        .padding(.horizontal, 22)
        .padding(.vertical, 14)
        .background(Theme.paperDeep)
        .overlay(alignment: .top) {
            Rectangle().fill(Theme.paperEdge).frame(height: 1)
        }
    }

    private func commit() {
        let trimmed = name.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { return }
        onCreate(trimmed)
        dismiss()
    }
}

/// Inline rename field that auto-focuses, commits on Return, cancels on Esc,
/// and commits on focus loss (clicking elsewhere). Used by the sidebar's
/// in-place rename affordance.
struct InlineRenameField: View {
    @Binding var text: String
    var onCommit: () -> Void
    var onCancel: () -> Void
    @FocusState private var focused: Bool
    @State private var didCommit: Bool = false

    var body: some View {
        TextField("", text: $text)
            .textFieldStyle(.plain)
            .font(.system(size: 13, weight: .medium))
            .foregroundStyle(Theme.ink)
            .focused($focused)
            .onSubmit { commitOnce() }
            .onExitCommand(perform: onCancel)
            .onAppear { DispatchQueue.main.async { focused = true } }
            .onChange(of: focused) { _, isFocused in
                // Commit on blur (Finder semantics). Without this, clicking
                // elsewhere silently discards the edit. ``didCommit`` guards
                // against the Return-then-blur double-fire path.
                if !isFocused { commitOnce() }
            }
    }

    private func commitOnce() {
        guard !didCommit else { return }
        didCommit = true
        onCommit()
    }
}

/// Merge sheet — pick a destination collection and confirm. Source name is
/// shown line-through to telegraph that it disappears after merge.
struct MergeCollectionSheet: View {
    let src: String
    let candidates: [String]
    var onMerge: (String) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var dst: String = ""

    var body: some View {
        VStack(spacing: 0) {
            head
            body_
            foot
        }
        .frame(width: 440)
        .background(Theme.paper)
        .onAppear { dst = candidates.first ?? "" }
    }

    private var head: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("MERGE COLLECTION")
                .font(.system(size: 10.5, weight: .semibold))
                .tracking(1.2)
                .foregroundStyle(Theme.inkMute)
            Text("Merge into another collection")
                .font(.serif(18, weight: .medium))
                .foregroundStyle(Theme.ink)
            HStack(spacing: 6) {
                Text(src)
                    .strikethrough()
                    .foregroundStyle(Theme.inkMute)
                Image(systemName: "arrow.right")
                    .font(.system(size: 10))
                    .foregroundStyle(Theme.inkMute)
                Text(dst.isEmpty ? "(pick a destination)" : dst)
                    .foregroundStyle(Theme.accentDeep)
            }
            .font(.system(size: 12, design: .monospaced))
            .padding(.top, 2)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 22)
        .padding(.top, 18)
        .padding(.bottom, 10)
    }

    private var body_: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("DESTINATION")
                .font(.system(size: 10.5, weight: .semibold))
                .tracking(1.2)
                .foregroundStyle(Theme.inkMute)
            Picker("", selection: $dst) {
                ForEach(candidates, id: \.self) { c in
                    Text(c).tag(c)
                }
            }
            .labelsHidden()
            .pickerStyle(.menu)
            .frame(maxWidth: .infinity, alignment: .leading)

            HStack(alignment: .top, spacing: 6) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: 11))
                    .foregroundStyle(Theme.warn)
                Text("Articles in “\(src)” move into “\(dst.isEmpty ? "…" : dst)”. Duplicates are de-duplicated. The source collection is deleted. This cannot be undone.")
                    .font(.system(size: 11))
                    .foregroundStyle(Theme.inkSoft)
                    .lineSpacing(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(10)
            .background(Theme.paperDeep, in: RoundedRectangle(cornerRadius: 6))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 22)
        .padding(.vertical, 14)
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
            Button(action: commit) {
                HStack(spacing: 6) {
                    Image(systemName: "arrow.triangle.merge")
                        .font(.system(size: 11, weight: .semibold))
                    Text("Merge")
                }
            }
            .buttonStyle(PrimaryButtonStyle())
            .keyboardShortcut(.defaultAction)
            .disabled(dst.isEmpty || dst == src)
        }
        .padding(.horizontal, 22)
        .padding(.vertical, 14)
        .background(Theme.paperDeep)
        .overlay(alignment: .top) {
            Rectangle().fill(Theme.paperEdge).frame(height: 1)
        }
    }

    private func commit() {
        guard !dst.isEmpty, dst != src else { return }
        onMerge(dst)
        dismiss()
    }
}
