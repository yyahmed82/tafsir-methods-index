# site/ — the public reader on mirqah.app

**English.** This folder is uploaded as-is to the Cloudflare Worker `mirqah` (static assets).
`index.html` is the reader (`src/fahras_v2_template.html`) built by `src/build_site.py` from the
**published snapshot** of the committee console (`https://console.mirqah.app/public/v1/published.json`):
only units a human specialist approved and a super admin published, inside the pinned source text
(`data/nur/`), checked letter for letter at build time. No review mode, no export, no working states,
no model names. `reader.html`, `fahras.html`, `methods.html` and `app.html` redirect to `/`.

Build and deploy (after publishing a version in the console):

```bash
python3 src/build_site.py                      # reads the console snapshot → site/index.html
python3 src/build_site.py --snapshot x.json    # from a saved snapshot (offline / tests)
cd site && zip -qr ../mirqah-site.zip . && cd ..
```

Then Cloudflare → Workers & Pages → `mirqah` → **New deployment** → upload the zip → **Deploy**,
or `npx --yes wrangler@latest deploy --assets ./site --name mirqah --compatibility-date 2026-10-01`.
The committed `index.html` is built from an empty snapshot (the "nothing published yet" card).

**العربية.** هذا المجلد يُرفع كما هو إلى Cloudflare Worker باسم `mirqah`. الصفحة `index.html` هي القارئ
نفسه (`src/fahras_v2_template.html`) يبنيه `src/build_site.py` من **الإصدار المنشور** من لوحة اللجنة:
لا يظهر إلا ما اعتمده متخصص بشري ونشره المشرف العام، داخل النص المثبّت (`data/nur/`) المطابق حرفاً بحرف
عند البناء. لا وضع مراجعة، ولا تصدير، ولا حالات عمل، ولا أسماء نماذج. الصفحات القديمة تحوّل إلى `/`.
البناء والنشر: بعد نشر إصدار من اللوحة، `python3 src/build_site.py` ثم ضغط محتويات `site/` ورفعها في Cloudflare.
