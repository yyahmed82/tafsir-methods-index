# Model card — بطاقة النماذج · مِرْقاة / Mirqah

Status as of 6 October 2026 (commit on `build/committee-console`). [English](#english) · [العربية](#العربية)

Every figure here is read from the code paths quoted; nothing is an accuracy claim. See [`EVALUATION.md`](EVALUATION.md) for what is measured and [`AI_DISCLOSURE.md`](AI_DISCLOSURE.md) for the full list of AI tools used on the project.

---

## English

### 1. What the models are for

Mirqah indexes the *method* a classical commentator uses in each passage of his tafsir (Quran by Quran, Sunnah, Companions, language, readings, his own opinion…). Models **propose** unit boundaries and method codes; they never produce text. Code verifies every proposal against the pinned source letter by letter, a code "committee chair" decides what becomes a candidate, a human specialist decides what is approved, and only published approvals reach the public reader.

**In scope:** proposing span-id ranges and a method code from a closed list for passages of the four tafsirs under `data/nur/`.
**Out of scope — the system is built not to do these:** writing, re-typing, normalising or paraphrasing tafsir text; interpreting a verse; answering a religious question; approving anything without a human (`AGENTS.md` §Never, `README.md` §4).

### 2. Model inventory

| Role | Model (tag) | Family | Where it runs | Used in |
|---|---|---|---|---|
| Classifier (arm A and B) | `qwen2.5:14b` | Qwen 2.5 (Alibaba) | Ollama, local (`console/settings.py` llm defaults) | Challenge build, 4–6 Oct 2026, Surah An-Nur |
| Verifier (second opinion) | `gemma3:12b` | Gemma 3 (Google) | Ollama, local | same |
| Six method specialists (arm B only) | `qwen2.5:14b` (same tag as the classifier) | Qwen 2.5 | Ollama, local | same (`src/specialist.py`, `console/runner.py`) |
| "lite" tier of the local installer | `qwen2.5:3b` + `gemma3:1b` | Qwen 2.5 / Gemma 3 | Ollama, local (`install.sh` `LITE_MODELS`) | laptops with 8 GB RAM; same workflow, lower proposal quality |
| Committee chair | — no model — | `src/committee_chair.py` | | all runs |
| Deterministic checker | — no model — | `src/v2_verify.py`, `console/pipeline.py` | | all runs |
| Pilot classifiers (three ayat, Sept–3 Oct 2026) | Codex `gpt-6-sol`; DeepSeek V4.1 Flash; MiMo V2.6 Flash (via Cline); v0.1 tags by Grok and Codex | OpenAI / DeepSeek / Xiaomi / xAI | hosted | `data/v2/`, `data/multi/`, `data/tags/` only — not used for An-Nur |

The chair refuses to pair two models of the same family (`SameFamilyError`, `src/committee_chair.py`). In production the server never runs a model: it calls the team Mac's Ollama over Tailscale (`deploy/README.md`). Quantisation is the Ollama default for each tag; committee files record it as `Q4_K_M`.

### 3. How a model is called

- Endpoint: OpenAI-compatible `POST {base_url}/v1/chat/completions` (default `http://127.0.0.1:11434`), `temperature 0.0`, `response_format {"type":"json_object"}`, streaming on with a loop guard, reply cap 80,000 characters (`src/classify_api.py`).
- Timeouts: one reply ≤ `step_timeout_s − 15` s (default step timeout 600 s); the console kills the step at `step_timeout_s` (`console/runner.py`).
- Re-ask: exactly one, after invalid JSON, an unknown span id, an invalid primary or a detected loop (temperature 0.3 only after a loop). A second failure routes every move to the specialist queue with `MODEL_OUTPUT_INVALID`.
- Console retries: a failed step is retried up to 2 times (after 5 and 30 minutes); if the engine is offline the step waits 60 s without using an attempt (`console/settings.py`, `console/workflow.py`).
- One model is in memory at a time; the verifier runs the same command on the same packet with only the model tag changed.
- Context size (`num_ctx`), seed and max tokens are **not** set by the code; the console warns when the largest prompt reaches 98 % of the model's context length.

### 4. Input

A **packet** per window (`src/v2_packets.py`): `window_id, ayah, source_file, source_sha256, instructions_ar, definitions, certainty_rules, output_schema, isnad_ranges, spans[{id,start,end,text,markers}], editor_footnote_evidence`. The prompt prints the instructions, the window id and ayah, the packet hash, the ten method definitions, the certainty rules, the output schema, then each span as `s012: [markers:…] text`, and finally the editor's footnotes under a heading that says they are not the commentator's words. Arm B adds the commentator's method profile card (`method/profiles/<tafsir>.json`, version 2026-10-05.1, status *draft*) and up to four reviewer-taught examples (references only; the text is read back from the pinned window at run time).

The instruction line every model sees: *return JSON only; span ids without text; one primary method or null; abstain (`insufficient`) when evidence is missing; the footnote is not the commentator's words.*

### 5. Output contract

One JSON object: `moves[{move_id, span_ids, primary, secondary[], content_tags[], certainty, evidence_span_ids, author_verdict_span_ids, references{verses,hadith,persons}, alternatives[], rationale_ar}]`.

- `primary` ∈ the closed list below or `null`; `certainty` ∈ `explicit | strong | weak | insufficient`.
- `rationale_ar` is ≤ 25 words, stored as `unverified_model_notes` and never shown as evidence.
- Only schema fields are kept; model text is never written into any source field. The reply is bound to its packet hash; a manually pasted reply is marked `manual_unverified` and is never nominated.

| Code | Method (Arabic label) |
|---|---|
| `M_QURAN` | القرآن بالقرآن |
| `M_SUNNAH` | السنة |
| `M_SAHABA` | الصحابة |
| `M_TABIIN` | التابعون |
| `M_LUGHA` | اللغة والغريب والشعر شاهداً |
| `M_QIRAAT` | القراءات |
| `M_NUZUL` | سبب النزول |
| `M_SIRA` | المغازي والسيرة |
| `M_ISRAILIYYAT` | الإسرائيليات |
| `M_RAY` | الرأي والاجتهاد |

### 6. What happens to a proposal (no model involved)

1. **Deterministic checker** (`src/v2_verify.py`). Structure flags (`empty_span_ids`, `unknown_span_ids`, `non_contiguous_span_ids`, `unknown_primary`, `unknown_certainty`, `unknown_evidence_span`), evidence rules (evidence must sit inside the move or the span just before it; empty evidence is never substituted; editor-only evidence is flagged), method rules (`rule_M_QURAN_verse_inside_hadith`, `rule_M_SAHABA_name_only_in_isnad`, …), overlap (`mixed_or_overlap_spans`), and the packet hash (`PACKET_HASH_MISSING / MISMATCH`, `MANUAL_INPUT_UNVERIFIED`). **Score:** marker 25 + function 45 + attribution 15 + boundary 15, capped at 59 when function evidence is missing or any rule flag is raised. A move is routed `auto_candidate` only with score ≥ 75, certainty explicit/strong, no flags, sufficient evidence and a primary outside the always-human set {`M_RAY`, `M_ISRAILIYYAT`, `M_NUZUL`, `M_QIRAAT`}; otherwise it goes to the specialist queue with **one** reason code (`src/grounding_contract.py`: `RUN_FAILURE, MODEL_OUTPUT_INVALID, PACKET_HASH_MISSING, PACKET_HASH_MISMATCH, MANUAL_INPUT_UNVERIFIED, BOUNDARY_INVALID, EVIDENCE_EMPTY, EVIDENCE_OUTSIDE_MOVE, VERDICT_FAR_FROM_MOVE, EDITOR_ONLY_EVIDENCE, CONFLICTING_EVIDENCE, UNGROUNDED_CLAIM, INSUFFICIENT_EVIDENCE, FORCED_SPECIALIST_METHOD, MIXED_SPAN, RULE_FLAG, LOW_CERTAINTY, LOW_SCORE`).
2. **Committee chair** (`src/committee_chair.py`, threshold 85). A move becomes a *candidate* only when the classifier's move is auto-routed with score ≥ 85, no flags and explicit/strong certainty, **and** every overlapping verifier move is auto-routed with the same primary, no flags and explicit/strong certainty. Otherwise the first code that applies: `written_abstain, force_specialist, agent_disagree, unclear_bounds, weak_evidence`; on arm B also `specialist_block` and `specialist_missing`. Abstention text is fixed; no model words it.
3. **Method specialists** (arm B, `src/specialist.py`): six narrow agents — Quran · Sunnah · attribution (Companions, Successors) · language and readings · reports (nuzul, sira, isra'iliyyat) · opinion. Each sees only its family's definitions, this commentator's rules and traps for that family, up to three reviewed examples, the move's spans and the span before it. Verdicts `confirm | reject | reframe | abstain`; an untrusted reply becomes `invalid` and confirms nothing. **A specialist can only block a candidate, never approve one.**
4. **Human review** (console, specialist role only). Decisions `approve | needs_edit | reject`. *Approve* requires the "compared with the source" check, which re-reads the file's SHA-256, the window slice and every move through its spans; *needs edit* and *reject* require a note or one of 20 closed error types (`src/gold_bank.py`). Lessons are stored as references only and reach arm B prompts as few-shot examples; arm A prompts never change.
5. **Publish** (`console/publish.py`, super admin). Only the latest *approve* with the source check passes; units failing `source_changed`, `source_missing`, `bad_bounds` or `text_mismatch` are withheld. Identical units approved in both blind arms merge into one. Reviewer names, e-mails, scores, flags and rationales are never in the public snapshot.

### 7. Blind A/B arms

Arm A = baseline packet; arm B = the same window with the commentator's profile and taught examples. Per window, X/Y is assigned from `sha256(server salt + "tafsir/window")`; the salt lives in `VAR_DIR/ab_blind.salt`. Only users with `generate_reports` who are not specialists can see which arm is which (`console/app.py` `_reveals_arms`).

### 8. Known failure modes and limitations

- **Boundaries are the main error.** Of the human decisions recorded by 6 Oct 2026, `wrong_bounds` is the most frequent error type (cut at the wrong punctuation; a hadith's last line taken as the start of a unit; part of an asbāb al-nuzūl report). See `EVALUATION.md` §4.
- **Verse inside a report** (`verse_in_report`) and **wrong method** (`wrong_method`) occur; the checker's `rule_M_QURAN_verse_inside_hadith` catches part of this, not all.
- Small models (lite tier) fail more steps — invalid JSON, timeouts; failures are retried and otherwise shown as *failed*, never silently dropped.
- The editor's apparatus sits between spans in 1,914 of 2,405 inter-span gaps; a move that crosses a footnote is compared span by span, never as one contiguous slice (fixed 6 Oct 2026, `console/pipeline.py span_text_ok`).
- The profiles used by arm B are **drafts** pending the specialist's review of the golden rules.
- Two thresholds exist on purpose: the checker's auto route (≥ 75) and the chair's candidate rule (≥ 85).
- The method-specialist verdict (arm B only) is visible to reviewers on the review screen and can hint at the arm; a fix is pending.
- Non-determinism: a repeated call can return different proposals; proposals are kept as files and the deterministic layers above them are the judgment.

### 9. Prompts, versions and where to look

| What | Where |
|---|---|
| Classifier prompt (generated from the packet builder) | `method/classifier_prompt_v2.md`, `src/v2_packets.py`, `src/classify_api.py` |
| Method profiles (arm B) | `method/profiles/{al_tabari,ibn_kathir,al_baghawi,al_saadi}.json` — version 2026-10-05.1, draft |
| Specialist agents | `src/specialist.py` |
| Checker, chair, reason codes | `src/v2_verify.py`, `src/committee_chair.py`, `src/grounding_contract.py` |
| Error types taught by reviewers | `src/gold_bank.py` |
| Model settings at run time | console → Settings → Engine (`llm.classifier_model`, `llm.verifier_model`, `llm.step_timeout_s`) |
| Tests | `tests/test_classify_api.py`, `test_grounding_*.py`, `test_committee_chair.py`, `test_specialist.py`, `test_profiles.py` |

---

## العربية

### ١. وظيفة النماذج

تفهرس مِرْقاة **منهج** المفسِّر في كل موضع من تفسيره (قرآن بالقرآن، سنة، صحابة، لغة، قراءات، رأي…). النماذج **تقترح** حدود الوحدة ورمز المنهج فقط، ولا تُنتج نصاً. الكود يتحقق من كل اقتراح بمطابقته مع المصدر المثبَّت حرفاً بحرف، و«رئيس لجنة» برمجي يقرر ما يصير مرشَّحاً، والمتخصص البشري يقرر ما يُعتمد، ولا يصل إلى القارئ العام إلا ما نُشر بعد الاعتماد.

**داخل النطاق:** اقتراح مدى من معرّفات الأجزاء ورمز منهج من قائمة مغلقة لمواضع التفاسير الأربعة في `data/nur/`.
**خارج النطاق — النظام مبني على ألا يفعلها:** كتابة نص التفسير أو إعادة كتابته أو تطبيعه أو صياغته؛ تفسير آية؛ الجواب عن سؤال شرعي؛ اعتماد أي شيء دون إنسان.

### ٢. جرد النماذج

| الدور | النموذج | العائلة | أين يعمل | المرحلة |
|---|---|---|---|---|
| المصنِّف (الذراعان أ وب) | `qwen2.5:14b` | Qwen 2.5 (Alibaba) | Ollama محلياً | بناء التحدي ٤–٦ أكتوبر ٢٠٢٦، سورة النور |
| المدقِّق (رأي ثانٍ) | `gemma3:12b` | Gemma 3 (Google) | Ollama محلياً | نفسها |
| ستة أخصائيي منهج (الذراع ب فقط) | `qwen2.5:14b` | Qwen 2.5 | Ollama محلياً | نفسها |
| مستوى «lite» في المثبّت المحلي | `qwen2.5:3b` + `gemma3:1b` | Qwen / Gemma | Ollama محلياً | أجهزة ٨ GB؛ سير العمل نفسه بجودة اقتراح أقل |
| رئيس اللجنة | — بلا نموذج — | `src/committee_chair.py` | | كل التشغيلات |
| الفاحص الحتمي | — بلا نموذج — | `src/v2_verify.py` | | كل التشغيلات |
| مصنِّفات التجربة الأولى (ثلاث آيات، حتى ٣ أكتوبر) | Codex `gpt-6-sol`، DeepSeek V4.1 Flash، MiMo V2.6 Flash (عبر Cline)، ووسوم v0.1 من Grok وCodex | OpenAI / DeepSeek / Xiaomi / xAI | مستضافة | `data/v2/` و`data/multi/` و`data/tags/` فقط — لم تُستعمل في سورة النور |

يرفض رئيس اللجنة نموذجين من عائلة واحدة. وفي الإنتاج لا يشغّل الخادم أي نموذج؛ بل يستدعي Ollama على جهاز الفريق عبر Tailscale.

### ٣. كيف يُستدعى النموذج

- واجهة متوافقة مع OpenAI: `/v1/chat/completions`، حرارة ٠٫٠، إخراج JSON إلزامي، بث مع حارس تكرار، سقف الرد ٨٠٬٠٠٠ حرف.
- المهلة: الرد الواحد ≤ مهلة الخطوة − ١٥ ثانية (المهلة الافتراضية ٦٠٠ ثانية).
- إعادة سؤال واحدة بعد JSON غير صالح أو معرّف جزء مجهول أو منهج غير صالح أو تكرار؛ وبعدها يُحال كل شيء إلى المتخصص برمز `MODEL_OUTPUT_INVALID`.
- اللوحة تعيد الخطوة الفاشلة مرتين على الأكثر (بعد ٥ ثم ٣٠ دقيقة)؛ وإن كان المحرّك متوقفاً تنتظر ٦٠ ثانية دون احتساب محاولة.
- نموذج واحد في الذاكرة في كل وقت؛ والمدقِّق يشغّل الأمر نفسه على الحزمة نفسها مع تغيير النموذج فقط.
- لا يضبط الكود حجم السياق ولا البذرة ولا الحد الأقصى للرموز؛ وتنبّه اللوحة عندما يبلغ أكبر موجّه ٩٨٪ من سياق النموذج.

### ٤. المدخل

**حزمة** لكل نافذة: معرّف النافذة، الآية، الملف المصدر وبصمته، التعليمات، تعريفات المناهج العشرة، قواعد اليقين، مخطط الإخراج، مدى الأسانيد، الأجزاء (معرّف، بداية، نهاية، نص، علامات)، وحواشي المحقق تحت عنوان يصرّح بأنها ليست كلام المفسِّر. تضيف الذراع ب بطاقة منهج المفسِّر (`method/profiles/`، إصدار 2026-10-05.1، مسودة) وحتى أربعة أمثلة علّمها المراجع (إحالات فقط؛ النص يُقرأ من النافذة المثبَّتة وقت التشغيل).

التعليمة التي يراها كل نموذج: *أعد JSON فقط؛ معرّفات الأجزاء دون نص؛ منهج رئيسي واحد أو null؛ امتنع (`insufficient`) عند غياب الدليل؛ الحاشية ليست كلام المفسِّر.*

### ٥. عقد الإخراج

كائن JSON واحد: حركات، لكل حركة: معرّف، معرّفات أجزاء، منهج رئيسي (من القائمة المغلقة أو null)، مناهج ثانوية، وسوم محتوى، يقين (`explicit | strong | weak | insufficient`)، معرّفات الشاهد، معرّفات حكم المؤلف، إحالات، بدائل، وتعليل ≤ ٢٥ كلمة يُحفظ كملاحظة غير موثَّقة ولا يُعرض دليلاً. لا يُحفظ من ردّ النموذج إلا حقول المخطط؛ ولا يُكتب نص نموذج في أي حقل مصدر. الرد مربوط ببصمة الحزمة؛ والرد الملصوق يدوياً يُعلَّم `manual_unverified` ولا يُرشَّح أبداً. رموز المناهج العشرة في الجدول أعلاه.

### ٦. ما يجري على الاقتراح (بلا نموذج)

١. **الفاحص الحتمي:** أعلام البنية والشاهد والقواعد والتداخل وبصمة الحزمة؛ الدرجة = علامة ٢٥ + وظيفة ٤٥ + إسناد ١٥ + حدود ١٥، بسقف ٥٩ عند غياب شاهد الوظيفة أو رفع أي علم قاعدة. يُوجَّه «مرشّح آلي» فقط بدرجة ≥ ٧٥ ويقين صريح/قوي وبلا أعلام وبدليل كافٍ ومنهج خارج مجموعة الإحالة الدائمة {الرأي، الإسرائيليات، سبب النزول، القراءات}؛ وإلا إلى طابور المتخصص **برمز سبب واحد**.
٢. **رئيس اللجنة (عتبة ٨٥):** تصير الحركة مرشَّحاً فقط إذا كانت حركة المصنِّف آلية بدرجة ≥ ٨٥ وبلا أعلام وبيقين صريح/قوي، **و**كانت كل حركة مدقِّق متقاطعة معها آلية وبالمنهج نفسه وبلا أعلام وبيقين صريح/قوي. وإلا: `written_abstain` أو `force_specialist` أو `agent_disagree` أو `unclear_bounds` أو `weak_evidence`، وفي الذراع ب أيضاً `specialist_block` و`specialist_missing`. نص الامتناع ثابت ولا يصوغه نموذج.
٣. **أخصائيو المنهج (الذراع ب):** ستة وكلاء ضيّقو السياق — القرآن · السنة · الإسناد (الصحابة والتابعون) · اللغة والقراءات · الأخبار (النزول والسيرة والإسرائيليات) · الرأي. لا يرى كلٌّ منهم إلا تعريفات عائلته وقواعد هذا المفسِّر فيها وحتى ثلاثة أمثلة مراجَعة وأجزاء الحركة والجزء الذي قبلها. أحكامه: تأكيد / رفض / إعادة تأطير / امتناع؛ والرد غير الموثوق يصير `invalid` ولا يؤكد شيئاً. **الأخصائي يحجب المرشَّح ولا يعتمده أبداً.**
٤. **المراجعة البشرية (دور المتخصص فقط):** اعتماد / يحتاج تعديلاً / رفض. الاعتماد يشترط فحص «قارنتُ بالمصدر» الذي يعيد قراءة بصمة الملف ومقطع النافذة وكل حركة عبر أجزائها؛ والتعديل والرفض يشترطان ملاحظة أو نوع خطأ من عشرين نوعاً مغلقاً. الدروس تُحفظ إحالاتٍ فقط وتصل إلى موجّهات الذراع ب أمثلةً؛ وموجّه الذراع أ لا يتغير.
٥. **النشر (المشرف العام):** لا يمر إلا آخر اعتماد اجتاز فحص المصدر؛ وتُحجب الوحدات التي تفشل في `source_changed` أو `source_missing` أو `bad_bounds` أو `text_mismatch`. الوحدة المتطابقة المعتمدة في الذراعين تُدمج. ولا تحمل اللقطة العامة أسماء المراجعين ولا بريدهم ولا الدرجات ولا الأعلام ولا التعليلات.

### ٧. ذراعا A/B المعمّاتان

الذراع أ = الحزمة الأساسية؛ الذراع ب = النافذة نفسها مع ملف المفسِّر والأمثلة المعلَّمة. يُعيَّن X/Y لكل نافذة من `sha256(ملح الخادم + "tafsir/window")`؛ ولا يرى أيَّهما أيٌّ إلا من يملك صلاحية التقارير وليس متخصصاً.

### ٨. أنماط الفشل المعروفة والحدود

- **الحدود هي الخطأ الأول:** في القرارات البشرية المسجلة حتى ٦ أكتوبر ٢٠٢٦ كان `wrong_bounds` أكثر الأنواع (قصّ عند النقطة بدل الفاصلة؛ آخر سطر من حديث حُسب بداية وحدة؛ جزء من خبر سبب النزول). انظر `EVALUATION.md` §٤.
- يقع **آية داخل خبر** (`verse_in_report`) و**منهج خطأ** (`wrong_method`)؛ وقاعدة `rule_M_QURAN_verse_inside_hadith` تلتقط بعض ذلك لا كله.
- النماذج الصغيرة (lite) تُخفق أكثر: JSON غير صالح، مهلات؛ تُعاد المحاولة وإلا تظهر «فشل» ولا تُسقط بصمت.
- حواشي المحقق تقع بين الأجزاء في ١٬٩١٤ من ٢٬٤٠٥ فجوات؛ والحركة التي تعبر حاشية تُقارَن جزءاً جزءاً لا مقطعاً واحداً (أُصلح ٦ أكتوبر).
- ملفات المناهج في الذراع ب **مسودات** بانتظار مراجعة المتخصص للقواعد الذهبية.
- عتبتان مقصودتان: توجيه الفاحص (≥ ٧٥) وقاعدة الترشيح عند الرئيس (≥ ٨٥).
- حكم أخصائي المنهج (الذراع ب فقط) يظهر للمراجع في شاشة المراجعة وقد يلمّح إلى الذراع؛ الإصلاح قيد العمل.
- اللاحتمية: تكرار الاستدعاء قد يعطي اقتراحات مختلفة؛ تُحفظ الاقتراحات ملفات، والطبقات الحتمية فوقها هي الحكم.

### ٩. أين تنظر

الموجّه: `method/classifier_prompt_v2.md` و`src/v2_packets.py` و`src/classify_api.py` · ملفات المناهج: `method/profiles/*.json` · الأخصائيون: `src/specialist.py` · الفاحص والرئيس ورموز الأسباب: `src/v2_verify.py` و`src/committee_chair.py` و`src/grounding_contract.py` · أنواع الأخطاء: `src/gold_bank.py` · إعدادات النماذج: اللوحة ← الإعدادات ← المحرّك · الاختبارات: `tests/`.
