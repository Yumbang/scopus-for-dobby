# scopus-for-dobby — macOS GUI Design Specsheet

**Audience:** Frontend / UI designer
**Author hand-off:** Engineer has built a working three-pane SwiftUI skeleton wired to a local HTTP backend. Schema, data flow, and architecture are frozen. Visual design, interaction polish, and the write-path UX are open questions.
**Platform:** Native macOS app (SwiftUI, macOS 14+, Apple Silicon)
**App bundle:** `com.yumbang.scopus-for-dobby`

---

## 1. What this app is

A personal research-library tool for academics. The user runs Scopus (Elsevier) searches from a CLI, and articles accumulate in a local DuckDB database. The macOS app is the **viewer + curator**: browse the library, organize articles into collections, tag them, take notes, and search full-text — all without leaving the desktop.

It is **single-user, local-only**. No login, no cloud sync, no multi-tenant concerns.

### One-line positioning
"Zotero, but stripped to the bone, native, and built around a CLI agent loop. (But not necessarily fully functional as Zotero)"

### Personas
- **Primary:** A grad student / researcher who runs literature reviews, often via an LLM agent (Claude Code), and wants to inspect/curate the resulting library visually.
- **Secondary:** Same user, but at a glance — checking what came in from a recent search.

### Core jobs-to-be-done
1. **Browse** — see what's in the library, filter by collection, sort by date / citations / title.
2. **Read** — open an article's metadata, abstract, DOI, keywords, tags, notes.
3. **Curate** — add to / remove from collections, apply tags, write notes, merge collections. Built: `AppState` calls the daemon for each (`tagArticles`, `setNote`, `addToCollection`, `mergeCollections`).
4. **Search** — live full-text across title, abstract, keywords and the user's own notes. Built, via `searchFTS`.

### Out of scope (do not design for)
- PDF reading or attachment management
- BibTeX / citation export dialogs (handled by CLI)
- Multi-library / multi-user
- Author-level browsing or editing
- iOS / iPad / web

---

## 2. Architecture (so you know what's cheap vs expensive)

```
┌──────────────┐   HTTP (127.0.0.1, port    ┌───────────────────────┐
│              │   from ~/.scopus-for-      │                       │
│              │   dobby/daemon.port)       │                       │
│  macOS App   │ ─────────────────────────► │  Python daemon        │
│  (SwiftUI)   │ ◄───────────────────────── │  FastAPI + DuckDB     │
└──────────────┘   JSON                     └───────────────────────┘
                                                    │
                                                    ▼
                                            ~/.scopus-for-dobby/
                                              articles.duckdb
                                              daemon.{pid,port}
```

- The app talks to a local Python daemon over HTTP. The daemon owns the only DuckDB connection.
- All reads and writes are HTTP calls; **a request round-trip is ~1–5 ms** on an idle machine. Treat it like an in-process call for design purposes.
- An `events` table on the backend tracks every mutation. The app polls `GET /events?since=N` every **1.5 s** and refreshes when it sees changes — meaning if the user runs a CLI command in another terminal, the GUI updates within ~1.5 s. Design for this "background mutation" reality (subtle row insertion / change indicators are nice; popups are not).
- If the daemon is down, the app shows a full-screen "Daemon not reachable / Retry" state. That screen also needs design love.

### What this means for design
- **No loading spinners between panes** — assume sub-100 ms for any pane switch.
- **List virtualization is fine up to 50k articles** — never expect more than ~200 visible at once.
- **Write operations are atomic and immediate** — when the user taps "Apply tag", the row updates in the same animation frame. Don't design for optimistic-UI rollback.

---

## 3. Data model (what each card / row needs to show)

### Article (the central object)
| Field | Type | Notes for design |
|---|---|---|
| `eid` | string | Internal ID. Never shown. |
| `title` | string | Often long (1–3 lines). Truncate at 2 lines in list, full in detail. |
| `authors` | array | First author shown in list ("Smith J. et al."). Full list in detail. |
| `journal` | string | Italic convention. |
| `coverDate` | "YYYY-MM-DD" | Show year in list, full date in detail. |
| `doi` | string | Detail only. Linkable to `https://doi.org/{doi}`. |
| `abstract` | long text | Detail only. Expect 100–500 words. |
| `keywords` | string | Comma-separated. Detail only. |
| `citedBy` | int | "Cited by 42" badge. Often 0 — design must handle absence. |
| `tags` | array | User-applied. 0–5 typical. |
| `notes` | long text | User-written. Often empty. Markdown-ish but render as plain. |
| `addedAt` | timestamp | "Added 3 days ago" — useful for sort. |
| `updatedAt` | timestamp | When the user last edited tags/notes. |
| `fulltextFetchedAt` | timestamp or empty | The paper's body is cached locally. Empty for most rows. **Design opportunity:** a "have the full text" affordance — badge, filter, or open-the-bundle action. |

### Collection
- A named bucket. `name` is the primary key (yes, the string itself).
- Has `articleCount`, a `created` timestamp, and an optional `project`.
- Articles can belong to **multiple** collections.
- Names can be long, multilingual (Korean is common: "수질관리특론"), and include spaces / punctuation.

### Project
- A named group of collections, **one level deep** — projects do not nest.
- A collection is in **at most one** project, or in none ("ungrouped").
- A project holds **no articles of its own**. Selecting it shows the deduplicated union of its collections' articles, so its `articleCount` is usually *less* than the sum of its collections' counts.
- Consequently articles cannot be added to or removed from a project directly — only to its collections. Filing a collection into a project (or out of it) is the only membership action.
- Deleting a project keeps its collections; they become ungrouped.
- The single-article payload lists the `projects` an article reaches through its collections; list rows do not carry it.

### Sidebar selection
- "All articles" (always present, top of sidebar)
- Projects first, each expandable to its member collections (indented beneath it), then the ungrouped collections — each list sorted alphabetically. A project row selects the union of its collections.
- The sidebar is the **filter** for the article list. No tag-based filter yet (design opportunity).

---

## 4. Current screen inventory

The skeleton ships with a `NavigationSplitView` three-pane layout. Below is what exists and what's missing.

### 4.1 Window chrome
- Standard macOS title bar with traffic-light controls.
- No toolbar yet. **Design opportunity:** what belongs in a toolbar? (Suggestions: search field, +Article, refresh / daemon-status indicator, view-mode toggle.)

### 4.2 Sidebar (left pane, ~220pt min width)
**Currently:**
- Section "Library" → "All articles" row (icon: `tray.full`), counting the whole library.
- Section "Projects" (header shows the project count and a `+` menu: *New collection…* / *New project…*; right-clicking the header offers the same) → one row per project (icon: `rectangle.stack`), with its distinct-article count and a chevron that expands it to show its member collections indented beneath it; an expanded empty project shows "No collections — choose…". With no projects, a muted "No projects — create one…" row.
- Section "Collections" — titled "Ungrouped collections" once any project exists — with the same header controls, one row per collection filed under no project (icon: `folder`) with its count.
- A row with a zero count has a muted label, so empty collections and projects read differently from populated ones.
- Project context menu: *Choose collections…* (a checkbox sheet for bulk filing — checking a collection filed elsewhere moves it), *Rename…* (inline), *New collection in project…*, *New project…*, *Delete…* (confirmation dialog; the collections are kept, ungrouped).
- Collection context menu: *Rename…* (inline), *Merge into…* (sheet), *Move to project* submenu (ending in *New project…*), *Remove from "project"* when filed, *Delete*.
- Footer: daemon status dot, port, and app/CLI version line.

**Gaps for you:**
- No drag-and-drop anywhere: articles cannot be dragged onto a collection (adding goes through the multi-select batch panel), and collections cannot be dragged into a project (filing goes through the context menu or the *Choose collections…* sheet). Is drag worth designing for either?
- No empty state when zero collections exist — the section is just a header with a `0`.
- Deleting a collection has no confirmation (deleting a project does).
- No "smart collection" concept (e.g., "Untagged", "Recently added") — should we have these? Mockup welcome.
- No tag or author section in the sidebar.

### 4.3 Article list (middle pane, ~360pt min width)
**Currently:**
- Two-line row: title (headline weight, max 2 lines), then a metadata strip with first author, journal (italic), year, and citation count badge.
- Single-select via `List(selection:)`.
- Empty state uses `ContentUnavailableView("No articles", ...)` with system icon and helper text.

**Gaps for you:**
- No sort control. Sort axes we want: title, added date, cover date, citations, last updated. Where does this UI go? Column header? Toolbar menu? Right-click on list?
- No multi-select visual. macOS convention is Cmd-click / Shift-click; the data layer supports it but we have no batch-action UI.
- No tag chips on the row. Should we surface them inline, or keep the row clean? (Argument for clean: 99% of the user's time is browsing, not auditing tags.)
- No "added recently" indicator (e.g., a soft dot for items added in the last 24 h).
- No way to visually distinguish articles in the current collection vs the global "All articles" view.
- Density: currently quite roomy. Design a "compact" alternate for power-user mode?

### 4.4 Detail pane (right, ~360pt min width)
**Currently:**
- Title (title2, semibold)
- Metadata strip (first author • journal • cover date)
- "N citations" label if non-zero
- DOI as a clickable link
- Abstract (selectable text)
- Keywords
- Tags as `Capsule()` chips with secondary background
- Notes (selectable)

**Gaps for you:**
- No edit affordances. The user cannot currently add/remove tags, edit notes, or add to a collection from this pane. **This is the biggest design surface for you.** What does inline editing look like? Edit-in-place vs edit-mode toggle vs sheet?
- The hierarchy is functional but visually flat. Headline / Abstract / Notes all use similar weights. Spacing and typographic scale need a designer's eye.
- Tag chips are uniform secondary gray. Color-by-tag? User-pickable tag colors? Stick with monochrome?
- No "Open in Scopus" or "Copy citation" actions. Should they live in a per-article menu?
- "Authors" beyond the first are currently hidden. Where do they go?
- No way to see *which collections this article belongs to* or to remove it from one. Critical write-path gap.

### 4.5 Daemon-down full-screen state
**Currently:**
- Centered `bolt.slash` system icon (48pt)
- "Daemon not reachable" title2
- Error message body (callout, secondary)
- "Retry" button (default-action keyboard shortcut)

**Gaps for you:**
- No visual brand presence — feels like a SwiftUI default. Could use a friendlier illustration.
- The error message body is technical (literal `errorDescription` from URLSession). Designer could propose a copy framework: friendly first sentence, optional "Show technical details" disclosure.

### 4.6 Search (does not exist yet — pure design opportunity)
We will add a full-text search bar that hits the backend with ~150 ms debounce. Open questions:
- Does it live in the toolbar or above the article list?
- Should the result list visually differ from the regular article list (highlight matches? show snippets)?
- How do we communicate "search is filtering on top of the current collection"?
- Is there a "recent searches" shelf?

### 4.7 Multi-select batch operations (does not exist yet)
The user wants to: select 10 articles → tag them all "review-2024" → move them to collection "Foo".
- Where does the batch-action bar appear (bottom of list? popover from selection count? toolbar?)
- What's the visual selection treatment for 1 vs many?
- Confirmation patterns: tag application is reversible — does it need a confirmation? (Lean: no.) Removing from a collection? (Lean: no, but a toast with "Undo".)

### 4.8 Collection write operations (does not exist yet)
- Create collection (modal sheet? inline at sidebar bottom?)
- Rename (inline rename like Finder? sheet?)
- Merge collections (this needs special design love — it's destructive-ish: source collection disappears)
- Delete (confirmation flow)

---

## 5. Visual style — Anthropic-inspired

We want the app to feel like it belongs in the **Anthropic / Claude visual family** — calm, literary, paper-like, generous whitespace, warm neutrals over cool grays, restrained accent use. Think Claude.ai's reading surfaces and Anthropic's marketing site, translated to a native macOS three-pane app.

Concrete cues to lean into:
- **Warm off-white background** (something near `#F5F1EB` / `#FAF9F5`) instead of pure system white, with a near-black ink color for body text rather than `#000`.
- **Anthropic's accent ochre / clay** (`#C96442`-ish) used *sparingly* — for the active sidebar row, the primary action button, and selection highlights. Not for chrome.
- **Serif for long-form reading surfaces** (article title in the detail pane, abstract body) — Tiempos / Charter / NY style. Sans (SF Pro / Styrene-feel) for everything else: list rows, sidebar, controls.
- **Quiet hierarchy.** Differentiate sections by typographic weight and spacing, not by boxes/dividers. Borrow Claude.ai's "no card chrome" feel.
- **Tag chips** as low-contrast pill shapes with the warm-neutral palette, not saturated category colors.
- **Subtle motion** — Claude.ai's gentle fades on content swap. No bounce, no spring overshoot.
- **Dark mode as a deliberate twin**, not an inversion. Same warm-paper feel, just darker (think `#1F1E1B` / `#2A2826` paper, with the same ochre accent at slightly higher luminance).

The earlier defaults SwiftUI shipped need replacing across the board. We'd still like proposals on:
- **Identity:** Wordmark / icon. The name "scopus-for-dobby" is a private joke ("Dobby" is the user's nickname); brand around "Dobby" warmly but in the Anthropic register — restrained, literary, not cute. Maybe a small mark, not a mascot.
- **Density:** macOS apps trend roomy lately. Anthropic surfaces are roomy too. Default to roomy; offer a compact toggle for power use.
- **Empty states:** Quiet, single-line copy with a small mark — not full illustrations. Anthropic-restrained.
- **Loading states:** Currently a vanilla `ProgressView` at app launch. Replace with something on-brand and quiet.

---

## 6. Interaction priorities (engineer's prioritization, open to debate)

**Must:**
1. Multi-select + batch tag / batch add-to-collection (we cannot ship without this)
2. Inline edit of tags and notes from the detail pane
3. Live full-text search field

**Should:**
4. Sort axes selector for the article list
5. Collection CRUD (create / rename / delete / merge) with sane confirmations
6. Toolbar with daemon-status indicator + quick actions

**Could:**
7. Drag-and-drop article → collection
8. "Smart collections" (Untagged, Recent, etc.)
9. Article context menu (Open in Scopus, Copy DOI, Copy citation)
10. Per-tag colors

**Won't (this version):**
- Author-pane browsing
- PDF integration
- iCloud / sync

---

## 7. Deliverables we'd love (any of these formats are great)

Either Figma **or** an HTML/CSS mockup is welcome. If you ship HTML, engineering will translate it to SwiftUI by hand — so optimize for clarity over fidelity. Use semantic HTML and CSS variables; we'll map them to `Theme.swift` and SwiftUI views.

1. **Mockups** (Figma file or static HTML) covering:
   - Three-pane layout, light + dark, at 1280×800 and 1680×1050
   - Detail pane in view + edit modes
   - Multi-select state with batch-action bar
   - Search active state
   - Collection-merge sheet (or whatever pattern you propose)
   - All five empty states (library / collection / search / daemon-down / first-launch)
2. **Component library** — buttons, chips, list rows, sheet headers. If HTML, one component per `<section>` with a clear class name we can name-map to SwiftUI views.
3. **Type + color tokens** — named so we can drop them into a `Theme.swift`. If HTML, expose them as `:root { --color-paper: …; --font-serif: …; }` CSS custom properties; we'll port them 1:1.
4. **Icon proposal** — app icon at 1024² (PNG/SVG fine) + the ICNS sizes if you have them in your output flow.
5. **Copy pass** — friendlier error / empty-state strings. Eight to ten total.

### Notes for HTML deliverables specifically
- Use system-font fallbacks alongside the intended typeface (e.g., `font-family: "Tiempos Text", Charter, "New York", Georgia, serif;`) so engineering can pick SwiftUI equivalents without scrambling for font licenses.
- Keep layout in flexbox/grid — no JS frameworks. We are reading the CSS, not running the file.
- Annotate hover, selected, focused, and dark-mode variants in the same file (separate sections is fine).
- Don't worry about responsiveness below 1100px; this is a desktop app.

Not needed: motion specs (we're using SwiftUI defaults), interactive prototypes, brand book.

---

## 8. Constraints / non-negotiables

- **macOS 14+ only.** Use any modern SwiftUI APIs (e.g., `ContentUnavailableView`, `LabeledContent`, `Table`, `.searchable`).
- **No custom windowing tricks.** Standard `NavigationSplitView`. Floating panels and tabs are out.
- **Sandbox is OFF** — but the user is the only user; do not design around per-app permission prompts.
- **All copy in English** for v1; the data itself can be multilingual (Korean, etc.) so the UI must render non-Latin scripts in titles/collections without truncation surprises.
- **Engineering time is the bottleneck**, not design. Prefer designs that lean on system components over fully bespoke ones. A polished default-tier app beats a half-built bespoke one.

---

## 9. References the engineer is looking at

- **Reeder 5** — list density, three-pane discipline
- **DEVONthink** — research-library reference (but we want to be lighter)
- **macOS Notes / Reminders** — modern macOS chrome, sidebar idioms
- **Things 3** — for tag chip treatment and inline editing tone
- **Linear (macOS)** — keyboard-first power-user feel

You don't have to ape any of these. Pick what's good.

---

*Source of truth for current code: `gui-macos/Sources/Views/{ContentView,CollectionsSidebar,ArticleListView,ArticleDetailView}.swift`. Implementation plan with all ADRs: `.omc/plans/gui-implementation-plan.md`. Backend API surface: `scopus_for_dobby/server/app.py` — every endpoint listed in the plan's "Daemon endpoints (live)" line.*
