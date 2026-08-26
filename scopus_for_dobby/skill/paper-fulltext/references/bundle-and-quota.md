# Bundle layout, quota, and failure modes

## Quota (Article Retrieval — not Abstract Retrieval)

Ordinary API keys: **50,000 requests / 7 days**, **10 req/s**. Text-mining keys: unlimited
count, same throttle. Elsevier may deactivate keys it considers abusive.

This is a **separate** bucket from Scopus Search (20,000/week) and Scopus Abstract
Retrieval (10,000/week). Exhausting one does not touch the others.

Article Retrieval responses **do not include** `X-RateLimit-Remaining` (verified 2026-08),
so `auth quota` will not update from `fulltext` calls — `by_api.sciencedirect-article`
stays empty until Elsevier starts sending the header. A 429 still stops the batch, and the
error carries the reset time.

Batches are **sequential** — one request, then the next, with the client sleeping ~0.11 s
between calls. Concurrent fetches cannot exceed 10/s and would only trip 429s sooner.
Do not parallelize `fulltext`, and do not hang it off `search-all` or `openalex enrich`.

## What lands on disk

```
~/.scopus-for-dobby/fulltext/
  index.json          # DOI → EID, so a DOI-only refetch is a cache hit
  <eid>/
    manifest.json     # outline + relative paths — open this first
    head.md           # title, authors, affiliations, abstract, keywords
    sections/*.md     # one file per section, nested included (e.g. 02.01-…)
    references.md     # bibliography, when the XML carries one
    figures/<id>.jpg
    figures/<id>.caption.md
    tables/<id>.md
    xml/article.xml   # original Elsevier XML. Do not parse.
```

`manifest.json` keys: `eid`, `doi`, `title`, `parser` (renderer version), `head`,
`source`, `sections` (nested `{id, title, file, children}`), `figures`
(`{id, label, locator, file, caption}`), `tables`, and `references` (path or `null`).

`parser` is the renderer version, and it is the key to read defensively: those are the
keys the **current** renderer emits. A bundle left by an older one carries a lower
`parser` and simply lacks the newer keys — `manifest["references"]` raises `KeyError`
rather than returning `None`. Use `.get()`, and re-run `fulltext` (a cache hit) to bring
the bundle up to date rather than coding around the old shape.

DuckDB only ever gets `fulltext_fetched_at`. The body is never written into
`articles.abstract`, and `--json` never dumps section text.

Personal cache: do not redistribute the XML or the images. Keep TDM snippets in
user-facing output to ≤ 200 characters plus a DOI link.

## Regeneration and migration

The markdown is rebuilt when the renderer version changes, so an older bundle picks up new
output on its next `fulltext` call. Cached figures are reused, never re-downloaded — but a
figure that is *missing* is fetched during that rebuild, so regenerating an old bundle can
cost `/content/object` requests even though it costs no Article Retrieval request.

Three shapes therefore coexist on disk, and only the newest matches this document:

| What you find | What it is | What to do |
|---|---|---|
| `manifest.json` at the current `parser` | a finished bundle | read it |
| `manifest.json` at a lower `parser` | written by an older renderer; newer keys absent | re-run `fulltext`, then read |
| `xml/article.xml` and nothing else | fetched before the markdown renderer existed | re-run `fulltext`, then read |

A leftover `fulltext/<eid>.xml`, or a `source.xml` inside a paper folder, is moved into
`fulltext/<eid>/xml/article.xml` automatically.

A bundle whose XML no longer parses is discarded and refetched on the next call — never
hand-delete one to unstick a run.

## Figures

Figures come from a second Elsevier endpoint (`/content/object`), one request each, under
the same 10 req/s throttle. A figure that could not be downloaded has `file: null` in the
manifest; the caption file and the article text are still complete, and `--force` retries
it. A network failure on a figure never costs you the article you already paid for.

## When something looks wrong

**Everything comes back `not_entitled`.** The key or institution does not carry
ScienceDirect full-text rights. `auth status` shows the tier. Fall back to `oa_url` from
`openalex enrich`, and tell the user rather than scraping.

**`no_identifier`.** The saved row has neither DOI nor Scopus ID. Run `abstract <eid>` to
fill in metadata first, then retry.

**`error` with "malformed XML".** Elsevier returned a truncated or non-XML 200. Nothing was
cached, the rest of the batch ran, and re-running is safe.

**`skipped_quota` on most of a batch.** The weekly Article Retrieval budget is gone. Wait
for the reset in the error message; other commands (`search`, `abstract`, `openalex`) draw
on different budgets and still work.

**A paper is in the library but `fulltext` fetched under a different EID.** The payload
carries the authoritative Scopus EID and the bundle follows it; `index.json` maps the DOI
you asked with onto it, so the next call is a cache hit either way.
