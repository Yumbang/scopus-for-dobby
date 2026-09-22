// app.jsx — composes the design canvas with all mockup artboards.
const { WindowFrame, Sidebar, Row, ListHeader } = window.Frames;
const { BatchPanel, MergeSheet, NewCollectionSheet, EmptyState, Wordmark, SockGlyph } = window.States;
const { ARTICLES } = window.SCOPUS_DATA;

// shared body grid for three-pane
const Body = ({ children, listWidth = 380 }) => (
  <div className="win-body" style={{ gridTemplateColumns: `220px ${listWidth}px 1fr` }}>{children}</div>
);

// canonical full mock — light, primary state
const MockMain = ({ theme = "light", title = "scopus-for-dobby", active = "Membrane fouling", selectedIdx = 0, multi = [], showSmart = false, mode = "view", clamped = false, dropTarget = null, daemonState = "running", showAddInline = false, sort = "Added", searchActive = false, searchQuery = "", listVariant = "default", overlay = null, compact = false, showWordmark = false }) => {
  const filtered = active === "All articles" ? ARTICLES : ARTICLES.filter(a => (a.collections || []).includes(active));
  const list = filtered.length ? filtered : ARTICLES;
  const sel = list[selectedIdx] || list[0];
  return (
    <WindowFrame theme={theme} title={title} width={1280} height={800}>
      <Body>
        <Sidebar active={active} showSmart={showSmart} dropTarget={dropTarget} daemonState={daemonState} showAddInline={showAddInline}/>
        <div className={`list-pane ${compact ? "is-compact" : ""}`}>
          <ListHeader collection={active} count={list.length === ARTICLES.length ? 1284 : list.length} sort={sort} searchActive={searchActive} searchQuery={searchQuery}/>
          <div className="list-rows">
            {list.map((a, i) => (
              <Row key={a.eid} a={a}
                   selected={multi.length === 0 && i === selectedIdx}
                   multi={multi.includes(i)}
                   snippet={searchActive && i < 3 ? buildSnippet(a, searchQuery) : null}
                   compact={compact}/>
            ))}
          </div>
        </div>
        {multi.length > 1 ? <BatchPanel count={multi.length}/> : <Detail a={sel} mode={mode} clamped={clamped}/>}
      </Body>
      {overlay === "merge" && <MergeSheet/>}
      {overlay === "new-collection" && <NewCollectionSheet/>}
    </WindowFrame>
  );
};

const buildSnippet = (a, q) => {
  const text = a.abstract || a.title;
  if (!text) return null;
  const re = new RegExp(`(${q.split(" ")[0]})`, "ig");
  return "…" + text.slice(0, 220).replace(re, "<mark>$1</mark>") + "…";
};

// ── Daemon-down full-window view
const DaemonDown = () => (
  <WindowFrame theme="light" title="scopus-for-dobby" width={1280} height={800}>
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", background: "var(--paper)", height: "100%" }}>
      <EmptyState kind="daemon"/>
    </div>
  </WindowFrame>
);

// ── Type scale showcase
const TypeScale = () => (
  <div className="typescale" style={{ width: 760 }}>
    <div className="row">
      <div className="label">Display</div>
      <div style={{ fontFamily: "var(--font-serif)", fontSize: 28, fontWeight: 500, letterSpacing: "-0.015em" }}>A quiet place for your reading.</div>
      <div className="meta">Tiempos · 28/1.1</div>
    </div>
    <div className="row">
      <div className="label">Title (article)</div>
      <div style={{ fontFamily: "var(--font-serif)", fontSize: 20, fontWeight: 500, letterSpacing: "-0.01em" }}>Long-term performance of submerged anaerobic membrane bioreactors</div>
      <div className="meta">Tiempos · 20/1.28</div>
    </div>
    <div className="row">
      <div className="label">Abstract / body</div>
      <div style={{ fontFamily: "var(--font-serif)", fontSize: 14, lineHeight: 1.62 }}>Submerged anaerobic membrane bioreactors offer a promising route to energy-positive municipal wastewater treatment.</div>
      <div className="meta">Tiempos · 14/1.62</div>
    </div>
    <div className="row">
      <div className="label">Headline (UI)</div>
      <div style={{ fontSize: 15, fontWeight: 600, letterSpacing: "-0.01em" }}>Membrane fouling · 47</div>
      <div className="meta">Inter · 15/1.4 · 600</div>
    </div>
    <div className="row">
      <div className="label">List row</div>
      <div style={{ fontSize: 13, fontWeight: 600 }}>Granular sludge stability under transient organic loading…</div>
      <div className="meta">Inter · 13/1.35 · 600</div>
    </div>
    <div className="row">
      <div className="label">Metadata</div>
      <div style={{ fontSize: 12, color: "var(--ink-soft)" }}>Smith, J. <span style={{ color: "var(--ink-mute)" }}>·</span> <em>Water Research</em> <span style={{ color: "var(--ink-mute)" }}>·</span> 2024</div>
      <div className="meta">Inter · 12/1.4 · 400</div>
    </div>
    <div className="row">
      <div className="label">Section eyebrow</div>
      <div style={{ fontSize: 10.5, fontWeight: 600, textTransform: "uppercase", letterSpacing: ".1em", color: "var(--ink-mute)" }}>In collections</div>
      <div className="meta">Inter · 10.5/1 · 600 · UPPER</div>
    </div>
  </div>
);

// ── Color swatches
const ColorScale = ({ theme = "light" }) => {
  const groups = theme === "light" ? [
    { name: "Paper", items: [["paper", "#FAF9F5"], ["paper-deep", "#F5F1EB"], ["paper-edge", "#EDE7DC"], ["paper-sink", "#E6DFD2"]] },
    { name: "Ink", items: [["ink", "#2A2723"], ["ink-soft", "#5C554B"], ["ink-mute", "#8A8175"], ["ink-faint", "#B8AE9F"]] },
    { name: "Accent · ochre", items: [["accent", "#C96442"], ["accent-deep", "#A8512F"], ["accent-soft", "#F2E0D5"], ["accent-ink", "#6B2D14"]] },
    { name: "Semantic", items: [["good", "#5A6E3F"], ["warn", "#B07A2B"], ["bad", "#8C3A2C"]] },
  ] : [
    { name: "Paper", items: [["paper", "#1F1E1B"], ["paper-deep", "#181715"], ["paper-edge", "#2C2A26"], ["paper-sink", "#38352F"]] },
    { name: "Ink", items: [["ink", "#ECE6D9"], ["ink-soft", "#B5AC9C"], ["ink-mute", "#847B6D"], ["ink-faint", "#57514A"]] },
    { name: "Accent", items: [["accent", "#D97757"], ["accent-deep", "#E48E72"], ["accent-soft", "#3A2A22"], ["accent-ink", "#F2D3C2"]] },
  ];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18, padding: 24, background: theme === "light" ? "#FAF9F5" : "#1F1E1B", color: theme === "light" ? "#2A2723" : "#ECE6D9", borderRadius: 8, width: 760 }}>
      {groups.map(g => (
        <div key={g.name}>
          <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: ".1em", color: theme === "light" ? "#8A8175" : "#847B6D", fontWeight: 600, marginBottom: 10 }}>{g.name}</div>
          <div className="swatch-grid">
            {g.items.map(([n, v]) => (
              <div key={n} className="sw">
                <div className="chip-color" style={{ background: v }}/>
                <div className="name">--{n}</div>
                <div className="val" style={{ color: theme === "light" ? "#8A8175" : "#847B6D" }}>{v}</div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
};

// ── Component shelf
const ComponentShelf = () => (
  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24, width: 880, padding: 28, background: "#FAF9F5", borderRadius: 8, border: "1px solid #EDE7DC" }}>
    <div>
      <div style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: ".1em", color: "#8A8175", fontWeight: 600, marginBottom: 10 }}>Buttons</div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button className="btn btn-primary"><Icon name="check" size={12}/>Create</button>
        <button className="btn">Cancel</button>
        <button className="btn btn-ghost"><Icon name="link" size={12}/>Open in Scopus</button>
        <button className="btn btn-danger"><Icon name="trash" size={12}/>Delete</button>
        <button className="btn btn-sm">⌘K</button>
      </div>
    </div>
    <div>
      <div style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: ".1em", color: "#8A8175", fontWeight: 600, marginBottom: 10 }}>Chips</div>
      <div className="chip-row">
        <span className="chip">membrane-fouling</span>
        <span className="chip is-removable">review-2024<span className="x" style={{ opacity: 1 }}><Icon name="x" size={10}/></span></span>
        <span className="chip is-collection"><Icon name="folder" size={11}/>PhD lit review</span>
        <span className="chip-input"><Icon name="plus" size={10}/>Add tag</span>
      </div>
    </div>
    <div>
      <div style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: ".1em", color: "#8A8175", fontWeight: 600, marginBottom: 10 }}>Search field</div>
      <div className="search-field" style={{ width: 240 }}><Icon name="search" size={12}/><span className="placeholder">Search library…</span><span className="kbd">⌘F</span></div>
      <div style={{ height: 8 }}/>
      <div className="search-field is-active" style={{ width: 240 }}><Icon name="search" size={12}/><span>membrane fouling</span><span className="scope">in PhD lit review</span></div>
    </div>
    <div>
      <div style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: ".1em", color: "#8A8175", fontWeight: 600, marginBottom: 10 }}>Sidebar row states</div>
      <div style={{ background: "#F5F1EB", padding: 8, borderRadius: 6 }}>
        <div className="sidebar-row">       <Icon name="folder"/><span>Default</span><span className="count">12</span></div>
        <div className="sidebar-row is-active"><Icon name="folder"/><span>Active (selected)</span><span className="count">47</span></div>
        <div className="sidebar-row is-droptarget"><Icon name="folder"/><span>Drop target (drag-over)</span><span className="count">8</span></div>
        <div className="sidebar-row is-empty"><Icon name="folder"/><span>Empty collection</span><span className="count">0</span></div>
      </div>
    </div>
  </div>
);

// ── Wordmark / icon proposal
const IconProposal = () => (
  <div style={{ display: "flex", flexDirection: "column", gap: 28, width: 760, padding: 32, background: "#FAF9F5", borderRadius: 8, border: "1px solid #EDE7DC" }}>
    <div style={{ display: "flex", gap: 36, alignItems: "center", flexWrap: "wrap" }}>
      <div style={{ width: 128, height: 128, borderRadius: 28, background: "linear-gradient(160deg, #FAF9F5, #ECE2D2)", border: "1px solid #E6DFD2", display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 12px 32px -10px rgba(40,30,20,.18), inset 0 1px 0 rgba(255,255,255,.6)" }}>
        <SockGlyph size={68}/>
      </div>
      <div style={{ width: 64, height: 64, borderRadius: 14, background: "linear-gradient(160deg, #FAF9F5, #ECE2D2)", border: "1px solid #E6DFD2", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <SockGlyph size={36}/>
      </div>
      <div style={{ width: 32, height: 32, borderRadius: 7, background: "linear-gradient(160deg, #FAF9F5, #ECE2D2)", border: "1px solid #E6DFD2", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <SockGlyph size={18}/>
      </div>
      <div style={{ width: 16, height: 16, borderRadius: 4, background: "#FAF9F5", border: "1px solid #E6DFD2", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <SockGlyph size={10}/>
      </div>
    </div>
    <div style={{ fontSize: 13, color: "#5C554B", lineHeight: 1.55, maxWidth: 56 + "ch" }}>
      An abstract single-stroke <em>sock</em> — a quiet nod to "Dobby" without leaning into the mascot. The form reads as an L-silhouette: cuff, leg, heel, foot. Ochre on warm paper. Looks like a margin glyph, not a logo.
    </div>
    <div style={{ display: "flex", gap: 16, alignItems: "baseline", padding: "12px 0", borderTop: "1px solid #EDE7DC" }}>
      <Wordmark large/>
      <div style={{ marginLeft: "auto", fontSize: 11, color: "#8A8175", fontFamily: "ui-monospace, monospace" }}>com.yumbang.scopus-for-dobby</div>
    </div>
  </div>
);

// ── Copy pass
const CopyPass = () => (
  <div style={{ width: 760, padding: 28, background: "#FAF9F5", borderRadius: 8, border: "1px solid #EDE7DC", fontSize: 13, lineHeight: 1.6, color: "#2A2723" }}>
    <div style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: ".1em", color: "#8A8175", fontWeight: 600, marginBottom: 14 }}>Copy framework — friendly first, technical on disclosure</div>
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
      <thead>
        <tr style={{ borderBottom: "1px solid #EDE7DC", color: "#8A8175", fontSize: 11, textTransform: "uppercase", letterSpacing: ".06em", fontWeight: 600 }}>
          <th style={{ textAlign: "left", padding: "8px 8px 8px 0", width: "30%" }}>Surface</th>
          <th style={{ textAlign: "left", padding: 8 }}>Was</th>
          <th style={{ textAlign: "left", padding: 8 }}>Suggested</th>
        </tr>
      </thead>
      <tbody>
        {[
          ["Daemon-down title", "Daemon not reachable", "The daemon is asleep."],
          ["Daemon-down body", "(literal URLSession error)", "scopus-for-dobby's local server isn't responding on :8765. Start it from a terminal, or click Retry."],
          ["Empty library", "No articles", "Your library is empty."],
          ["Empty library sub", "Use `scopus-for-dobby search` or import to populate.", "Run a search from the CLI — articles you collect there will appear here."],
          ["Empty collection", "(none)", "Nothing in this collection yet."],
          ["Empty search", "(none)", "No matches. Try a broader term, or clear the collection filter."],
          ["First launch", "(spinner)", "A quiet place for your reading."],
          ["Notes empty", "(field hidden)", "Write a note about this article…"],
          ["Merge confirm", "(none)", "Merge \"To re-read\" into \"PhD lit review\"?"],
          ["Add tag input", "Tags", "Add tag (or pick an existing one)"],
        ].map((r, i) => (
          <tr key={i} style={{ borderBottom: "1px solid #EDE7DC" }}>
            <td style={{ padding: "10px 8px 10px 0", color: "#5C554B", fontFamily: "ui-monospace, monospace", fontSize: 11 }}>{r[0]}</td>
            <td style={{ padding: 10, color: "#8A8175", fontStyle: "italic" }}>{r[1]}</td>
            <td style={{ padding: 10 }}>{r[2]}</td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

// ── Smart collections proposal annotation
const SmartProposalNote = () => (
  <div style={{ width: 480, padding: 22, background: "#FAF9F5", borderRadius: 8, border: "1px dashed #C96442", fontSize: 13, lineHeight: 1.6, color: "#2A2723" }}>
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
      <span className="badge" style={{ background: "#F2E0D5", color: "#6B2D14" }}><Icon name="sparkle" size={11}/>Proposal</span>
      <strong style={{ fontFamily: "var(--font-serif)", fontSize: 16, fontWeight: 500 }}>Smart collections</strong>
    </div>
    <p style={{ margin: 0, color: "#5C554B" }}>
      Three system buckets sit above user collections: <strong>Untagged</strong> (anything with zero tags — surfaces the curation backlog), <strong>Recently added</strong> (last 7 days), and <strong>Most cited</strong> (top 50 by citedBy in the current library).
    </p>
    <p style={{ marginTop: 10, color: "#5C554B" }}>
      Read-only on the GUI side — no membership editing. Engineering cost is one new endpoint each, or a single <code style={{ fontFamily: "var(--font-mono)", fontSize: 11, background: "#EDE7DC", padding: "1px 4px", borderRadius: 3 }}>?smart=...</code> query param on /articles.
    </p>
  </div>
);

// ──────────────────────────────────────────────────────────
// THE CANVAS
// ──────────────────────────────────────────────────────────
const App = () => (
  <DesignCanvas>
    <DCSection id="hero" title="scopus-for-dobby · macOS GUI" subtitle="Anthropic-warm three-pane viewer for a personal research library. CSS class names map 1:1 to SwiftUI views — see tokens.css and components.css.">
      <DCArtboard id="cover" label="Cover" width={920} height={420}>
        <div style={{ height: "100%", background: "linear-gradient(160deg, #FAF9F5, #ECE2D2)", padding: "56px 64px", display: "flex", flexDirection: "column", justifyContent: "space-between", borderRadius: 8 }}>
          <div className="canvas-intro">
            <span className="kicker">macOS · SwiftUI · v1 facade</span>
            <h1>A quiet place for your reading.</h1>
            <p>A personal research-library tool, translated to a native three-pane macOS app. Warm paper, restrained ochre, serif for reading surfaces. Same skeleton as the engineer's SwiftUI scaffold — just dressed.</p>
            <div className="badge-row">
              <span className="badge">Light + dark</span>
              <span className="badge">Hybrid inline edit</span>
              <span className="badge">Multi-select panel</span>
              <span className="badge">FTS search</span>
              <span className="badge">Merge sheet</span>
              <span className="badge">5 empty states</span>
              <span className="badge">2 alt directions</span>
            </div>
          </div>
          <Wordmark large/>
        </div>
      </DCArtboard>
    </DCSection>

    <DCSection id="primary" title="Primary state · three-pane" subtitle="Default density, primary collection selected. Read carefully — every later artboard is a delta on this one.">
      <DCArtboard id="three-light" label="Light · 1280×800" width={1280} height={800}>
        <MockMain theme="light" active="Membrane fouling" selectedIdx={0}/>
      </DCArtboard>
      <DCArtboard id="three-dark" label="Dark · 1280×800" width={1280} height={800}>
        <MockMain theme="dark" active="Membrane fouling" selectedIdx={0}/>
      </DCArtboard>
      <DCArtboard id="three-1680" label="Light · 1680×1050" width={1680} height={1050}>
        <MockMain theme="light" active="PhD lit review" selectedIdx={3}/>
      </DCArtboard>
    </DCSection>

    <DCSection id="detail-modes" title="Detail pane · view + edit" subtitle="Hybrid model: collections + tags are always editable inline (chip + add-input). Notes have a small Edit affordance that expands a focused editor.">
      <DCArtboard id="d-view" label="View mode" width={1280} height={800}>
        <MockMain theme="light" active="Membrane fouling" selectedIdx={0}/>
      </DCArtboard>
      <DCArtboard id="d-tag-edit" label="Editing tag (popover open)" width={1280} height={800}>
        <MockMain theme="light" active="Membrane fouling" selectedIdx={0} mode="editing-tags"/>
      </DCArtboard>
      <DCArtboard id="d-notes-edit" label="Editing notes (focused)" width={1280} height={800}>
        <MockMain theme="light" active="Membrane fouling" selectedIdx={0} mode="editing-notes"/>
      </DCArtboard>
      <DCArtboard id="d-clamped" label="Long abstract · clamped" width={1280} height={800}>
        <MockMain theme="light" active="Membrane fouling" selectedIdx={0} clamped/>
      </DCArtboard>
    </DCSection>

    <DCSection id="multi" title="Multi-select · batch panel" subtitle="Detail pane transforms into a batch panel when ≥2 articles are selected. Big serif count, selection summary, and reversible actions inline.">
      <DCArtboard id="multi-7" label="7 selected" width={1280} height={800}>
        <MockMain theme="light" active="Membrane fouling" multi={[0,1,2,3,4,5,6]}/>
      </DCArtboard>
      <DCArtboard id="multi-3-dark" label="3 selected · dark" width={1280} height={800}>
        <MockMain theme="dark" active="PhD lit review" multi={[0,2,4]}/>
      </DCArtboard>
    </DCSection>

    <DCSection id="search" title="Search · live FTS" subtitle="Search field lives inline in the list header (replaces the sort control when active). Scope chip makes the filter context explicit. Matches highlighted in serif italic snippets.">
      <DCArtboard id="search-active" label="Active query · in collection" width={1280} height={800}>
        <MockMain theme="light" active="PhD lit review" selectedIdx={0} searchActive searchQuery="membrane fouling"/>
      </DCArtboard>
      <DCArtboard id="search-empty" label="No matches" width={1280} height={800}>
        <WindowFrame theme="light" width={1280} height={800}>
          <Body>
            <Sidebar active="To re-read"/>
            <div className="list-pane">
              <ListHeader collection="To re-read" count={0} searchActive searchQuery="anammox cold-climate kinetic model"/>
              <div className="list-rows"><EmptyState kind="search"/></div>
            </div>
            <div className="detail-pane"><EmptyState kind="search"/></div>
          </Body>
        </WindowFrame>
      </DCArtboard>
    </DCSection>

    <DCSection id="collections" title="Collections · write paths" subtitle="Create, rename, merge, delete. Merge needs the most care — it's destructive-ish but not undoable from the GUI.">
      <DCArtboard id="merge" label="Merge sheet" width={1280} height={800}>
        <MockMain theme="light" active="To re-read" selectedIdx={0} overlay="merge"/>
      </DCArtboard>
      <DCArtboard id="new-coll" label="New collection sheet" width={1280} height={800}>
        <MockMain theme="light" active="Membrane fouling" overlay="new-collection"/>
      </DCArtboard>
      <DCArtboard id="dragdrop" label="Drag article → collection" width={1280} height={800}>
        <MockMain theme="light" active="All articles" selectedIdx={0} dropTarget="Membrane fouling"/>
      </DCArtboard>
      <DCArtboard id="add-inline" label="Inline rename / new" width={1280} height={800}>
        <MockMain theme="light" active="Membrane fouling" showAddInline/>
      </DCArtboard>
    </DCSection>

    <DCSection id="smart" title="Smart collections · proposal" subtitle="Marked as proposal in the sidebar with a dashed treatment. Three system buckets, read-only.">
      <DCArtboard id="smart-on" label="Sidebar with smart collections" width={1280} height={800}>
        <MockMain theme="light" active="Untagged" showSmart/>
      </DCArtboard>
      <DCArtboard id="smart-note" label="Why these three" width={520} height={400}>
        <SmartProposalNote/>
      </DCArtboard>
    </DCSection>

    <DCSection id="empties" title="Empty + error states" subtitle="Quiet single-line copy with a small mark — no full illustrations. The first-launch state is the only one that uses the wordmark.">
      <DCArtboard id="e-library" label="Empty library" width={620} height={420}>
        <div style={{ height: "100%", background: "#FAF9F5", borderRadius: 8 }}><EmptyState kind="library"/></div>
      </DCArtboard>
      <DCArtboard id="e-coll" label="Empty collection" width={620} height={420}>
        <div style={{ height: "100%", background: "#FAF9F5", borderRadius: 8 }}><EmptyState kind="collection"/></div>
      </DCArtboard>
      <DCArtboard id="e-search" label="Empty search" width={620} height={420}>
        <div style={{ height: "100%", background: "#FAF9F5", borderRadius: 8 }}><EmptyState kind="search"/></div>
      </DCArtboard>
      <DCArtboard id="e-first" label="First launch" width={620} height={420}>
        <div style={{ height: "100%", background: "#FAF9F5", borderRadius: 8 }}><EmptyState kind="first-launch"/></div>
      </DCArtboard>
      <DCArtboard id="e-daemon-fs" label="Daemon-down · full window" width={1280} height={800}>
        <DaemonDown/>
      </DCArtboard>
    </DCSection>

    <DCSection id="density" title="Density · roomy vs compact" subtitle="Default is roomy. Compact toggles row padding from 12px → 7px and clamps title to one line. Toolbar toggle, not a setting.">
      <DCArtboard id="dense-roomy" label="Roomy (default)" width={620} height={620}>
        <WindowFrame theme="light" width={620} height={620}>
          <div className="win-body" style={{ gridTemplateColumns: "1fr" }}>
            <div className="list-pane">
              <ListHeader collection="Membrane fouling" count={47}/>
              <div className="list-rows">{ARTICLES.slice(0,5).map((a,i) => <Row key={a.eid} a={a} selected={i===0}/>)}</div>
            </div>
          </div>
        </WindowFrame>
      </DCArtboard>
      <DCArtboard id="dense-compact" label="Compact" width={620} height={620}>
        <WindowFrame theme="light" width={620} height={620}>
          <div className="win-body" style={{ gridTemplateColumns: "1fr" }}>
            <div className="list-pane is-compact">
              <ListHeader collection="Membrane fouling" count={47}/>
              <div className="list-rows">{ARTICLES.slice(0,8).map((a,i) => <Row key={a.eid} a={a} selected={i===0} compact/>)}</div>
            </div>
          </div>
        </WindowFrame>
      </DCArtboard>
    </DCSection>

    <DCSection id="tokens" title="Tokens · drop into Theme.swift" subtitle="Names exposed as CSS custom properties in tokens.css. Map 1:1 to a Theme.swift static enum.">
      <DCArtboard id="colors-light" label="Colors · light" width={820} height={620}>
        <ColorScale theme="light"/>
      </DCArtboard>
      <DCArtboard id="colors-dark" label="Colors · dark" width={820} height={520}>
        <ColorScale theme="dark"/>
      </DCArtboard>
      <DCArtboard id="type" label="Type scale" width={820} height={560}>
        <TypeScale/>
      </DCArtboard>
    </DCSection>

    <DCSection id="components" title="Component library" subtitle="The atoms the rest of the design composes from. Each block names its target SwiftUI view in components.css comments.">
      <DCArtboard id="atoms" label="Atoms" width={940} height={540}>
        <ComponentShelf/>
      </DCArtboard>
    </DCSection>

    <DCSection id="brand" title="Brand · icon + wordmark" subtitle="Sock as an L-silhouette glyph. Abstract enough to live in a margin; warm enough to feel literary, not corporate.">
      <DCArtboard id="icon" label="App icon · 16/32/64/128" width={820} height={400}>
        <IconProposal/>
      </DCArtboard>
    </DCSection>

    <DCSection id="copy" title="Copy pass" subtitle="Replacements for SwiftUI defaults and gaps where copy was missing.">
      <DCArtboard id="copy-table" label="Suggested strings" width={820} height={540}>
        <CopyPass/>
      </DCArtboard>
    </DCSection>

    <DCSection id="alts" title="Alt directions" subtitle="Same skeleton, different paper + accent + serif. Engineering cost: changing token values in Theme.swift. Dropped in to give the user something to react to.">
      <DCArtboard id="alt-slate" label="Slate & Saffron" width={1280} height={800}>
        <div className="theme-slate"><MockMain theme="light" active="Membrane fouling" selectedIdx={0}/></div>
      </DCArtboard>
      <DCArtboard id="alt-indigo" label="Bookcloth & Indigo" width={1280} height={800}>
        <div className="theme-indigo"><MockMain theme="light" active="PhD lit review" selectedIdx={3}/></div>
      </DCArtboard>
    </DCSection>
  </DesignCanvas>
);

ReactDOM.createRoot(document.getElementById("root")).render(<App/>);
