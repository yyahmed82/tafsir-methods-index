# لوحة لجنة الذكاء — Committee console

لوحة تشغيل محلية للجنة الوسم: من يدخل، وأي وكيل يعمل على ماذا، والتقدّم في سورة النور، والتقارير اليومية، والإعدادات.
تعمل على الجهاز نفسه الذي يشغّل Ollama. لا تكتب نص التفسير أبداً: كل خطوة تستدعي خط المعالجة المثبّت
`src/run_window.py`، وهو وحده يكتب `moves/` ثم يشغّل الفاحص الحتمي إلى `verified/` (قواعد `AGENTS.md` ١–٣).

A local operator console for the tagging committee. It runs next to Ollama and only drives the pinned
pipeline (`src/run_window.py`). It never writes tafsir text, tags or approvals of record.

## التشغيل / Run (macOS or Linux, from the repo root)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r console/requirements.txt
python -m console create-user --email you@example.com --name "Your name" --role super_admin
python -m console                         # http://127.0.0.1:8800
```

- الدخول للمسجّلين فقط برمز لمرة واحدة يُرسل إلى البريد. البريد في **وضع المحاكاة** افتراضياً:
  الرمز يظهر على الشاشة وفي `console/var/outbox/` ولا يخرج شيء من الجهاز. أطفئ «اعرض الرمز على الشاشة»
  من الإعدادات ← أمان الدخول قبل أي عرض مشترك، وأدخل بيانات SMTP عند جاهزيتها.
- Sign-in is for registered users only (one-time code by mail). Mail starts in **mock mode**.
  SMTP password: Settings → Mail (stored only in the local DB, never shown again), or the
  `MIRQAH_SMTP_PASSWORD` environment variable.
- Hosted models: the key comes only from `LLM_API_KEY` in the server's terminal. Nothing is stored.

## النشر / Production

للنشر على خادم (Cloudflare Tunnel + نشر تلقائي من `main` بعد نجاح CI + رجوع تلقائي): `deploy/README.md`.
In production set `MIRQAH_ENV=production`, `MIRQAH_PROXY=cloudflare` and `MIRQAH_ALLOWED_HOSTS`;
the server tools (`mirqah`, `mirqah-deploy`, `mirqah-backup`) are in `deploy/server/`.
Command-line settings: `python -m console settings-show [section]`,
`python -m console settings-set smtp mode=smtp host=… port=587`, `python -m console mail-test --to …`.
**Judges:** Settings → Security → «دخول المحكّمين والزوّار» adds a view-only button to the sign-in page (off by default).

## ما بداخلها / What is inside

| الصفحة | ما تعرضه |
|---|---|
| غرفة القيادة | طبقة النماذج (Ollama)، الوكلاء الخمسة: المصنّف، المدقّق، الفاحص الحتمي، رئيس اللجنة (معاينة للقراءة فقط)، المتخصص البشري — ما فعل، وما يفعل الآن، وما التالي |
| المهام | تشغيل اللجنة على العيّنة ٢٤:٣٥ أو آيات محدّدة؛ خطوة واحدة في كل مرة؛ إيقاف وإعادة الفاشل؛ مخرجات كل خطوة |
| الإنجاز | مصفوفة آية × تفسير لسورة النور كلها |
| المراجعة | وحدات المصنّف المحقّقة؛ اعتماد / يحتاج تعديلاً / رفض — للمتخصص فقط، والاعتماد يتطلب المقارنة بالمصدر |
| التقارير اليومية | تقرير يُبنى ويُرسل تلقائياً كل مساء، وتنزيله بصيغة Markdown |
| المستخدمون والأدوار | المشرف العام ثابت؛ لا يمنح أحد صلاحيات أكثر مما يملك؛ لا يمكن إيقاف آخر مشرف عام |
| الإعدادات | النماذج وسير العمل، SMTP، اللغات (العربية افتراضية + الإنجليزية والصينية والأردية، وإضافة لغات وتحرير نصوصها)، أمان الدخول، بوابات الأمان، التقارير، صندوق الصادر |

**بوابات الأمان:** لا وسم جماعي (أكثر من ١٢ نافذة) قبل أن يفعّل المشرف العام بوابتي «دمج المرحلة ٠» و«مراجعة العيّنة»،
وفق `docs/TAGGING_PLAN_NUR.md`. فحص الحزم دون نموذج متاح دائماً.

الأرقام في اللوحة «أعداد توجيه وليست دقة». معاينة رئيس اللجنة لا تكتب ملفات ولا تعني اعتماداً.

## وضع المحاكاة / Demo mode

مفتاح «حيّ | محاكاة» في الشريط العلوي يعرض سنة عمل مولَّدة على سورة النور: مهام وإخفاقات وإعادات، قرار الرئيس،
قرارات متخصصين تجريبيين، وتقارير يومية. البيانات في قاعدة منفصلة `console/var/demo.db`؛ لا تمسّ البيانات الحيّة ولا
`data/`، ولا تحتوي نصاً من التفسير، وكل شيء فيها للقراءة فقط مع شريط تنبيه في كل صفحة. الأرقام فيها **ليست نتائج**.

A Live | Demo switch shows a generated year of committee work (separate `demo.db`, read-only, banner on every
page, no tafsir text, invented "(تجريبي)" people). Generate it in Settings → Demo or
`python -m console demo-seed --months 12`; `demo-status`, `demo-clear`. Guests (judges) start on what
Settings → Demo → guest mode says, and can switch themselves.

## العرض كمستخدم آخر / View as another user

المشرف العام فقط، من قائمة الحساب: يرى اللوحة بصلاحيات المستخدم وصفحاته تماماً، **للقراءة فقط** (كل كتابة تُرفض برمز 423)،
مع شريط سفلي ثابت «العودة إلى حسابي». يُسجَّل البدء والانتهاء باسم المشرف في سجل التدقيق.
Super admins only (account menu → View as another user): the `X-Mirqah-View-As` header is honoured only for a
real super admin; identity in the audit log stays the super admin; every write is refused while switched.

## البريد / Mail

كل رسالة بقالب HTML عربي من اليمين إلى اليسار (`console/mailtpl.py`) مع نسخة نصية، والشعار مرفق داخلياً (cid):
رمز الدخول، اختبار البريد، رسالة الترحيب عند إضافة مستخدم (`--notify` أو خيار في نافذة الإضافة)، والتقرير اليومي.
Set Settings → General → console link (`settings-set general console_url=https://…`) for the buttons.
Settings → Outbox → Preview shows any sent mail as the recipient sees it (real sign-in codes stay masked).

## الشعار / Logo

`console/static/brand/`: `mirqah-logo.svg` (full, with the book), `mirqah-wordmark.svg`, `-on-dark` variants,
`mirqah-mark.svg` / `mirqah-icon.svg` (arch and stairs; favicon), `icon-180.png`, `mail-wordmark.png` (mail
header; mail clients do not show SVG). The app inlines the SVGs so the ink follows light/dark mode.

## الحالة المحلية / Local state

`console/var/` (gitignored): `console.db` (SQLite), `demo.db`, `secret.key`, `outbox/`. Delete the folder to reset.
On the server, agent runs use the writable copy in `MIRQAH_WORK_ROOT` (see `deploy/README.md`).

## Tests

```bash
python -m pytest -q tests/test_console.py   # skipped automatically when FastAPI is not installed
```

The end-to-end test runs the real pipeline on a temp copy of one tafsir with a fake Ollama server,
so the repo's `data/` is never touched.
