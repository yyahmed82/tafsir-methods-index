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

## الحالة المحلية / Local state

`console/var/` (gitignored): `console.db` (SQLite), `secret.key`, `outbox/`. Delete the folder to reset.

## Tests

```bash
python -m pytest -q tests/test_console.py   # skipped automatically when FastAPI is not installed
```

The end-to-end test runs the real pipeline on a temp copy of one tafsir with a fake Ollama server,
so the repo's `data/` is never touched.
