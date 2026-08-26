# Elsevier full text

When you need the **body** of a paper (methods, a quote, a figure caption), use `fulltext`, not `abstract` and not `openalex enrich`.

- `abstract --view FULL` is Scopus **Abstract Retrieval**: abstract text, author list, correspondence *names*. It is not the article body.
- `openalex enrich` writes OA links and topics. It does not download PDFs or XML.
- `fulltext` calls Elsevier **Article Retrieval** (`GET /content/article/...`) and writes a **bundle directory** under `~/.scopus-for-dobby/fulltext/<eid>/`. It stamps `fulltext_fetched_at` on the library row.

Do **not** scrape ScienceDirect HTML. The site's robots.txt defaults to `Disallow: /` (including `claude-code`). Elsevier ToS and the TDM licence require the API.

## Fetch

Cache-first. `--force` refetches.

```bash
fulltext 10.1016/j.watres.2026.125855
fulltext 2-s2.0-105035063878
fulltext --indices 1,3
fulltext --collection thesis-refs
fulltext --tag review --limit 20
fulltext --query "closed-circuit reverse osmosis"
fulltext 2-s2.0-aaa 2-s2.0-bbb
# pipeline from db list:
scopus-for-dobby --json db list -c thesis-refs -n 1000 \
  | jq -r '.articles[].eid' \
  | scopus-for-dobby fulltext --eids-from-stdin
```

Identifiers: DOI, Scopus EID (`2-s2.0-...`), or Scopus ID. DuckDB pipelines (`--collection` / `--tag` / `--query`) resolve saved rows. Direct EIDs/DOIs work even when mixed into the same invocation; duplicates collapse.

`--json` (global flag, before the subcommand) returns counts plus per-item `{eid, doi, status, path, reason, oa_url, outline}`. `path` is the bundle directory. It does **not** dump XML or section text.

After a successful fetch, **do not parse `xml/article.xml`**. Open `manifest.json`, then only the files you need (`head.md`, `sections/*.md`, `figures/*.caption.md`, `tables/*.md`). Do not call the API again for the same EID unless `--force`.

## Batch failures are per item

Closed papers, non-Elsevier papers, and missing DOIs do **not** abort the batch.

| `status` | Meaning |
|---|---|
| `fetched` | API 200, XML written |
| `cached` | local XML reused |
| `not_entitled` | HTTP 401/403, or 200 with abstract-only payload. Subscription/entitlement miss |
| `not_found` | HTTP 404 — not an Elsevier article, or unknown id |
| `no_identifier` | saved row has no DOI / Scopus ID |
| `error` | other HTTP failure |
| `skipped_quota` | weekly Article Retrieval quota hit; **remaining items skipped** |

On `not_entitled`, if `openalex enrich` already stored `oa_url`, it is echoed so you can try the OA copy. Do not scrape the publisher HTML.

A 429 stops the rest of the batch (`skipped_quota`). Wait for the reset, or check `auth quota` (`by_api.sciencedirect-article` is this budget, **not** Scopus abstract).

## Quota (Article Retrieval, not Abstract Retrieval)

Ordinary API keys: **50,000 requests / 7 days**, **10 req/s**. Text-mining keys: unlimited count, same throttle. Elsevier may deactivate abusive keys.

Article Retrieval responses **do not include** `X-RateLimit-Remaining` (verified 2026-08). `auth quota` / `by_api.sciencedirect-article` will not update from `fulltext` calls. A 429 still stops the batch.

Batches are **sequential** — one request, then the next, with the client sleeping ~0.11s between calls. Concurrent fetches cannot go faster than 10/s and would only trip 429s earlier. Do not parallelize `fulltext`.

This is a **separate** bucket from Scopus Search (20,000/week) and Scopus Abstract Retrieval (10,000/week). `auth quota` without `by_api` is whatever ran last.

## What is stored

```
~/.scopus-for-dobby/fulltext/<eid>/
  manifest.json       # outline + relative paths — open this first
  head.md             # title, authors, affiliations, abstract, keywords
  sections/*.md       # one file per section, including nested (e.g. 02.01-…). Math is LaTeX (`$…$` / `$$…$$`).
  figures/<id>.jpg
  figures/<id>.caption.md
  tables/<id>.md
  xml/article.xml     # original Elsevier XML. Do not parse.
```

Personal cache; do not redistribute the XML or images. TDM snippets in user-facing output stay ≤ 200 characters plus a DOI link.

DuckDB only gets `fulltext_fetched_at`. The body is never written into `articles.abstract`.

A leftover `fulltext/<eid>.xml` (or `source.xml` in the paper folder) is moved into `fulltext/<eid>/xml/article.xml` on the next `fulltext` call.

## When to use it (agents)

Trigger on **need for the body**, not only on the words "full text" / "전문". Abstracts, `profile`, and citation graphs are enough for screening, themes, and "what exists". Switch to `fulltext` when the answer depends on methods, a quote, a figure, an equation, or a specific claim.

**Ask the user first** when:

- Several papers or a whole collection would be fetched
- It is still a search/screening step and you only *might* need the body
- Entitlement is uncertain and a miss would change the plan

Name the EIDs/DOIs and why the body is required. Do not fetch a search hit list "just in case".

**Do it without asking** when:

- The local bundle already exists (cache — no API)
- The user named a specific paper (or 1–5 they already chose) and the question needs the body
- They already told you to download / read the article / look at methods or figures
- You are continuing on a paper they already approved this turn

Then open `manifest.json` and only the section files you need — not `xml/article.xml`. A large approved collection belongs in a subagent; the main context keeps the JSON summary.

Do not hang `fulltext` off `search-all` or `openalex enrich`. Do not fetch every new search hit.
