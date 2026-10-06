# site/ — the public reader on mirqah.app

**English.** This folder is uploaded as-is to the Cloudflare Worker `mirqah` (static assets).
`index.html` is the reader (`src/fahras_v2_template.html`) built by `src/build_site.py` over the
**whole surah**: every ayah of every tafsir from the pinned source text (`data/nur/`), checked letter
for letter at build time, with a navigation strip (tafsir tabs, the 64 ayat, approved-only switch,
← → keys). Only units a human specialist approved and a super admin published are marked on the
text. The page embeds the snapshot it was built from and **fetches the live one on load**
(`https://console.mirqah.app/public/v1/published.json`, 60 s cache), checks every unit against the
embedded source text, and marks it: publishing a version in the console reaches mirqah.app on the next
reload, with no rebuild and no upload. Rebuild only when the template, the data or this builder
change. No review mode, no export, no working states, no model names. `reader.html`, `fahras.html`,
`methods.html` and `app.html` redirect to `/`.

Build and deploy (template, data or builder changed):

```bash
python3 src/build_site.py                      # reads the console snapshot → site/index.html
python3 src/build_site.py --snapshot x.json    # from a saved snapshot (offline / tests)
cd site && zip -qr ../mirqah-site.zip . && cd ..
```

Then Cloudflare → Workers & Pages → `mirqah` → **New deployment** → upload the zip → **Deploy**,
or `npx --yes wrangler@latest deploy --assets ./site --name mirqah --compatibility-date 2026-10-01`.
Local preview of another snapshot: open `index.html?data=<url of a published.json>`.

**العربية.** هذا المجلد يُرفع كما هو إلى Cloudflare Worker باسم `mirqah`. الصفحة `index.html` هي القارئ
نفسه (`src/fahras_v2_template.html`) يبنيه `src/build_site.py` على **السورة كاملة**: كل آية من كل تفسير من
النص المثبّت (`data/nur/`) المطابق حرفاً بحرف عند البناء، مع شريط تنقّل (تبويبات التفاسير، الآيات الأربع والستون،
مفتاح «المعتمد فقط»، السهمان ← →). لا يُعلَّم على النص إلا ما اعتمده متخصص بشري ونشره المشرف العام. الصفحة
تضمّن الإصدار الذي بُنيت منه **وتجلب الإصدار الحي عند الفتح** من اللوحة (`/public/v1/published.json`)، وتتحقق من كل
موضع مقابل النص المضمَّن ثم تعلّمه: نشر إصدار من اللوحة يصل إلى mirqah.app عند إعادة التحميل التالية دون بناء ولا رفع.
يُعاد البناء والرفع فقط عند تغيّر القالب أو البيانات أو البانِي. لا وضع مراجعة، ولا تصدير، ولا حالات عمل، ولا أسماء
نماذج. الصفحات القديمة تحوّل إلى `/`.
