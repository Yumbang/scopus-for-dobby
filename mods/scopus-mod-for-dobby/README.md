# scopus-mod-for-dobby

A Claude Code mod: the `/scopus-mod` side pane for browsing a scopus-for-dobby
library, attaching papers to the chat, and letting the agent steer the same scope
and selection through three tools (`papers_state`, `papers_scope`, `papers_select`).

```text
/plugin install scopus-mod-for-dobby --marketplace Yumbang/scopus-for-dobby
```

It needs the scopus-for-dobby daemon (`uv tool install --editable ".[gui]"`, then
`scopus-for-dobby serve --background`). Full description, controls and the security
notes are in the [repository README](../../README.md#claude-code-mod-the-scopus-mod-pane).

Develop: `claude --plugin-dir mods/scopus-mod-for-dobby`; test: `claude plugin test mods/scopus-mod-for-dobby`.
