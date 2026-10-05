# `site/` — public website for مِرْقاة (mirqah.app)

This folder is the **complete, static** public site served at <https://mirqah.app>.
It is uploaded as-is to the Cloudflare Worker `mirqah` (static assets only — there is
no server code here). It replaces the old `web/` pilot pages, which are kept in the
repository only for the existing tests.

The site is a **read-only reader**: it shows only passages that a human specialist
approved and a super admin published from the committee console. There is no review
mode, no decision buttons, no status chips and no model or reviewer names.

## Files

| Path | Purpose |
|---|---|
| `index.html` | The reader (home page `/`). All CSS/JS is inline. |
| `reader.html`, `fahras.html`, `methods.html`, `app.html` | Tiny redirect pages → `/` so old links keep working. |
| `_headers` | Cloudflare headers (CSP, HSTS, caching). `connect-src` allows `https://console.mirqah.app`. |
| `assets/brand/` | Logo (`mirqah-logo.svg`, `mirqah-logo-on-dark.svg`), mark, icon, and `quranpedia-books.js` (builds the «اقرأ في المصدر» link). |

Do **not** place `published.json` or any data file in this folder — data is fetched at
runtime from the console.

## Deploy

Either of the two:

1. **Dashboard:** zip the *contents* of `site/` (not the folder itself) → Cloudflare →
   Workers & Pages → `mirqah` → *New deployment* → upload the zip.
2. **CLI** (from the repository root):

   ```bash
   npx --yes wrangler@latest deploy --assets ./site --name mirqah --compatibility-date 2026-10-01
   ```

## Data contract

`index.html` fetches `https://console.mirqah.app/public/v1/published.json`
(`fetch(..., {cache: 'no-cache'})`, CORS `*`). While nothing is published the console
answers `404 {"error":"not_published"}` and the page shows the "not published yet" card.
For local testing you can point the page at any JSON file: `index.html?data=published.json`.

Top level: `version` (int), `published_at` (unix seconds), `project`, `team`, `note`,
`counts` `{units, windows, by_tafsir, by_method}`, `notice_ar`, `methods_ar`
(method code → Arabic name), `units[]`, `windows[]`.

- `windows[]` — one per (tafsir, window) that has approved units: `tafsir`
  (`al_tabari | ibn_kathir | al_baghawi | al_saadi`), `tafsir_name_ar`, `window`
  (`24_11`, `24_11_p02`), `ayah` (`24:11`), `surah`, `surah_name_ar`, `ayah_number`,
  `part`, `parts`, `ayah_text` (may be `null`), `source_file`, `source_sha256`,
  `window_start`, `window_end`, `text` (the pinned passage; editor apparatus as
  `¬…¥`, verse quotes as `{…}`).
- `units[]` — approved passages: `id`, `tafsir`, `window`, `ayah`, `move`, `primary`
  (method code), `secondary` (e.g. `["T_SHIR"]`), `certainty`
  (`explicit | strong | weak | insufficient`), `content_tags`, `span_ids`,
  `evidence_span_ids`, `references` `{verses, hadith, persons}`, `start`, `end`
  (absolute offsets in the source file; offset inside the window = `start - window_start`),
  `text`, `approved_at`.

Page state lives in the URL hash: `#/<surah>/<ayah>/<tafsir>` (e.g. `#/24/11/al_saadi`).

---

## بالعربية

هذا المجلد هو الموقع العام الكامل لـ **مِرْقاة** على <https://mirqah.app>، ويُرفع كما هو إلى
Cloudflare Worker باسم `mirqah` (ملفات ثابتة فقط، لا يوجد كود خادم). وهو يحل محل صفحات
`web/` القديمة.

الموقع **قارئ للقراءة فقط**: يعرض الوحدات التي اعتمدها متخصص بشري ونشرها مدير الفهرس من
لوحة اللجنة، ولا يحوي أي أزرار مراجعة أو قرار، ولا أسماء نماذج أو مراجعين.

**النشر:** إمّا بضغط *محتويات* مجلد `site/` في ملف zip ورفعه من Cloudflare ← Workers & Pages
← `mirqah` ← New deployment، أو بالأمر:

```bash
npx --yes wrangler@latest deploy --assets ./site --name mirqah --compatibility-date 2026-10-01
```

**البيانات:** تُجلب أثناء التشغيل من `https://console.mirqah.app/public/v1/published.json`؛
وإذا لم يُنشر شيء بعد تردّ الخدمة بـ `404` وتظهر بطاقة «لم يُنشر بعد أي إصدار معتمد». للاختبار
المحلي: `index.html?data=published.json`. لا تضع أي ملف بيانات داخل هذا المجلد.
