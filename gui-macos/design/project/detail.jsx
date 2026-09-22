// detail.jsx — article detail pane (view mode + hybrid inline-edit affordances)
const Detail = ({ a, mode = "view", clamped = false }) => {
  // mode: 'view' (default), 'editing-tags', 'editing-notes', 'fresh' (no notes)
  const cols = a.collections || [];
  const tags = a.tags || [];

  return (
    <div className="detail-pane">
      <div className="detail-header">
        <div className="breadcrumb">
          <Icon name="folder-fill" size={11} style={{ color: "var(--ink-mute)" }}/>
          <span>{cols[0] || "All articles"}</span>
        </div>
        <div className="spacer"/>
        <div className="actions">
          <button className="btn btn-sm btn-ghost"><Icon name="link" size={12}/><span>Open in Scopus</span></button>
          <button className="btn btn-sm btn-ghost"><Icon name="copy" size={12}/><span>Copy citation</span></button>
        </div>
      </div>

      <div className="detail-scroll">
        <h1 className="detail-title">{a.title}</h1>

        <div className="detail-byline">
          {(a.authors && a.authors.length > 1) ? (
            <>
              <span>{a.authors.slice(0, 2).join(", ")}</span>
              <span className="more-authors">+{a.authors.length - 2} more</span>
            </>
          ) : <span>{a.firstAuthor}</span>}
          <span className="sep">·</span>
          <span className="journal">{a.journal}</span>
          <span className="sep">·</span>
          <span>{a.coverDate || a.year}</span>
        </div>

        <div className="detail-stats">
          {a.cited > 0 && <span className="stat"><Icon name="quote" size={12}/>Cited by {a.cited}</span>}
          {a.doi && <span className="stat"><Icon name="link" size={12}/><a href={`https://doi.org/${a.doi}`}>{a.doi}</a></span>}
          <span className="stat" style={{ marginLeft: "auto", color: "var(--ink-mute)" }}>{a.addedAt}</span>
        </div>

        {/* Collections */}
        <div className="detail-section">
          <div className="detail-section-head"><span>In collections</span></div>
          <div className="chip-row">
            {cols.map(c => (
              <span key={c} className="chip is-collection is-removable">
                <Icon name="folder" size={11}/>{c}
                <span className="x"><Icon name="x" size={10}/></span>
              </span>
            ))}
            <span className="chip-input"><Icon name="plus" size={10}/>Add to collection</span>
          </div>
        </div>

        {a.abstract && (
          <div className="detail-section">
            <div className="detail-section-head"><span>Abstract</span></div>
            <div className={`detail-abstract ${clamped ? "is-clamped" : ""}`}>{a.abstract}</div>
            {clamped && <div className="read-more">Read more</div>}
          </div>
        )}

        {a.keywords && (
          <div className="detail-section">
            <div className="detail-section-head"><span>Keywords</span></div>
            <div style={{ fontSize: "var(--t-meta)", color: "var(--ink-soft)", lineHeight: 1.6 }}>{a.keywords}</div>
          </div>
        )}

        {/* Tags — hybrid: chips + inline + suggestions */}
        <div className="detail-section" style={{ position: "relative" }}>
          <div className="detail-section-head"><span>Tags</span></div>
          <div className="chip-row">
            {tags.map(t => (
              <span key={t} className="chip is-removable">{t}<span className="x"><Icon name="x" size={10}/></span></span>
            ))}
            {mode === "editing-tags" ? (
              <span className="chip-input is-typing">
                <Icon name="plus" size={10}/>memb<span style={{ borderLeft: "1.5px solid var(--accent)", height: 11, marginLeft: 1 }}/>
              </span>
            ) : (
              <span className="chip-input"><Icon name="plus" size={10}/>Add tag</span>
            )}
          </div>
          {mode === "editing-tags" && (
            <div className="tag-popover" style={{ left: 0, top: 70, marginTop: 6 }}>
              <div className="header">Existing tags</div>
              <div className="item is-focus"><Icon name="tag" size={11}/><span>membrane-fouling</span><span className="count">22</span></div>
              <div className="item"><Icon name="tag" size={11}/><span>membrane-bioreactor</span><span className="count">11</span></div>
              <div className="item is-new"><Icon name="plus" size={11}/><span>Create tag "memb"</span></div>
            </div>
          )}
        </div>

        {/* Notes — collapsed view by default, expand for editor */}
        <div className="detail-section">
          <div className="detail-section-head">
            <span>Notes</span>
            <button className="edit-btn">{a.notes ? "Edit" : "Add note"}</button>
          </div>
          {mode === "editing-notes" ? (
            <div style={{ border: "1.5px solid var(--accent)", borderRadius: 6, padding: 12, background: "var(--paper)" }}>
              <div className="notes-text">{a.notes || "Compare to Lin et al. 2022."}<span style={{ borderLeft: "1.5px solid var(--accent)", marginLeft: 1 }}>&nbsp;</span></div>
              <div style={{ display: "flex", gap: 8, marginTop: 12, fontSize: 11, color: "var(--ink-mute)" }}>
                <span>⌘↩ Save</span><span>·</span><span>Esc Discard</span>
                <span style={{ marginLeft: "auto" }}>Plain text · Markdown rendered on read</span>
              </div>
            </div>
          ) : a.notes ? (
            <div className="notes-text">{a.notes}</div>
          ) : (
            <div className="notes-empty">Write a note about this article…</div>
          )}
        </div>
      </div>
    </div>
  );
};

window.Detail = Detail;
