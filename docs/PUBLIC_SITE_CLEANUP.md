# mirqah.app — cleanup plan (plan only)

**Goal:** the public site shows only what a specialist approved **and** a super admin
published in the console. Nothing AI-proposed, under review, rejected or internal.

## Where we are (5 Oct 2026)

mirqah.app is the Cloudflare Worker `mirqah` (static assets), uploaded by hand from `web/`.
The pages are pre-built HTML with their data embedded:

| File | Size | What it carries today | Keep? |
|---|---|---|---|
| `index.html` | 99 KB | Ibn Kathir pilot index (earlier tags, statuses) | rebuild as the shell of the new index |
| `fahras.html` | 1.3 MB | multi-tafsir index with `ai_proposed`, `under_review`, `needs_edit`, specialist routes, an export button | rebuild (no embedded data) |
| `reader.html` | 1.2 MB | reader with the same mixed statuses | rebuild (no embedded data) |
| `methods.html` | 357 KB | methods page with mixed statuses | rebuild (no embedded data) |
| `app.html` | 372 KB | earlier app prototype with an export flow | remove or redirect |
| `reconcile.html` + `reconcile_data.json` | 0.9 MB | the internal integrity screen (source reconciliation) | **remove from the public site** |
| `index_data.json` | 93 KB | raw index data | remove |

Counted in the files: `ai_proposed` 8×, `under_review` 15×, `needs_edit` 7×, review/export
controls in 5 pages. None of that should be public.

## Target

```
console (super admin publishes vN) ──► /public/v1/published.json  (approved + re-verified, no names)
                                              │  cached at the edge, 60 s
mirqah.app Worker ── /data/published.json ────┘  (same-origin proxy: keeps CSP connect-src 'self')
     │
     └── static shells: index / fahras / reader / methods — render only the snapshot, show
         "version vN · published <date> · approved by a human specialist"
```

## Steps

| # | Step | Detail | Done when |
|---|---|---|---|
| 0 | **Freeze** | No more hand uploads of the current `web/` | agreed in #ai-committee |
| 1 | **Data contract** | `published.json` schema v1 (`version`, `published_at`, `counts`, `units[]` with `tafsir`, `window`, `ayah`, `primary`, `secondary`, `certainty`, `span_ids`, `text`, `source_sha256`, `approved_at`). Add `schema/published.schema.json` and a test | schema + test in CI |
| 2 | **Same-origin data route** | The `mirqah` Worker gets a fetch handler: `/data/published.json` → fetch the console URL with a 60 s edge cache; on error serve the last good copy (Workers KV or the cache). Avoids CORS and keeps CSP `connect-src 'self'` | `curl mirqah.app/data/published.json` = console's version |
| 3 | **Shell pages** | Builders (`build_fahras.py`, `build_index.py`, `build_methods.py`) emit pages **without embedded data**; one shared `site.js` loads the snapshot, renders, and shows the version badge. Empty state: «لا وحدات منشورة بعد» | pages render from a fixture snapshot |
| 4 | **Remove internal pages** | Delete `reconcile.html`, `reconcile_data.json`, `index_data.json`, `app.html` from `web/` (they stay in the repo for the team: `docs/` or the console) | not in the Worker's asset list |
| 5 | **Strip working states** | No status chips for `ai_proposed` / `under_review` / `needs_edit` / `rejected`; no export or review buttons; rationale text from models never shown | test: `web/` contains none of those strings |
| 6 | **Guard test** | `tests/test_public_site.py`: every page loads only `/data/published.json`; no embedded unit data; no internal strings; CSP unchanged | in CI, gates the Worker deploy |
| 7 | **Deploy without hand uploads** | Point the Worker's Builds at `tafsir-methods-index` (`main`, `npx wrangler deploy --assets ./web …`, watch `web/*`) — content changes need no deploy at all, only code changes do | a merge to `main` updates mirqah.app |
| 8 | **Cut-over and rollback** | Publish v1 in the console → deploy the shells → check 4 pages × light/dark × phone. Rollback: content = "Make live" an older version in the console; code = previous Worker version in Cloudflare | checked by the team |

## Notes

- Judges see the same page as everyone; the console's guest login stays for the review side.
- Publishing is instant for content (console snapshot); the Worker only changes when the
  page code changes.
- Sizes drop from ~4 MB of HTML to a few small shells plus one JSON (about 1 KB per unit).
