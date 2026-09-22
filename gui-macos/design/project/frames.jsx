// frames.jsx — small shared building blocks: window chrome, sidebar, list, detail header.
const { useState } = React;

const WindowFrame = ({ title = "scopus-for-dobby", children, theme = "light", width = 1280, height = 800, withToolbar = false }) => (
  <div className={`app-frame theme-${theme}`} style={{ width, height }}>
    <div className="win" style={{ height: "100%" }}>
      <div className="win-bar">
        <div className="win-lights"><span className="l-r"/><span className="l-y"/><span className="l-g"/></div>
        <div className="win-title">{title}</div>
        <div className="win-tools">
          <Icon name="search" size={13}/>
          <Icon name="sort" size={13}/>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateRows: withToolbar ? "auto 1fr" : "1fr", minHeight: 0 }}>
        {children}
      </div>
    </div>
  </div>
);

// ── Sidebar ─────────────────────────────────────────────
const Sidebar = ({ active = "Membrane fouling", showSmart = false, dropTarget = null, daemonState = "running", showAddInline = false }) => {
  const { COLLECTIONS, SMART, USER_COLS } = window.SCOPUS_DATA;
  return (
    <div className="sidebar">
      <div className="sidebar-section">
        <div className="sidebar-section-title">Library</div>
        {COLLECTIONS.map(c => (
          <div key={c.name} className={`sidebar-row ${active === c.name ? "is-active" : ""}`}>
            <Icon name={c.icon}/><span>{c.name}</span><span className="count">{c.count.toLocaleString()}</span>
          </div>
        ))}
      </div>

      {showSmart && (
        <div className="sidebar-section">
          <div className="sidebar-section-title">Smart <span style={{ color: "var(--accent-deep)", fontStyle: "italic", textTransform: "none", letterSpacing: 0, fontWeight: 400 }}>· proposed</span></div>
          {SMART.map(c => (
            <div key={c.name} className={`sidebar-row is-smart ${active === c.name ? "is-active" : ""}`}>
              <Icon name={c.icon}/><span>{c.name}</span><span className="count">{c.count}</span>
            </div>
          ))}
        </div>
      )}

      <div className="sidebar-section">
        <div className="sidebar-section-title" style={{ display: "flex", alignItems: "center" }}>
          <span>Collections</span>
          <span style={{ marginLeft: "auto", color: "var(--ink-mute)", textTransform: "none", letterSpacing: 0, fontWeight: 400, display: "inline-flex", alignItems: "center", gap: 2 }}>
            <Icon name="plus" size={12}/>
          </span>
        </div>
        {USER_COLS.map(c => (
          <div key={c.name}
               className={`sidebar-row ${active === c.name ? "is-active" : ""} ${dropTarget === c.name ? "is-droptarget" : ""} ${c.count === 0 ? "is-empty" : ""}`}>
            <Icon name="folder"/><span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.name}</span><span className="count">{c.count}</span>
          </div>
        ))}
        {showAddInline && (
          <div className="sidebar-row" style={{ background: "var(--paper)", boxShadow: "inset 0 0 0 1.5px var(--accent)" }}>
            <Icon name="folder"/>
            <span style={{ color: "var(--ink)" }}>New collection<span style={{ borderLeft: "1.5px solid var(--accent)", marginLeft: 1, opacity: 0.9 }}>&nbsp;</span></span>
          </div>
        )}
      </div>

      <div className="sidebar-foot">
        <span className={`daemon-dot ${daemonState === "down" ? "is-down" : ""}`}/>
        {daemonState === "running" ? <span>Daemon · live</span> : <span>Daemon · offline</span>}
        <span style={{ marginLeft: "auto", fontVariantNumeric: "tabular-nums", opacity: 0.7 }}>:8765</span>
      </div>
    </div>
  );
};

// ── Article row ─────────────────────────────────────────
const Row = ({ a, selected = false, multi = false, snippet = null, compact = false }) => (
  <div className={`row ${selected ? "is-selected" : ""} ${multi ? "is-multi-selected" : ""}`}>
    <div className="row-title">{a.title}</div>
    <div className="row-meta">
      <span>{a.firstAuthor}{a.authors && a.authors.length > 1 ? " et al." : ""}</span>
      <span className="sep">·</span>
      <span className="journal">{a.journal}</span>
      <span className="sep">·</span>
      <span>{a.year}</span>
      <span className="right">
        {a.isNew && <span className="new-dot" title="Added in last 24h"/>}
        {a.cited > 0 && <><Icon name="quote" size={11}/><span>{a.cited}</span></>}
      </span>
    </div>
    {snippet && <div className="row-snippet" dangerouslySetInnerHTML={{ __html: snippet }}/>}
  </div>
);

// ── List header ─────────────────────────────────────────
const ListHeader = ({ collection, count, sort = "Added", searchActive = false, searchQuery = "" }) => (
  <div className="list-header">
    <div className="crumb">
      <Icon name={collection === "All articles" ? "tray" : "folder-fill"} size={14} style={{ color: "var(--accent-deep)" }}/>
      <span>{collection}</span>
      <span className="crumb-count">· {count.toLocaleString()}</span>
    </div>
    <div className="spacer"/>
    {searchActive ? (
      <div className="search-field is-active" style={{ width: 240 }}>
        <Icon name="search" size={12}/>
        <span>{searchQuery}</span>
        <span style={{ borderLeft: "1.5px solid var(--accent)", height: 12, marginLeft: -2 }}/>
        <span className="scope">in {collection}</span>
      </div>
    ) : (
      <div className="list-tool"><Icon name="sort" size={12}/><span>{sort}</span><Icon name="chevron-d" size={10}/></div>
    )}
  </div>
);

window.Frames = { WindowFrame, Sidebar, Row, ListHeader };
