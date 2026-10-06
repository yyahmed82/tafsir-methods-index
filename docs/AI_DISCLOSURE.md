# الإفصاح عن أدوات الذكاء الاصطناعي — AI Disclosure

تفصح هذه الوثيقة عن كل نموذج وأداة ذكاء اصطناعي استُخدم في هذا المستودع، مقسَّمة إلى **ما أنتج البيانات (الوسوم)** و**ما بنى المشروع (الكود والوثائق والبحث)**. نص القرآن ونصوص التفسير لم يكتبها نموذج ولا عدّلها حرفًا واحدًا: النص مثبّت ببصمة SHA-256 ومطابَق حرفاً بحرف بعد كل خطوة.

## ١. النماذج التي أنتجت بيانات الوسم (التصنيف)

### أ. بناء التحدي (٤–٦ أكتوبر ٢٠٢٦) — سورة النور، التفاسير الأربعة

تعمل هذه النماذج محلياً عبر Ollama (واجهة `/v1/chat/completions`، حرارة ٠)، على جهاز الفريق؛ ولا يشغّل خادم الإنتاج أي نموذج ولا تُستدعى أي واجهة خارجية. مخرجاتها (ملفات «الحركات» والتحقق واللجنة) في مجلد عمل اللوحة لا في هذا المستودع؛ وما اعتمده المتخصص ونُشر يظهر في اللقطة العامة `https://console.mirqah.app/public/v1/published.json`. التفاصيل الكاملة (المدخل، عقد الإخراج، الدرجات، العتبات، أنماط الفشل) في [`MODEL_CARD.md`](MODEL_CARD.md).

| النموذج | العائلة | الدور | ما فعله بالضبط |
|---|---|---|---|
| **`qwen2.5:14b`** | Qwen 2.5 (Alibaba) | المصنِّف (الذراعان أ وب) | يقترح حدود الحركة بمعرّفات الأجزاء ومنهجاً رئيسياً من عشرة رموز مغلقة ودرجة يقين، ويمتنع عند غياب الدليل |
| **`qwen2.5:14b`** | Qwen 2.5 | ستة أخصائيي منهج (الذراع ب فقط) | كلٌّ منهم يرى عائلته وحدها ويجيب تأكيداً أو رفضاً أو امتناعاً؛ يحجب المرشَّح ولا يعتمده أبداً |
| **`gemma3:12b`** | Gemma 3 (Google) | المدقِّق | يعيد التصنيف على الحزمة نفسها دون أن يرى وسوم المصنِّف؛ يرفض رئيس اللجنة نموذجين من عائلة واحدة |
| `qwen2.5:3b` + `gemma3:1b` | Qwen / Gemma | مستوى «lite» في المثبّت المحلي | الأدوار نفسها على أجهزة ٨ GB لتجربة سير العمل؛ جودة اقتراح أقل |

رئيس اللجنة (`src/committee_chair.py`) والفاحص الحتمي (`src/v2_verify.py`) **كود بلا نموذج**: الفاحص يعيد بناء كل حركة من المصدر المثبَّت ويطابقها حرفاً بحرف ويمنحها درجة ورمز سبب واحداً؛ والرئيس يرشّح فقط ما اتفق عليه المساران بدرجة ≥ ٨٥؛ والمتخصص البشري وحده يعتمد.

### ب. التجربة الأولى (ثلاث آيات: 2:255 و2:102 و17:105 — قبل التحدي)

| النموذج | المزوّد / الطريق | وجهة الاستعمال | ما فعله بالضبط |
|---|---|---|---|
| **Codex** — النموذج `gpt-6-sol` | OpenAI | تفسير ابن كثير | صنّف حركات الوسم في نوافذ ابن كثير الثلاث، المخرج `data/v2/moves/codex/` |
| **DeepSeek V4.1 Flash** | عبر Cline | التفاسير الأربعة | صنّف حركات الوسم في ابن كثير والطبري والبغوي والسعدي، المخرج `data/v2/moves/deepseek/` و`data/multi/*/moves/deepseek/` |
| **MiMo V2.6 Flash** | عبر Cline | الطبري — آية 2:255 فقط | صنّف نافذة 2:255 من الطبري، المخرج `data/multi/al_tabari/moves/mimo/` |
| **Grok** و**Codex** (تصنيف v0.1 الأقدم) | xAI عبر Cursor / OpenAI | ابن كثير | وسوم المصدر ونوع المحتوى على ١٤٣ جزءاً، المخرج `data/tags/{grok,codex}/`؛ تُقارَن في `reports/comparison.md` |

**ما قيّد النماذج** (من `method/classifier_prompt_v2.md` و`method/agent-briefs/`):

1. الإشارة إلى النص **بمعرّفات الأجزاء (span IDs) فقط** — لا نسخ ولا إعادة صياغة ولا تلخيص للمصدر.
2. كل حركة تحمل `evidence_span_ids`؛ وعند غياب الدليل يُمتنع النموذج (`insufficient`) ولا يخمّن.
3. تصنيف **الوظيفة** لا الألفاظ: الآية داخل حديث ليست «قرآن بالقرآن»، وراوٍ في إسناد لا يجعله «أقوال صحابة».
4. كلام المحقّق (الحاشية وإضافة المحقق) ليس كلام المفسّر، فلا يُنشئ به منهجاً.
5. الحركات لا تتداخل، ولا يُطالب المصنّف بتغطية كل جزء.

## ٢. أدوات بناء المشروع (كود ووثائق وبحث — لا تنتج وسوماً)

| الأداة | الدور |
|---|---|
| **Claude** (Anthropic — Claude Code / Cowork) | الإشراف: تقسيم المهام، مراجعة المخرجات، التنسيق؛ وكود لوحة اللجنة والمثبّت المحلي والموقع العام وأدوات الخادم؛ ووثائق التسليم (بطاقة النماذج، بطاقة البيانات، التقييم، سياسة الأمن، هذه الوثيقة) |
| **Cursor** (نماذج Grok) | كتابة وتعديل الكود والواجهات |
| **Grok** | بحث، كود، وثائق |
| **Codex** | بحث، كود، وثائق |
| **Cline** | تنفيذ المهام؛ ومضيف لاستدعاء نموذجي DeepSeek وMiMo في خط التصنيف |
| **Antigravity** | كود ووثائق |
| **Gemini** (AGY) | كود ووثائق |

التعليمات (briefs) الموجَّهة لهذه الأدوات محفوظة حرفياً في `method/agent-briefs/`.

## ٣. الحدود والقيود

- **لا نصّ مُولَّد:** لم يكتب أي نموذج آية أو مقطعاً من تفسير، ولم يغيّر حرفاً؛ دور النموذج اقتراح حدود المقاطع والوسوم بمعرّفات فقط.
- **المقترح ليس محتوى:** الفاحص الحتمي يعيد بناء كل حركة من مواضعها ويطابقها حرفاً بحرف ثم يمنحها درجة ويوجّهها؛ ولا يُنشر إلا ما اعتمته يد بشرية.
- **الاعتماد البشري في اللوحة فقط:** سجل `approved` في `schema/example_approved.json` توضيحي، لا اعتماد متخصص. وحتى ٦ أكتوبر ٢٠٢٦ اعتمد متخصص وحدةً واحدة بعد مقارنة المصدر ونُشرت في الإصدار الأول (`published.json` v1)؛ وبقية الاقتراحات إمّا «يحتاج تعديلاً» أو في طابور المتخصصين — الأعداد في [`EVALUATION.md`](EVALUATION.md).
- **كل الأعداد المنشورة أعداد توجيه ونتائج مراجعة وليست دقة** (حركات / مرشّح آلي / مختص / معتمد) — [`EVALUATION.md`](EVALUATION.md).
- **التصنيف خطوة غير حتمية:** تكرار الاستدعاء قد يعطي نتائج مختلفة؛ لذلك تُحفظ مخرجات التصنيف في المستودع، ويظل التحقق الحتمي فوقها هو الحكم.
- **النماذج ليست مرجعاً شرعياً:** الأداة لا تُصدر شرحاً ولا جواباً شرعياً؛ تفهرس منهج المفسِّر في نصه بشاهد من المصدر، وتمتنع عند غياب الدليل، والاعتماد للمتخصص — انظر «ما هو المشروع» و«كيف يعمل» في [`../README.md`](../README.md).
- **بلا ادعاء دقة:** لا تُعرض هذه الأرقام كأداء قياسي. ثلاث آيات (2:255 و2:102 و17:105) = تجربة ما قبل التحدي؛ متن التحدي = سورة النور (٢٩٦ نافذة) — انظر [`../README.md`](../README.md) و[`EVALUATION.md`](EVALUATION.md).

## ٤. الوثائق ذات الصلة

- [`../README.md`](../README.md) — ما هو المشروع، وكيف يعمل، والنطاق.
- [`MODEL_CARD.md`](MODEL_CARD.md) — بطاقة النماذج: الجرد، المدخل، عقد الإخراج، الفاحص والرئيس، أنماط الفشل.
- [`DATA_CARD.md`](DATA_CARD.md) — بطاقة البيانات: المصدر، التكوين، المعالجة، الترخيص، المشكلات المعروفة.
- [`EVALUATION.md`](EVALUATION.md) — ما يُقاس وكيف، والأعداد حتى تاريخه.
- [`../SECURITY.md`](../SECURITY.md) — سياسة الأمن وما تحفظه اللوحة من بيانات.
- [`RUN.md`](RUN.md) — الخطوات الحتمية وأين تدخل الخطوة الخارجية.
- [`DATA_FORMAT.md`](DATA_FORMAT.md) — صيغة السجل ثلاثي الطبقات (مصدر مثبّت / مقترح آلة / وسم معتمد).
- [`../ATTRIBUTION.md`](../ATTRIBUTION.md) — المصادر والتراخيص والاستعمال غير التجاري.
---

## English summary

**Models that produced tagging proposals.** Challenge build (4–6 Oct 2026, Surah An-Nur, four tafsirs): `qwen2.5:14b` (Qwen 2.5, Alibaba) as the classifier on both A/B arms and as the six narrow method-specialist agents on arm B; `gemma3:12b` (Gemma 3, Google) as the independent verifier; the local installer's *lite* tier uses `qwen2.5:3b` + `gemma3:1b`. All run locally through Ollama (OpenAI-compatible endpoint, temperature 0); the production server runs no model and no external API is called. Their outputs live in the console's work folder, not in this repository; what a specialist approved and a super admin published is the public snapshot. Earlier three-ayah pilot: Codex `gpt-6-sol` (OpenAI), DeepSeek V4.1 Flash and MiMo V2.6 Flash via Cline, and v0.1 tags by Grok and Codex (`data/v2/`, `data/multi/`, `data/tags/`).

**What constrained every model:** refer to the text by span ids only — never copy, re-type or paraphrase; one primary method from ten closed codes or `null`; abstain (`insufficient`) when evidence is missing; the editor's footnote is not the commentator's words; moves do not overlap. The deterministic checker and the committee chair are code without a model; only a human specialist approves; nothing reaches the public reader without a published approval. No accuracy percentage is claimed anywhere.

**Tools that built the project (code, docs, research — no tags):** Claude (Anthropic; supervision, console/installer/site/server code and the submission documents), Cursor (Grok models), Grok, Codex, Cline (also the host for the DeepSeek and MiMo pilot calls), Antigravity, Gemini. Their briefs are kept verbatim in `method/agent-briefs/`.

Details: [`MODEL_CARD.md`](MODEL_CARD.md) · [`DATA_CARD.md`](DATA_CARD.md) · [`EVALUATION.md`](EVALUATION.md) · [`../SECURITY.md`](../SECURITY.md).
