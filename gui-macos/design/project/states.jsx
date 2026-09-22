// states.jsx — batch panel, sheets, empty states, daemon-down

const BatchPanel = ({ count = 7 }) => {
  const { ARTICLES } = window.SCOPUS_DATA;
  const sample = ARTICLES.slice(0, count);
  return (
    <div className="detail-pane batch-pane">
      <div className="batch-head">
        <div className="batch-count">{count}<span className="label">articles selected</span></div>
        <div className="batch-summary">Across {new Set(sample.flatMap(a => a.collections || [])).size} collections · {new Set(sample.flatMap(a => a.tags || [])).size} unique tags · {sample.reduce((s, a) => s + (a.cited || 0), 0)} total citations</div>
      </div>

      <div className="batch-section">
        <div className="batch-section-head">Selection</div>
        <div className="batch-thumb-list">
          {sample.map((a, i) => (
            <div key={a.eid} className="batch-thumb">
              <span className="num">{String(i+1).padStart(2,"0")}</span>
              <span className="t">{a.title}</span>
              <span style={{ color: "var(--ink-mute)" }}>{a.year}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="batch-section">
        <div className="batch-section-head">Apply to all</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <button className="batch-action"><Icon name="tag"/><span>Apply tag…</span><span className="meta">⌘T</span></button>
          <button className="batch-action"><Icon name="folder"/><span>Add to collection…</span><span className="meta">⌘⇧M</span></button>
          <button className="batch-action"><Icon name="copy"/><span>Copy citations as BibTeX</span></button>
          <button className="batch-action is-danger"><Icon name="minus"/><span>Remove from "Membrane fouling"</span></button>
        </div>
      </div>

      <div className="batch-section" style={{ marginTop: "auto", color: "var(--ink-mute)", fontSize: "var(--t-meta)" }}>
        <span>⌘A select all · Esc clear · ⇧↑↓ extend</span>
      </div>
    </div>
  );
};

const MergeSheet = () => (
  <div className="sheet-shade">
    <div className="sheet">
      <div className="sheet-head">
        <div className="eyebrow">Merge collections</div>
        <div className="title">Merge "To re-read" into "PhD lit review"?</div>
        <div className="subtitle">All 5 articles will move into "PhD lit review". The "To re-read" collection will be deleted. Article tags and notes are preserved.</div>
      </div>
      <div className="sheet-body">
        <div className="merge-preview">
          <div className="col is-deleted" style={{ flex: 1 }}>
            <div className="name"><Icon name="folder" size={12}/>To re-read</div>
            <div className="meta">5 articles · created Mar 12</div>
          </div>
          <div className="arrow"><Icon name="arrow-right" size={16}/></div>
          <div className="col" style={{ flex: 1 }}>
            <div className="name"><Icon name="folder-fill" size={12} style={{ color: "var(--accent-deep)" }}/>PhD lit review</div>
            <div className="meta">102 → 107 articles</div>
          </div>
        </div>
        <div className="callout-warn">
          <Icon name="warn" size={14}/>
          <div><strong>This can't be undone from the GUI.</strong> The CLI keeps an event log; you can replay it with <code style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}>scopus-for-dobby events --since</code>.</div>
        </div>
      </div>
      <div className="sheet-foot">
        <button className="btn">Cancel</button>
        <div className="spacer"/>
        <button className="btn btn-primary"><Icon name="merge" size={12}/>Merge & delete source</button>
      </div>
    </div>
  </div>
);

const NewCollectionSheet = () => (
  <div className="sheet-shade">
    <div className="sheet" style={{ width: 420 }}>
      <div className="sheet-head">
        <div className="eyebrow">New collection</div>
        <div className="title">Name your collection</div>
        <div className="subtitle">Collections are buckets for articles. An article can live in many. Names can include any language.</div>
      </div>
      <div className="sheet-body">
        <div>
          <div className="field-label">Name</div>
          <div className="field-input" style={{ borderColor: "var(--accent)", boxShadow: "0 0 0 3px color-mix(in oklab, var(--accent) 18%, transparent)" }}>
            Membrane fouling — chapter 3<span style={{ borderLeft: "1.5px solid var(--accent)", marginLeft: 1 }}/>
          </div>
          <div className="field-help">Tip: keep it short. You can rename later.</div>
        </div>
      </div>
      <div className="sheet-foot">
        <button className="btn">Cancel</button>
        <div className="spacer"/>
        <button className="btn btn-primary"><Icon name="check" size={12}/>Create</button>
      </div>
    </div>
  </div>
);

const EmptyState = ({ kind }) => {
  const map = {
    library: { icon: "tray", head: "Your library is empty.", sub: "Run a search from the CLI — articles you collect there will appear here.", code: "scopus-for-dobby search \"membrane fouling\"" },
    collection: { icon: "folder", head: "Nothing in this collection yet.", sub: "Drag articles here from any list, or use Add to collection from a selection." },
    search: { icon: "search", head: "No matches.", sub: "Searched titles, abstracts, keywords, and notes. Try a broader term, or clear the collection filter." },
    "first-launch": { icon: "sparkle", head: "A quiet place for your reading.", sub: "When the daemon catches up to the database, your articles will appear in the middle pane.", brand: true },
    daemon: { icon: "bolt-slash", head: "The daemon is asleep.", sub: "scopus-for-dobby's local server isn't responding on :8765. Start it from a terminal, or click Retry below.", code: "scopus-for-dobby daemon start", action: "Retry" },
  };
  const e = map[kind];
  return (
    <div className="empty">
      {e.brand
        ? <Wordmark large/>
        : <Icon name={e.icon} size={28} className="mark" style={{ color: "var(--ink-mute)" }}/>}
      <div className="head">{e.head}</div>
      <div className="sub">{e.sub}</div>
      {e.code && (
        <div style={{ marginTop: 10, padding: "8px 14px", background: "var(--paper-deep)", border: "1px solid var(--paper-edge)", borderRadius: 6, fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--ink-soft)" }}>
          {e.code}
        </div>
      )}
      {e.action && (
        <button className="btn btn-primary" style={{ marginTop: 8 }}>{e.action}</button>
      )}
    </div>
  );
};

const Wordmark = ({ large = false }) => (
  <div className="wordmark" style={large ? { fontSize: 22, gap: 9 } : {}}>
    <SockGlyph size={large ? 22 : 14}/>
    <span>scopus</span>
    <span className="for">for</span>
    <span>dobby</span>
  </div>
);

// Sock motif — abstract, literary. Single stroke, hint of the form.
const SockGlyph = ({ size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" style={{ color: "var(--accent)" }}>
    {/* a sock as a simple "L" silhouette: leg ─ heel ─ foot */}
    <path d="M9 4h5a1 1 0 0 1 1 1v9c0 .5.2 1 .6 1.4l3.5 3.5a1.6 1.6 0 0 1-2.3 2.3l-5-5A2 2 0 0 1 11 14.6V8H9a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z"/>
    {/* cuff stitching */}
    <path d="M9 7h6" opacity="0.6"/>
  </svg>
);

window.States = { BatchPanel, MergeSheet, NewCollectionSheet, EmptyState, Wordmark, SockGlyph };
