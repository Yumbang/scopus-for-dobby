# Searching Scopus & Retrieving Abstracts

## Two Tiers

| Feature | Free (API key only) | Institutional (+ inst token) |
|---|---|---|
| Search view | STANDARD | COMPLETE |
| Abstract retrieval | META (no abstract text) | FULL (abstract, all authors, keywords) |
| Author list in search results | First author only | All authors with AUIDs |
| Rate limit | Same | Same |

Check the current tier with `auth status`. Upgrade/downgrade with `auth upgrade --inst-token ...` / `auth downgrade`.

## Search

Results are **auto-saved to the local DB** by default — use `--no-save` for throwaway queries so you don't pollute the library.

```bash
# Simple keywords (auto-wrapped in TITLE-ABS-KEY())
search deep learning image segmentation

# Field-code queries (detected → NOT auto-wrapped)
search "AUTH(Kim) AND AFFIL(Seoul National University)"
search "DOI(10.1016/j.example.2024)"
search "AU-ID(55666793600)"

# Filters
search transformer --year 2022-2024 --subject COMP
search "renewable energy" --sort citedby-count --limit 25

# Tag and collect at save time
search machine learning --tag ml --collection thesis

# Paginated fetch (multiple API calls, counts against quota per page)
search-all "machine learning" --max 200 --sort -pubyear
```

`search --limit` is capped at 25 — that is one API page. For anything larger use `search-all --max N`, which pages through the API; `--max` is the uncapped total (each page is one API call against quota).

Options (both commands): `-s/--sort`, `-y/--year` (`2024` or `2020-2024`), `--subject` (COMP, MEDI, PHYS, ENGI, ...), `-t/--tag`, `-c/--collection`, `--no-save`.

### Scopus Field Codes

These go directly in the query string; when detected, the CLI skips the TITLE-ABS-KEY() wrapper:

| Code | Meaning | Example |
|---|---|---|
| `TITLE-ABS-KEY()` | Title, abstract, keywords | `TITLE-ABS-KEY(deep learning)` |
| `TITLE()` | Title only | `TITLE(transformer architecture)` |
| `AUTH()` | Author name | `AUTH(Smith J.)` |
| `FIRSTAUTH()` | First author | `FIRSTAUTH(Kim)` |
| `AU-ID()` | Author ID | `AU-ID(55666793600)` |
| `AFFIL()` | Affiliation | `AFFIL(MIT)` |
| `DOI()` | DOI | `DOI(10.1016/...)` |
| `PUBYEAR()` | Publication year | `PUBYEAR(2024)`, also `PUBYEAR > 2020` |
| `SRCTITLE()` | Source/journal title | `SRCTITLE(Nature)` |
| `KEY()` | Author keywords | `KEY(neural network)` |
| `FUND-SPONSOR()` | Funding sponsor | `FUND-SPONSOR(NSF)` |

Combine with `AND`, `OR`, `AND NOT`:

```bash
search "AUTH(Kim) AND AFFIL(Seoul National) AND PUBYEAR > 2020"
```

### Sort Options

`relevancy` (default), `citedby-count`, `-pubyear` (newest first), `+pubyear` (oldest first)

## Abstract Retrieval

Detailed metadata for a single paper; the identifier type (DOI / EID `2-s2.0-...` / Scopus ID) is auto-detected. The result is **auto-saved** — it inserts a new row or upgrades an existing one with richer metadata.

```bash
abstract 10.1016/j.example.2024
abstract 2-s2.0-85012345678
abstract 10.1016/j.example.2024 --view FULL
```

Views: `META`, `META_ABS`, `FULL`, `REF`, `ENTITLED`. For normal use stick to `META_ABS`/`FULL` — `REF` returns the paper's cited-reference list and `ENTITLED` only checks access entitlement (no metadata). `FULL`'s abstract text and full author list require the institutional tier.

**`--view FULL` matters**: in practice, corresponding-author flags, index keywords, detailed affiliations, and subject areas are only reliably populated by `abstract --view FULL` — STANDARD (free-tier) search results never carry them. Corresponding-author flags land in the saved record (visible via `db info`), not in the command's printed output. To upgrade already-saved articles, loop over their EIDs through the CLI (never open the DuckDB file directly — DuckDB is single-writer; see `troubleshooting.md`):

```bash
for eid in $(scopus-for-dobby --json db list --collection my-collection -n 1000 \
             | jq -r '.articles[].eid'); do
  scopus-for-dobby abstract "$eid" --view FULL
done
```

Each iteration is one API call against the abstract quota — for large collections, check the budget first with `auth quota`.

## API Rate Limits & Quota

Throttled automatically per endpoint:

- Search: 9 req/sec (20,000/week)
- Abstract: 9 req/sec (10,000/week)
- Author retrieval: 3 req/sec
- Author search: 2 req/sec

`auth quota` shows the cached remaining budget and reset time **without spending a call** (it reflects the most recent API response; `auth status` includes it too). On `429`, the error message shows the reset time — wait it out, or shift work to OpenAlex (`openalex.md`), which has its own independent free quota.
