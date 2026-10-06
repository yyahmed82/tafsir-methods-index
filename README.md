# مِرْقاة · Mirqah — فهرس مناهج التفسير / Tafsir Methods Index

Indexing the *method* of classical Quran commentators — verified by code, decided by human specialists, without an AI writing a single letter of the source text.
فهرسة **منهج** المفسِّر في نص التفسير: يتحقّق منها الكود، ويقرّرها متخصصون بشر، ولا يكتب الذكاء الاصطناعي حرفاً واحداً من النص.

**Live reader:** https://mirqah.app · **Committee console:** https://console.mirqah.app · **Repo:** https://github.com/yyahmed82/tafsir-methods-index

Team **مِرْقاة (840)** — Track 4 (knowledge and verification tools), Islamic AI Challenge 2026. [English](#english) · [العربية](#العربية)

---

## English

### 1. Installation

#### Option A — one command (recommended)

Installs the committee console, the public reader and a local model engine (Ollama) on Ubuntu/Debian, WSL2 or macOS. No keys, no external services; nothing leaves the machine.

```bash
curl -fsSL https://raw.githubusercontent.com/yyahmed82/tafsir-methods-index/build/committee-console/install.sh | bash
```

| Tier | RAM | Disk | Models | What you get |
|---|---|---|---|---|
| `full` | 16 GB | 22 GB | `qwen2.5:14b` + `gemma3:12b` | the same engine the team runs |
| `lite` | 8 GB | 8 GB | `qwen2.5:3b` + `gemma3:1b` | the whole workflow on a laptop (lower tagging quality) |
| `none` | 4 GB | 3 GB | — | demo mode only (a simulated year of committee work) |

1. The installer picks the tier from your memory and disk (force one with `--tier lite`), asks for your e-mail (used only to sign in locally) and runs eight steps with a progress bar.
2. Open **http://localhost:8800** (console). Mail is in mock mode, so the one-time sign-in code appears on screen. The reader is at http://localhost:8080.
3. Check a machine without installing anything: `bash install.sh --check`. Services: `mirqah-local status | stop | start | update | uninstall`.

Options, SSH tunnels, troubleshooting and what goes where: [`docs/INSTALL.md`](docs/INSTALL.md).

#### Option B — manual (developers)

Prerequisites: Python 3.11+, git, and optionally [Ollama](https://ollama.com) with the two models of a tier above.

```bash
git clone https://github.com/yyahmed82/tafsir-methods-index.git && cd tafsir-methods-index
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r console/requirements.txt
python3 -m pytest -q                      # unit tests (a few skip without quran.db)
python3 src/v2_selftest.py                # must print SELFTEST PASS
python3 -m console create-user --email you@example.com --name "Your name" --role super_admin,specialist
python3 -m console --port 8800            # http://127.0.0.1:8800
```

1. Sign in with the e-mail you registered; the one-time code is shown on screen and saved in `console/var/outbox/` (mock mail).
2. No model engine? Seed demo mode with `python3 -m console demo-seed --months 12` and use the **Live | Demo** switch in the top bar. `python3 -m console llm-probe` tells you whether the console can reach both models.
3. Public site preview: `python3 -m http.server 8080 --directory site`, then open `http://localhost:8080/?data=http://localhost:8800/public/v1/published.json`. The site is static: the whole surah from the pinned text, and it marks only the snapshot the console published (`/public/v1/published.json`), fetched live on every load, so a new publication shows on the next reload without a rebuild. See [`site/README.md`](site/README.md).

#### Option C — production server

Cloudflare (Pages + Tunnel) in front of a small Ubuntu server, pull-based CI-gated deploys with `mirqah-deploy`, nightly backups: [`deploy/README.md`](deploy/README.md).

### 2. What it is

Classical tafsir is long continuous prose in which hadith, Companions' sayings, grammar, legal rulings and isra'iliyyat run together. Mirqah cuts a commentary into small units and tags each unit with the commentator's *method* (Quran by Quran, Sunnah, Companions, Successors, language, readings, the commentator's own opinion…) and its content type. Models only *propose*; code verifies every proposal against the pinned source letter by letter; a human specialist decides; a super admin publishes; the public reader shows nothing else. The tool indexes — it never interprets a verse or answers a religious question.

### 3. Scope

- Surah **An-Nur (24)**: 64 ayat × 4 tafsirs (al-Tabari, Ibn Kathir, al-Baghawi, al-Saadi) = **296 windows** under `data/nur/`.
- Source text from Tafsir Center's open dataset, pinned by SHA-256 (`data/raw/manifest.json`), never retyped or normalised.
- Strict fidelity checker (`reports/nur/check_fidelity_strict.py`): **76,773 / 76,773** checks pass — every span and window re-reads letter for letter from the pinned source. This is a text-integrity check, not a tag-accuracy figure.
- Earlier pilot (three ayat, `data/v2/`, `data/multi/`) is kept for its tests and history.

### 4. How it works

```
pinned source ─► spans (code) ─► classifier model proposes by span ids only
     ─► independent verifier model (another model family) ─► deterministic checker
     ─► committee chair (code, threshold 85, one reason code)
     ─► human specialist in the console: approve / needs edit / reject (compare-with-source required)
     ─► super admin publishes a versioned snapshot ─► mirqah.app reads only that snapshot
```

- **The AI never writes a letter of the text.** Models return span ids and a closed list of codes; the checker rebuilds each unit from the pinned file and matches it letter for letter, then scores and routes it.
- **Committee chair** is plain code: a unit becomes a *candidate* only when both arms agree on boundaries and primary method, the score is ≥ 85 and no evidence flag is raised; otherwise it goes to the specialist queue with one reason code. Abstention is a safety feature, not an error.
- **Agent training** (`method/profiles/`, `src/specialist.py`): one method profile per commentator, built from academic studies of his method; six narrow-context specialist agents (Quran, Sunnah, attribution, language and readings, reports, opinion) each see only their family's rules and the move's spans, and can only *block* a candidate — never approve. Reviewer lessons feed back as references only.
- **Blind A/B review:** the specialist sees both arms (X / Y) of a window without knowing which is which; identical approved units are merged.
- **Numbers are routing counts, not accuracy.** No accuracy percentage is claimed anywhere in this repository.

### 5. Repository layout

| Path | What |
|---|---|
| `src/` | pipeline: fetch, layers, spans, windows, markers, packets, classify, verify, committee chair, specialists, builders |
| `console/` | committee console (FastAPI + SQLite): tasks, review, roles, reports, settings, publishing |
| `site/` | public static site served at mirqah.app (the whole surah; marks the live published snapshot only) |
| `web/` | earlier pilot pages, generated — kept for the existing tests |
| `data/` | pinned source text and derived data (`nur/`, `v2/`, `multi/`, `anfal/`); never edited by hand |
| `deploy/` | server tools (`mirqah`, `mirqah-deploy`, `mirqah-backup`), systemd units, bootstrap |
| `docs/` | install, deploy, workflow, data format, tagging plan, AI disclosure, team notes |
| `tests/` | unit and end-to-end tests (`pytest -q`) |
| `method/` | taxonomy, classifier prompt, method profiles, research, agent briefs |

### 6. Sources and licences

- **Code:** MIT — [`LICENSE`](LICENSE).
- **Tafsir text and derived data:** Tafsir Center for Quranic Studies (مركز تفسير), dataset `tafsircenter/tafsir-mcp-data`, CC BY 4.0 with attribution; non-commercial use, prior permission for commercial redistribution — [`ATTRIBUTION.md`](ATTRIBUTION.md).
- **«آيات» (King Saud University):** linked as a reading reference from each passage; no text is copied from it.
- **AI disclosure:** every model and tool used, and what each did, is in [`docs/AI_DISCLOSURE.md`](docs/AI_DISCLOSURE.md).

### 7. Starting version

The challenge build days were 4–6 October 2026. Everything up to commit [`ec616f4`](https://github.com/yyahmed82/tafsir-methods-index/commit/ec616f4) (3 October 2026, 22:27 UTC+1) is the team's prior work — the three-ayah pilot, the text pipeline and the first pages. Everything after it was built during the challenge: [compare ec616f4...main](https://github.com/yyahmed82/tafsir-methods-index/compare/ec616f4...main).

### 8. Team and contributing

**مِرْقاة (840):** Dr. Khaled Al-Refay · Yosri Yahmed · Ahmed Gomaa · Sherif Ezzeldin · Mohamed Rezk.

Branch → pull request → CI (`v2_selftest`, `pytest`, deterministic build) → owner review → merge. Never edit `data/` sources, tags or approval states by hand; models write only under `moves/<annotator>/`; no secrets in the repo. Details: [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`AGENTS.md`](AGENTS.md).

---

## العربية

### ١. التثبيت

#### الخيار أ — أمر واحد (الموصى به)

يثبّت لوحة اللجنة والقارئ العام ومحرّك نماذج محلياً (Ollama) على Ubuntu/Debian أو WSL2 أو macOS. بلا مفاتيح ولا خدمات خارجية؛ لا يخرج شيء من الجهاز.

```bash
curl -fsSL https://raw.githubusercontent.com/yyahmed82/tafsir-methods-index/build/committee-console/install.sh | bash
```

| المستوى | الذاكرة | القرص | النماذج | ما تحصل عليه |
|---|---|---|---|---|
| `full` | 16 GB | 22 GB | `qwen2.5:14b` + `gemma3:12b` | المحرّك نفسه الذي يعمل عليه الفريق |
| `lite` | 8 GB | 8 GB | `qwen2.5:3b` + `gemma3:1b` | سير العمل كاملاً على حاسوب محمول (جودة وسم أقل) |
| `none` | 4 GB | 3 GB | — | وضع المحاكاة فقط (سنة عمل مولَّدة للجنة) |

١. يختار المثبّت المستوى حسب الذاكرة والقرص (أو افرضه بـ `--tier lite`)، ويسألك عن بريدك (للدخول محلياً فقط)، ثم ينفّذ ثماني خطوات مع شريط تقدّم.
٢. افتح **http://localhost:8800** (اللوحة). البريد في وضع المحاكاة، فيظهر رمز الدخول على الشاشة. القارئ على http://localhost:8080.
٣. لفحص الجهاز دون تثبيت: `bash install.sh --check`. إدارة الخدمات: `mirqah-local status | stop | start | update | uninstall`.

الخيارات، والتشغيل عبر SSH، وحلّ المشكلات، وأماكن الملفات: [`docs/INSTALL.md`](docs/INSTALL.md).

#### الخيار ب — يدوياً (للمطوّرين)

المتطلبات: Python 3.11+ وgit، واختيارياً [Ollama](https://ollama.com) مع نموذجَي أحد المستويات أعلاه.

```bash
git clone https://github.com/yyahmed82/tafsir-methods-index.git && cd tafsir-methods-index
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r console/requirements.txt
python3 -m pytest -q                      # اختبارات الوحدات (بعضها يُتخطّى بغياب quran.db)
python3 src/v2_selftest.py                # يجب أن يطبع SELFTEST PASS
python3 -m console create-user --email you@example.com --name "اسمك" --role super_admin,specialist
python3 -m console --port 8800            # http://127.0.0.1:8800
```

١. ادخل بالبريد الذي سجّلته؛ يظهر رمز الدخول على الشاشة ويُحفظ في `console/var/outbox/` (بريد محاكى).
٢. لا محرّك نماذج عندك؟ أنشئ بيانات المحاكاة بـ `python3 -m console demo-seed --months 12` ثم استعمل مفتاح **حيّ | محاكاة** في الشريط العلوي. والأمر `python3 -m console llm-probe` يخبرك هل تصل اللوحة إلى النموذجين.
٣. معاينة الموقع العام: `python3 -m http.server 8080 --directory site` ثم افتح `http://localhost:8080/?data=http://localhost:8800/public/v1/published.json`. الموقع ثابت: السورة كاملة من النص المثبّت، ولا يعلّم إلا ما نشرته اللوحة (`/public/v1/published.json`) ويجلبه حيّاً عند كل فتح، فيظهر الإصدار الجديد عند إعادة التحميل دون بناء. التفاصيل في [`site/README.md`](site/README.md).

#### الخيار ج — خادم إنتاج

Cloudflare (Pages + Tunnel) أمام خادم Ubuntu صغير، ونشر بالسحب مشروط بنجاح CI عبر `mirqah-deploy`، ونسخ احتياطي ليلي: [`deploy/README.md`](deploy/README.md).

### ٢. ما هو المشروع

كتب التفسير نثر طويل متصل يختلط فيه الحديث، وقول الصحابي، والشرح اللغوي، والحكم الفقهي، والإسرائيليات. تقطّع مِرْقاة التفسير إلى وحدات صغيرة، وتَسِم كل وحدة بـ**منهج** المفسِّر فيها (قرآن بالقرآن، سنة، صحابة، تابعون، لغة، قراءات، رأي المفسر…) وبنوع محتواها. النماذج **تقترح** فقط؛ والكود يتحقّق من كل اقتراح بمطابقته مع المصدر المثبَّت حرفاً بحرف؛ والمتخصص البشري يقرّر؛ والمشرف العام ينشر؛ ولا يعرض القارئ العام سوى ذلك. الأداة تفهرس ولا تفسّر آية ولا تجيب عن سؤال شرعي.

### ٣. النطاق

- سورة **النور (٢٤)**: ٦٤ آية × ٤ تفاسير (الطبري، ابن كثير، البغوي، السعدي) = **٢٩٦ نافذة** في `data/nur/`.
- النص من مجموعة بيانات مركز تفسير المفتوحة، مثبَّت ببصمة SHA-256 (`data/raw/manifest.json`)، لا يُعاد كتابته ولا تطبيعه.
- الفاحص الصارم (`reports/nur/check_fidelity_strict.py`): **٧٦٬٧٧٣ / ٧٦٬٧٧٣** فحصاً ناجحاً — كل جزء وكل نافذة يُقرأ من المصدر المثبَّت حرفاً بحرف. هذا فحص لسلامة النص، لا رقم لدقة الوسوم.
- التجربة الأولى (ثلاث آيات في `data/v2/` و`data/multi/`) محفوظة لاختباراتها وتاريخها.

### ٤. كيف يعمل

```
المصدر المثبَّت ─► أجزاء (كود) ─► نموذج مصنِّف يقترح بمعرّفات الأجزاء فقط
     ─► نموذج مدقِّق مستقل (من عائلة أخرى) ─► الفاحص الحتمي
     ─► رئيس اللجنة (كود، عتبة ٨٥، رمز سبب واحد)
     ─► المتخصص البشري في اللوحة: اعتماد / يحتاج تعديلاً / رفض (المقارنة بالمصدر شرط)
     ─► المشرف العام ينشر إصداراً مرقّماً ─► mirqah.app لا يقرأ إلا هذا الإصدار
```

- **الذكاء الاصطناعي لا يكتب حرفاً من النص.** النماذج تُرجع معرّفات أجزاء ورموزاً من قائمة مغلقة؛ والفاحص يعيد بناء كل وحدة من الملف المثبَّت ويطابقها حرفاً بحرف، ثم يمنحها درجة ويوجّهها.
- **رئيس اللجنة** كود خالص: تصبح الوحدة «مرشّحاً» فقط إذا اتفق المساران على الحدود والمنهج الأساسي، وبلغت الدرجة ٨٥ فأكثر، ولم تُرفع أي علامة على الدليل؛ وإلا تذهب إلى طابور المتخصص برمز سبب واحد. الامتناع ميزة أمان لا خطأ.
- **تدريب الوكلاء** (`method/profiles/` و`src/specialist.py`): ملف منهج لكل مفسِّر مستخلص من الدراسات العلمية في منهجه؛ وستة وكلاء متخصصين بسياق ضيّق (القرآن، السنة، الإسناد والأقوال، اللغة والقراءات، الأخبار، الرأي) لا يرى كلٌّ منهم إلا قواعد عائلته وأجزاء الحركة، ولا يملك إلا **الحجب** — لا الاعتماد أبداً. ودروس المراجعين تعود إلى الحزم كإحالات فقط.
- **مراجعة A/B معمّاة:** يرى المتخصص نسختَي النافذة (X / Y) دون أن يعرف أيهما أيّ مسار؛ وتُدمج الوحدات المتطابقة المعتمدة.
- **الأرقام أعداد توجيه وليست دقة.** لا نسبة دقة مُدَّعاة في أي موضع من هذا المستودع.

### ٥. بنية المستودع

| المسار | المحتوى |
|---|---|
| `src/` | خط المعالجة: الجلب، الطبقات، الأجزاء، النوافذ، العلامات، الحزم، التصنيف، التحقق، رئيس اللجنة، المتخصصون، البناء |
| `console/` | لوحة اللجنة (FastAPI + SQLite): المهام، المراجعة، الأدوار، التقارير، الإعدادات، النشر |
| `site/` | الموقع العام الثابت على mirqah.app (السورة كاملة؛ يعلّم الإصدار المنشور الحي فقط) |
| `web/` | صفحات التجربة الأولى، مولَّدة — محفوظة للاختبارات القائمة |
| `data/` | النص المثبَّت والبيانات المشتقة (`nur/` و`v2/` و`multi/` و`anfal/`)؛ لا تُحرَّر يدوياً أبداً |
| `deploy/` | أدوات الخادم (`mirqah` و`mirqah-deploy` و`mirqah-backup`) ووحدات systemd والتهيئة الأولى |
| `docs/` | التثبيت، النشر، سير العمل، صيغة البيانات، خطة الوسم، الإفصاح عن الذكاء الاصطناعي، ملاحظات الفريق |
| `tests/` | اختبارات الوحدات والاختبارات الشاملة (`pytest -q`) |
| `method/` | التصنيف، موجّه المصنِّف، ملفات المناهج، البحث، التعليمات |

### ٦. المصادر والتراخيص

- **الكود:** MIT — [`LICENSE`](LICENSE).
- **نص التفسير والبيانات المشتقة:** مركز تفسير للدراسات القرآنية، مجموعة `tafsircenter/tafsir-mcp-data`، بترخيص CC BY 4.0 مع النسبة؛ الاستعمال غير تجاري، وإعادة التوزيع التجاري تتطلب إذناً مسبقاً — [`ATTRIBUTION.md`](ATTRIBUTION.md).
- **«آيات» (جامعة الملك سعود):** رابط للقراءة من كل موضع إلى الآية نفسها؛ ولا نُعيد نشر أي نص منه.
- **الإفصاح عن الذكاء الاصطناعي:** كل نموذج وأداة استُخدمت وما فعلته بالضبط في [`docs/AI_DISCLOSURE.md`](docs/AI_DISCLOSURE.md).

### ٧. نسخة البداية

أيام البناء في التحدي: ٤–٦ أكتوبر ٢٠٢٦. كل ما قبل الإيداع [`ec616f4`](https://github.com/yyahmed82/tafsir-methods-index/commit/ec616f4) (٣ أكتوبر ٢٠٢٦، 22:27 بتوقيت UTC+1) عمل سابق للفريق: تجربة الآيات الثلاث، وخط معالجة النص، والصفحات الأولى. وكل ما بعده بُني أثناء التحدي: [المقارنة ec616f4...main](https://github.com/yyahmed82/tafsir-methods-index/compare/ec616f4...main).

### ٨. الفريق والمساهمة

**مِرْقاة (840):** د. خالد الرفاعي · يسري يحمد · أحمد جمعة · شريف عز الدين · محمد رزق.

فرع ← طلب دمج ← CI (`v2_selftest` و`pytest` وبناء حتمي) ← مراجعة المالك ← دمج. لا تُحرَّر مصادر `data/` ولا الوسوم ولا حالات الاعتماد يدوياً أبداً؛ النماذج لا تكتب إلا تحت `moves/<annotator>/`؛ ولا أسرار في المستودع. التفاصيل: [`CONTRIBUTING.md`](CONTRIBUTING.md) و[`AGENTS.md`](AGENTS.md).
