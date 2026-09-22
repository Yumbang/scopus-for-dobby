# ScopusForDobby — macOS GUI

Native SwiftUI viewer for the local article database. Reads/writes via
the HTTP daemon at `http://127.0.0.1:<port>` (lazy-spawned by the CLI;
see ADR-7 in `.omc/plans/gui-implementation-plan.md`).

## Bootstrap

```bash
brew install xcodegen          # one-time
cd gui-macos
xcodegen generate              # produces ScopusForDobby.xcodeproj from project.yml
open ScopusForDobby.xcodeproj  # or build from CLI: xcodebuild -project ScopusForDobby.xcodeproj
```

The `.xcodeproj` is gitignored — regenerate after editing `project.yml`.

## Run requirements

The Python side must be installed **with the `gui` extra**, which is what
provides the daemon server (`fastapi`, `uvicorn`):

```bash
uv tool install --reinstall --editable ".[gui]"
```

Then the daemon must be running. Either:

- let the app start it — the daemon-down empty state has a "Launch daemon"
  button backed by `DaemonLauncher.swift` (`serve --background`), or
- run it explicitly: `scopus-for-dobby serve` in another terminal.

Note that plain CLI subcommands do **not** start a daemon: the CLI opens
DuckDB in-process unless one is already listening. So `scopus-for-dobby db
stats` will not bring the GUI to life — use one of the two options above.

The app reads `~/.scopus-for-dobby/daemon.port` to discover the URL. If
that file is missing it shows a "daemon not running" placeholder.

## Layout

```
Sources/
  ScopusForDobbyApp.swift      # @main entry point
  AppState.swift               # ObservableObject driving the UI
  HTTP/
    DaemonClient.swift         # URLSession wrapper around the daemon
  Models/
    Article.swift              # mirrors core/article_db.py schema
    CollectionInfo.swift
    EventModel.swift
  Views/
    ContentView.swift          # NavigationSplitView root
    CollectionsSidebar.swift
    ArticleListView.swift
    ArticleDetailView.swift
Resources/
  ScopusForDobby.entitlements  # sandbox OFF (dev build)
```

## Schema contract

Models in `Sources/Models/` are hand-mirrored from the DuckDB schema in
`scopus_for_dobby/core/article_db.py`. The Python-side test
`tests/test_schema_fingerprint.py` is the tripwire — bumping the schema
requires updating both the fingerprint and the Swift structs in the
same commit.
