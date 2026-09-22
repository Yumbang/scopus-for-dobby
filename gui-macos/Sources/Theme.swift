import AppKit
import SwiftUI

/// Visual tokens — direct port of `gui-macos/design/project/tokens.css`.
/// Light + dark are deliberate twins (warm paper / warm dark paper), not inversions.
/// Hex literals match the design source 1:1; do not edit without updating tokens.css.
enum Theme {
    // Surfaces — warm paper
    static let paper      = dyn(0xFAF9F5, 0x1F1E1B)
    static let paperDeep  = dyn(0xF5F1EB, 0x181715)
    static let paperEdge  = dyn(0xEDE7DC, 0x2C2A26)
    static let paperSink  = dyn(0xE6DFD2, 0x38352F)

    // Ink (text)
    static let ink        = dyn(0x2A2723, 0xECE6D9)
    static let inkSoft    = dyn(0x5C554B, 0xB5AC9C)
    static let inkMute    = dyn(0x8A8175, 0x847B6D)
    static let inkFaint   = dyn(0xB8AE9F, 0x57514A)

    // Accent — Anthropic ochre / clay
    static let accent     = dyn(0xC96442, 0xD97757)
    static let accentDeep = dyn(0xA8512F, 0xE48E72)
    static let accentSoft = dyn(0xF2E0D5, 0x3A2A22)
    static let accentInk  = dyn(0x6B2D14, 0xF2D3C2)

    // Semantic
    static let good       = dyn(0x5A6E3F, 0x8FA274)
    static let warn       = dyn(0xB07A2B, 0xD6A458)
    static let bad        = dyn(0x8C3A2C, 0xC77160)

    // Tag chip palette
    static let tagBg      = dyn(0xECE5D7, 0x2E2A24)
    static let tagInk     = dyn(0x5C554B, 0xB5AC9C)

    // Foreground for accent-filled buttons (off-white, matches CSS #FFF8F2)
    static let onAccent   = Color(red: 1.0, green: 0.973, blue: 0.949)
}

extension Font {
    /// New York / Charter — used for article titles, abstracts, notes, hero copy.
    static func serif(_ size: CGFloat, weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .serif)
    }
}

private extension NSColor {
    convenience init(rgb: UInt32) {
        let r = CGFloat((rgb >> 16) & 0xFF) / 255.0
        let g = CGFloat((rgb >>  8) & 0xFF) / 255.0
        let b = CGFloat( rgb        & 0xFF) / 255.0
        self.init(srgbRed: r, green: g, blue: b, alpha: 1)
    }
}

private func dyn(_ light: UInt32, _ dark: UInt32) -> Color {
    Color(nsColor: NSColor(name: nil) { appearance in
        let isDark = appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua
        return NSColor(rgb: isDark ? dark : light)
    })
}

/// Wraps an arbitrary collection of subviews and flows them into rows. Used
/// for tag/collection chips. macOS 14+ Layout API.
struct WrapHStack: Layout {
    var spacing: CGFloat = 6
    var lineSpacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxWidth = proposal.width ?? .infinity
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        for sub in subviews {
            let s = sub.sizeThatFits(.unspecified)
            if x > 0, x + s.width > maxWidth {
                x = 0
                y += rowHeight + lineSpacing
                rowHeight = 0
            }
            x += s.width + spacing
            rowHeight = max(rowHeight, s.height)
        }
        let totalH = y + rowHeight
        let totalW = (maxWidth.isFinite ? maxWidth : x)
        return CGSize(width: totalW, height: totalH)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX
        var y = bounds.minY
        var rowHeight: CGFloat = 0
        for sub in subviews {
            let s = sub.sizeThatFits(.unspecified)
            if x > bounds.minX, x + s.width > bounds.maxX {
                x = bounds.minX
                y += rowHeight + lineSpacing
                rowHeight = 0
            }
            sub.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(s))
            x += s.width + spacing
            rowHeight = max(rowHeight, s.height)
        }
    }
}

/// Chip palette. All five map onto existing ``Theme`` tokens — nothing here
/// introduces a colour that isn't already in `tokens.css`.
enum ChipTone {
    /// Neutral chip — tags, affiliations, plain facts.
    case neutral
    /// Accent pill — state the user is currently causing (an active filter,
    /// a selection count) and OpenAlex-derived vocabulary.
    case accent
    /// Semantic. ``Theme.good``/``warn``/``bad`` were previously used only by
    /// the daemon status dot.
    case good, warn, bad

    var ink: Color {
        switch self {
        case .neutral: return Theme.tagInk
        case .accent:  return Theme.accentInk
        case .good:    return Theme.good
        case .warn:    return Theme.warn
        case .bad:     return Theme.bad
        }
    }

    var background: Color {
        switch self {
        case .neutral: return Theme.tagBg
        case .accent:  return Theme.accentSoft
        // The semantic tokens are foreground colours; tokens.css pairs no
        // surface with them, so tint rather than invent a hex literal here.
        case .good:    return Theme.good.opacity(0.16)
        case .warn:    return Theme.warn.opacity(0.16)
        case .bad:     return Theme.bad.opacity(0.16)
        }
    }
}

enum ChipSize {
    /// Detail-pane chips.
    case regular
    /// Header pills and list-row badges, where vertical space is tight.
    case small

    var font: CGFloat { self == .regular ? 11 : 10.5 }
    var hPadding: CGFloat { self == .regular ? 9 : 6 }
    var vPadding: CGFloat { self == .regular ? 3 : 1 }
}

/// The pill every chip and badge in the app is built from: capsule, padding,
/// palette. Split from ``Chip`` because some chips carry interactive content
/// (a hover-revealed remove button) rather than a plain label.
struct ChipShell<Content: View>: View {
    var tone: ChipTone = .neutral
    var size: ChipSize = .regular
    @ViewBuilder var content: Content

    var body: some View {
        content
            .padding(.horizontal, size.hPadding)
            .padding(.vertical, size.vPadding)
            .background(tone.background, in: Capsule())
    }
}

/// A read-only pill: optional SF Symbol, then a label.
struct Chip: View {
    let label: String
    var systemImage: String? = nil
    var tone: ChipTone = .neutral
    var size: ChipSize = .regular

    var body: some View {
        ChipShell(tone: tone, size: size) {
            HStack(spacing: 4) {
                if let systemImage {
                    Image(systemName: systemImage)
                        .font(.system(size: size.font - 1.5, weight: .medium))
                }
                Text(label)
                    .font(.system(size: size.font, weight: .medium))
            }
            .foregroundStyle(tone.ink)
            .lineLimit(1)
        }
    }
}

/// Primary button — accent fill + off-white label. Matches `.btn-primary` in components.css.
struct PrimaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13, weight: .medium))
            .foregroundStyle(Theme.onAccent)
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .background(
                (configuration.isPressed ? Theme.accentDeep : Theme.accent),
                in: RoundedRectangle(cornerRadius: 6)
            )
    }
}

/// What this build is, for the footer.
///
/// Marketing version alone does not answer "am I running the binary I just
/// built" — it only changes on release. The executable's modification date
/// does, and costs one stat.
enum BuildInfo {
    static let version: String =
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "?"

    static let built: String? = {
        guard let exe = Bundle.main.executableURL,
              let date = try? exe.resourceValues(forKeys: [.contentModificationDateKey])
                  .contentModificationDate
        else { return nil }
        let f = DateFormatter()
        f.dateFormat = "d MMM HH:mm"
        return f.string(from: date)
    }()
}
