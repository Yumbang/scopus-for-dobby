---
name: paper-fulltext
description: "Fetch and read the BODY of a paper — one named paper, or every paper in a saved collection: the article text itself, not its metadata — using scopus-for-dobby's `fulltext` command, which calls Elsevier Article Retrieval and writes a local markdown bundle (sections, figures, tables, references, LaTeX math). Use whenever answering depends on what a paper actually says or did: methods and experimental setup, a verbatim quote, a specific reported number, an equation, what a figure or table shows, 'what did they actually claim/do', 'read this paper', 'download the full text', 'get me the article/전문', or verifying a claim against its source. Also use BEFORE fetching, to decide whether the body is warranted and whether to ask the user first — it costs metered quota. NOT for finding, searching, listing, tagging or exporting papers, and not for abstracts or metadata — that is the scopus-for-dobby skill. NOT for locating a free open-access PDF link, which costs nothing and is also scopus-for-dobby — this skill spends metered Elsevier quota, so reach for it only when the publisher's own text is what the answer needs. NOT for citation structure, gaps or seminal works (citation-analysis). NOT for topic statistics over a large set (corpus-profiling) — screening many papers needs abstracts, not bodies."
---

# paper-fulltext — the article, not the abstract

`fulltext` calls Elsevier **Article Retrieval** (`GET /content/article/...`) and writes a
bundle directory per paper under `~/.scopus-for-dobby/fulltext/<eid>/`. It stamps
`fulltext_fetched_at` on the library row; the body is never written into the database.

Requires the `scopus-for-dobby` CLI and a configured Scopus API key (`auth setup`).
For finding the papers in the first place, see the **scopus-for-dobby** skill.

## Do you need the body?

Ask what the answer actually rests on. Most literature work does not need the body.

| The question is… | Use |
|---|---|
| Does this paper exist / who wrote it / when | `search`, `db list` — no fetch |
| What is this paper roughly about | the abstract (`abstract --view FULL`) |
| What are these 200 papers about | `profile` — **corpus-profiling** skill |
| What did this field build on, what did I miss | **citation-analysis** skill |
| **What method / setup / protocol did they use** | **`fulltext`** |
| **What exact number / equation / figure did they report** | **`fulltext`** |
| **Quote them, or check a claim against the source** | **`fulltext`** |

`abstract --view FULL` is Scopus **Abstract Retrieval** — abstract text, author list,
correspondence *names*. It is not the article body. `openalex enrich` writes OA links and
topics; it downloads nothing.

Do **not** scrape ScienceDirect HTML. The site's robots.txt defaults to `Disallow: /`
(including `claude-code`); Elsevier ToS and the TDM licence require the API.

## Ask first, or just fetch?

Fetching spends metered quota and can miss on entitlement, so the default is not "always".

**Ask the user first** when:

- Several papers, or a whole collection, would be fetched
- It is still a search/screening step and you only *might* need the body
- Entitlement is uncertain and a miss would change the plan

Name the EIDs/DOIs and say why the body is required. Do not fetch a hit list "just in case".

**Fetch without asking** when:

- The bundle already exists locally — that is a cache read, not an API call
- The user named a specific paper (or 1–5 they already chose) and the question needs the body
- They already said to download / read the article / look at the methods or figures
- You are continuing on a paper they approved this turn

A large approved collection belongs in a subagent; the main context keeps only the
`--json` summary, never the raw bodies.

## Fetch

Cache-first, including for a paper that is **not** in the local library — a repeated
`fulltext <doi>` is a cache hit, not another API call. `--force` refetches.

```bash
scopus-for-dobby fulltext 10.1016/j.watres.2026.125855   # DOI
scopus-for-dobby fulltext 2-s2.0-105035063878            # Scopus EID
scopus-for-dobby fulltext --indices 1,3                  # from the last search/list
scopus-for-dobby fulltext --collection thesis-refs       # a saved collection
scopus-for-dobby fulltext --tag review --limit 20
scopus-for-dobby fulltext --query "closed-circuit reverse osmosis"
scopus-for-dobby fulltext 2-s2.0-aaa 2-s2.0-bbb          # several; duplicates collapse

# pipeline from db list:
scopus-for-dobby --json db list -c thesis-refs -n 1000 \
  | jq -r '.articles[].eid' \
  | scopus-for-dobby fulltext --eids-from-stdin
```

`fulltext` is a subcommand, not a binary — inside the interactive REPL you drop the
`scopus-for-dobby` prefix, but every example here is written to run in a shell as-is.

Identifiers: DOI, Scopus EID (`2-s2.0-...`), or Scopus ID. Pipelines (`--collection` /
`--tag` / `--query`) resolve saved rows, and mix freely with explicit identifiers in one
invocation. When `--limit` truncates a mixed batch, the identifiers you named explicitly
are kept and pipeline rows are dropped.

`--json` (global flag, **before** the subcommand) returns counts plus per-item
`{eid, doi, status, path, reason, in_db, oa_url, outline}`. `path` is the bundle
directory. It never dumps XML or section text.

## Read the bundle

**Run `fulltext` on the paper before reading it, even when you believe it is already
cached.** A cache hit spends no Article Retrieval request, it prints the bundle path,
and it rebuilds anything a newer renderer would write differently. Reading a directory
you found by hand is how you end up parsing a shape that no longer exists.

Then open `manifest.json`, and only the files you need. **Never parse
`xml/article.xml`** — it is the regenerate-from original, and the markdown already
carries everything.

Not every directory under `fulltext/` is a finished bundle. One written by an older
version may have **no `manifest.json` at all** (just `xml/article.xml`), or a manifest
missing keys this document describes — `references` is absent, not `null`, in anything
written before it existed. Treat a missing key as "older bundle, regenerate", never as
"this paper has no bibliography". Running `fulltext` fixes both cases.

```
~/.scopus-for-dobby/fulltext/<eid>/
  manifest.json          # outline + relative paths — open this first
  head.md                # title, authors, affiliations, abstract, keywords
  sections/*.md          # one file per section, nested included (02.01-…)
  references.md          # bibliography, when the XML carries one
  figures/<id>.jpg
  figures/<id>.caption.md
  tables/<id>.md
  xml/article.xml        # original Elsevier XML — do not parse
```

`manifest.sections` is a nested outline: each node has `title`, `file`, and `children`.
A parent section's `.md` holds only its own paragraphs — subsection text lives in the
child files.

Cross-references keep their target: `[Fig. 1](#fig0001)`, `[65](#bb0325)`. That link is
often the only thing tying a claim to what it cites — numeric citation styles render as a
bare number otherwise — so use it to jump to `references.md` or a figure caption, and to
answer "where does this paper cite X". A link carrying several ids lists the rest in its
title attribute.

Tables in `tables/*.md` are rectangular: every row has the same number of columns and each
value sits under its own header, with a row-spanning label repeated down the rows it covers
rather than left blank. Read them as data — no cell inherits meaning from a row above. Math is LaTeX (`$…$` inline, `$$…$$` display, `\tag{n}` for numbered
equations). Numbered protocol steps survive as markdown list items.

Do not call the API again for the same EID unless `--force`.

## Batch failures are per item

Closed papers, non-Elsevier papers, missing DOIs, malformed payloads, and network errors
on a single item do **not** abort the batch. Every item lands in exactly one `status`;
the run always reaches the last one.

| `status` | Meaning |
|---|---|
| `fetched` | API 200, bundle written |
| `cached` | local bundle reused — no API call |
| `not_entitled` | HTTP 401/403, or a 200 carrying only the abstract. Subscription miss |
| `not_found` | HTTP 404 — not an Elsevier article, or unknown id |
| `no_identifier` | the saved row has no DOI / Scopus ID to retrieve against |
| `error` | other HTTP failure, or a 200 whose XML will not parse (nothing cached — retrying is safe) |
| `skipped_quota` | weekly Article Retrieval quota hit; **remaining items skipped** |

On `not_entitled`, any `oa_url` that `openalex enrich` already stored is echoed so you can
point the user at the open-access copy. Do not scrape the publisher's HTML instead.

A 429 stops the rest of the batch. Wait for the reset rather than retrying.

## Quota and etiquette — read before a batch

Ordinary keys get **50,000 Article Retrieval requests / 7 days** at **10 req/s**, a
budget entirely separate from Scopus Search and Abstract Retrieval. Batches are
**sequential by design**; do not parallelize them.

This is a personal cache: do not redistribute the XML or images, and keep TDM snippets in
user-facing output to ≤ 200 characters plus a DOI link.

`references/bundle-and-quota.md` — the quota model in full, the on-disk layout and how it
migrates, figure downloads, and what to do when a fetch misbehaves.
