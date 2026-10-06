# Evaluation — التقييم · مِرْقاة / Mirqah

What is measured, how, and the numbers as of **6 October 2026, 09:30 Riyadh**. [English](#english) · [العربية](#العربية)

**Nothing in this document is an accuracy rate.** Mirqah measures three things that can be verified by anyone who clones the repository: (1) that the text shown is the pinned source, letter for letter; (2) how the code routed each model proposal and why; (3) what human specialists decided. Live counts are on the console dashboard (`https://console.mirqah.app`, judges' link `/judges`); the figures below were read from the console's decision export and publish page at the time stated.

---

## English

### 1. Principles

- A model proposal is never a result. A unit exists for the public only after a specialist approved it with the source comparison and a super admin published it.
- Counts, not percentages of "accuracy": a percentage would need a gold standard that does not exist yet for method-tagging of tafsir. What we report are routing counts, review outcomes and agreement.
- Every number can be regenerated: scripts in `reports/`, tests in `tests/`, the console's export (`/api/review/export`) and the published snapshot (`/public/v1/published.json`, SHA-256 per version).

### 2. Text fidelity (integrity, not tagging quality)

| Check | Result | How to re-run |
|---|---|---|
| Strict fidelity, Surah An-Nur, 4 tafsirs | **76,773 / 76,773** pass (commit `abc9a0f`, 3 Oct 2026) | `python3 reports/nur/check_fidelity_strict.py --db quran.db` (the DB is not in the repo; its SHA-256 `10e61f61…cc27` is pinned in `data/raw/manifest.json`) |
| Same, re-run offline on 6 Oct 2026 without the DB | 19,338 / 19,338 (256 spans-file hashes + 296 window hashes + 296 window slices + 18,490 span slices) | any clone, Python 3.11+ |
| Older checker (windows + span records) | 18,786 / 18,786 | `reports/nur/check_fidelity.py` |
| Determinism of the preparation pipeline (al-Saadi re-run) | 384 vs 384 files; 320 / 320 compared files equal; raw and markers byte-identical | `reports/nur/check_determinism.py` |
| CI guard | `data/**/{raw,layers,spans,windows}` may not be modified, deleted or renamed by a pull request | `.github/workflows/ci.yml` "Frozen paths" |

What one strict check is: 1 (DB present) + 4 × 259 per tafsir (row count, no duplicate ayat, ayat 1–64, each of 64 rows non-empty / raw file present / raw equals DB text / spans-file SHA) + 6 per window (SHA, integer offsets, offsets in range, non-empty text, slice equals text, spans in order) + 8 per span (four checks, counted in the spans file and again in the window) = 1 + 1,036 + 1,776 + 73,960 = 76,773.

### 3. Corpus under evaluation

| Tafsir | Windows | Spans | Source characters | Apparatus characters (editor's notes, refs, brackets) |
|---|---:|---:|---:|---:|
| al-Tabari | 84 | 4,435 | 354,825 | 69,812 |
| Ibn Kathir | 82 | 2,817 | 294,948 | 56,148 |
| al-Baghawi | 66 | 1,129 | 191,161 | 27,450 |
| al-Saadi | 64 | 864 | 73,585 | 1,833 |
| **Total** | **296** | **9,245** | **914,519** | 155,243 |

64 ayat × 4 tafsirs = 256 ayah-units; 22 of them exceed the 110-span cap and are split into 62 part-windows, hence 296. Details: [`DATA_CARD.md`](DATA_CARD.md).

### 4. Human review outcomes — Surah An-Nur (challenge build)

Source: console decision export, 6 Oct 2026 09:30 Riyadh. One specialist had reviewed so far; a second specialist has windows assigned.

| Measure | Value |
|---|---|
| Decision records | 14, on 7 moves in 7 windows (al-Tabari 24:3, 24:11 parts 1–4; al-Baghawi 24:11 parts 1 and 3) |
| All records | approve 1 · needs edit 11 · reject 2 |
| Latest decision per move | **approve 1 · needs edit 6** (two earlier *reject*s on al-Tabari 24:11 p02 were superseded by *needs edit — wrong bounds* after the specialist re-read the source) |
| Error types given | wrong_bounds 3 · other 4 · wrong_method 1 · verse_in_report 1 · note only 5 |
| Published | **v1**, 6 Oct 2026 07:00 Riyadh — 1 unit (al-Baghawi 24:11, `M_SUNNAH`), approved after the source comparison; SHA-256 of the snapshot is shown on the publish page |
| Specialist queue | 25 windows / 129 moves open across 2 specialists (console → Workflow) |

What the notes say (the lesson, not the numbers): units were cut at the wrong punctuation (the specialist asks for the comma, not the full stop), a unit started with the last line of a Bukhari hadith, another was only part of an asbāb al-nuzūl report, and in one al-Tabari window the specialist reports text missing from the digital source. Boundary quality is therefore the first thing the next model run and the profiles must improve; method labels came second.

### 5. Pilot results (three ayat, before the challenge)

Kept for history; they are from the earlier three-ayah pilot (2:255, 2:102, 17:105) and are routing counts of the deterministic checker (`auto` = score ≥ 75, explicit/strong certainty, no flags — not the chair's 85 rule).

| Run | Moves | auto | specialist | Source |
|---|---:|---:|---:|---|
| Ibn Kathir — Codex | 42 | 23 | 19 | `reports/v2_summary.md` |
| Ibn Kathir — DeepSeek | 44 | 26 | 18 | `reports/v2_summary.md` |
| al-Tabari — DeepSeek + MiMo | 31 | 18 | 13 | `data/multi/al_tabari/summary.md` |
| al-Baghawi — DeepSeek | 39 | 29 | 10 | `data/multi/al_baghawi/summary.md` |
| al-Saadi — DeepSeek | 24 | 15 | 9 | `data/multi/al_saadi/summary.md` |

Two-annotator agreement on the v0.1 taxonomy (Grok vs Codex, Ibn Kathir, 143 spans): boundary F1 1.0 / 1.0 / 0.667 per ayah; exact agreement on the evidence-source tag 0.909, on the content tag 0.692, on both 0.636; 75 spans sent to the specialist queue (`reports/comparison.md`, `reports/specialist_queue.json`). Two digital editions of Ibn Kathir compared: similarity 0.874 / 0.977 / 0.804 with the apparatus, 0.978 / 0.965 / 0.949 author text only (`reports/reconciliation*.md`) — the reason the source is pinned and never "corrected".

### 6. Automated tests and CI

- **240 tests** in 21 modules (`pytest -q`): checker and chair (threshold 85, reason codes), grounding contract (packet hash, manual input never nominated), specialists (strict context, block-only), profiles (arm A unchanged), console (roles, specialist-only decisions, assignment, publishing, demo read-only), public site (pinned text letter for letter, only published units marked), installer.
- `src/v2_selftest.py` prints `SELFTEST PASS` on fixed fixtures: scores, routes, the empty-evidence cap (≤ 59) and `PACKET_HASH_MISSING`.
- CI (`.github/workflows/ci.yml`): self-test, pytest, the reader built twice and compared byte for byte, frozen data paths, and the installer on Ubuntu and macOS. The production server deploys a commit only after the `test` check is green and rolls back on a failed health check.

### 7. What is measured next

1. **Inter-annotator agreement** (Cohen's κ on primary method, boundary F1 on span ranges) once two specialists have decided the same windows — the assignment logic already gives both blind arms of a window to one specialist; a second pass by another specialist is the plan.
2. **Candidate precision**: approved ÷ chair candidates, per tafsir and per arm (A vs B), reported as counts with the denominator.
3. **Abstention rate** and the distribution of reason codes per model tag.
4. **Post-tagging blind sample** (`docs/TAGGING_PLAN_NUR.md`): at least 10 windows per tafsir re-tagged by a third model family and compared automatically; disagreement takes the strictest verdict; no percentages, no automatic approval.
5. Time per decision and the share of decisions that needed the source comparison to be re-done.

---

## العربية

### ١. المبادئ

- اقتراح النموذج ليس نتيجة. لا توجد وحدة للعامة إلا بعد أن يعتمدها متخصص مع مقارنة المصدر وينشرها المشرف العام.
- أعداد لا نسب «دقة»: النسبة تحتاج معياراً ذهبياً لوسم مناهج التفسير لا يوجد بعد. ما نعرضه أعداد توجيه ونتائج مراجعة واتفاق.
- كل رقم قابل لإعادة التوليد: سكربتات `reports/`، واختبارات `tests/`، وتصدير اللوحة (`/api/review/export`)، واللقطة المنشورة (`/public/v1/published.json`، بصمة SHA-256 لكل إصدار).

### ٢. سلامة النص (سلامة لا جودة وسم)

| الفحص | النتيجة | إعادة التشغيل |
|---|---|---|
| الفحص الصارم، سورة النور، أربعة تفاسير | **٧٦٬٧٧٣ / ٧٦٬٧٧٣** ناجحاً (الإيداع `abc9a0f`، ٣ أكتوبر ٢٠٢٦) | `python3 reports/nur/check_fidelity_strict.py --db quran.db` (قاعدة البيانات ليست في المستودع؛ بصمتها `10e61f61…cc27` مثبَّتة في `data/raw/manifest.json`) |
| إعادة الفحص دون قاعدة البيانات، ٦ أكتوبر ٢٠٢٦ | ١٩٬٣٣٨ / ١٩٬٣٣٨ (٢٥٦ بصمة ملف أجزاء + ٢٩٦ بصمة نافذة + ٢٩٦ مقطع نافذة + ١٨٬٤٩٠ مقطع جزء) | أي نسخة من المستودع |
| الفاحص الأقدم | ١٨٬٧٨٦ / ١٨٬٧٨٦ | `reports/nur/check_fidelity.py` |
| حتمية خط التحضير (إعادة تشغيل السعدي) | ٣٨٤ مقابل ٣٨٤ ملفاً؛ ٣٢٠ / ٣٢٠ متطابقة؛ الخام والعلامات متطابقة بايتاً بايتاً | `reports/nur/check_determinism.py` |
| حارس CI | لا يجوز لطلب دمج تعديل `data/**/{raw,layers,spans,windows}` أو حذفها أو إعادة تسميتها | `.github/workflows/ci.yml` |

الفحص الواحد: ١ (وجود القاعدة) + ٤ × ٢٥٩ لكل تفسير + ٦ لكل نافذة + ٨ لكل جزء = ٧٦٬٧٧٣.

### ٣. المدوّنة

الطبري ٨٤ نافذة / ٤٬٤٣٥ جزءاً / ٣٥٤٬٨٢٥ حرفاً · ابن كثير ٨٢ / ٢٬٨١٧ / ٢٩٤٬٩٤٨ · البغوي ٦٦ / ١٬١٢٩ / ١٩١٬١٦١ · السعدي ٦٤ / ٨٦٤ / ٧٣٬٥٨٥ · **المجموع ٢٩٦ نافذة، ٩٬٢٤٥ جزءاً، ٩١٤٬٥١٩ حرفاً** (منها ١٥٥٬٢٤٣ حرفاً من جهاز المحقق). ٦٤ آية × ٤ تفاسير = ٢٥٦ وحدة آية؛ ٢٢ منها تجاوزت سقف ١١٠ أجزاء فقُسمت إلى ٦٢ نافذة جزئية، ومن هنا ٢٩٦. التفاصيل في [`DATA_CARD.md`](DATA_CARD.md).

### ٤. نتائج المراجعة البشرية — سورة النور (بناء التحدي)

المصدر: تصدير قرارات اللوحة، ٦ أكتوبر ٢٠٢٦، ٠٩:٣٠ بتوقيت الرياض. راجع متخصص واحد حتى الآن؛ ولمتخصص ثانٍ نوافذ مسندة.

| المقياس | القيمة |
|---|---|
| سجلات القرار | ١٤، على ٧ حركات في ٧ نوافذ (الطبري ٢٤:٣ و٢٤:١١ الأجزاء ١–٤؛ البغوي ٢٤:١١ الجزءان ١ و٣) |
| كل السجلات | اعتماد ١ · يحتاج تعديلاً ١١ · رفض ٢ |
| آخر قرار لكل حركة | **اعتماد ١ · يحتاج تعديلاً ٦** (رفضان سابقان على الطبري ٢٤:١١ ج٢ حلّ محلهما «يحتاج تعديلاً — حدود خاطئة» بعد إعادة قراءة المصدر) |
| أنواع الخطأ | حدود خاطئة ٣ · أخرى ٤ · منهج خطأ ١ · آية داخل خبر ١ · ملاحظة فقط ٥ |
| المنشور | **الإصدار ١**، ٦ أكتوبر ٢٠٢٦ ٠٧:٠٠ بتوقيت الرياض — وحدة واحدة (البغوي ٢٤:١١، `M_SUNNAH`) اعتُمدت بعد مقارنة المصدر؛ بصمة اللقطة معروضة في صفحة النشر |
| طابور المتخصصين | ٢٥ نافذة / ١٢٩ حركة مفتوحة لدى متخصصَين |

ما تقوله الملاحظات (الدرس لا الأرقام): قُصّت وحدات عند علامة ترقيم خاطئة (المتخصص يطلب الفاصلة لا النقطة)، وبدأت وحدة بآخر سطر من حديث في البخاري، وكانت أخرى جزءاً من خبر سبب نزول، وفي نافذة من الطبري أبلغ المتخصص عن نص ناقص في المصدر الرقمي. فجودة الحدود أول ما يجب أن يحسّنه التشغيل التالي وملفات المناهج؛ ووسم المنهج ثانياً.

### ٥. نتائج التجربة الأولى (ثلاث آيات، قبل التحدي)

أعداد توجيه من الفاحص الحتمي («آلي» = درجة ≥ ٧٥ ويقين صريح/قوي وبلا أعلام — لا قاعدة الرئيس ٨٥): ابن كثير — Codex ٤٢ حركة: ٢٣ آلي / ١٩ متخصص؛ ابن كثير — DeepSeek ٤٤: ٢٦ / ١٨؛ الطبري ٣١: ١٨ / ١٣؛ البغوي ٣٩: ٢٩ / ١٠؛ السعدي ٢٤: ١٥ / ٩ (`reports/v2_summary.md` و`data/multi/*/summary.md`). اتفاق مصنِّفَين على تصنيف v0.1 (Grok مقابل Codex، ابن كثير، ١٤٣ جزءاً): F1 للحدود ١٫٠ / ١٫٠ / ٠٫٦٦٧ لكل آية؛ اتفاق تام على وسم مصدر الدليل ٠٫٩٠٩، وعلى نوع المحتوى ٠٫٦٩٢، وعليهما معاً ٠٫٦٣٦؛ ٧٥ جزءاً أُحيل إلى طابور المتخصص (`reports/comparison.md`). ومقارنة نسختين رقميتين لابن كثير: تشابه ٠٫٨٧٤ / ٠٫٩٧٧ / ٠٫٨٠٤ مع جهاز المحقق، و٠٫٩٧٨ / ٠٫٩٦٥ / ٠٫٩٤٩ لكلام المؤلف وحده — ولهذا يُثبَّت المصدر ولا «يُصحَّح».

### ٦. الاختبارات الآلية وCI

- **٢٤٠ اختباراً** في ٢١ وحدة (`pytest -q`): الفاحص والرئيس (عتبة ٨٥ ورموز الأسباب)، عقد التثبيت (بصمة الحزمة، المدخل اليدوي لا يُرشَّح)، الأخصائيون (سياق صارم، حجب فقط)، ملفات المناهج (الذراع أ لا يتغير)، اللوحة (الأدوار، قرار المتخصص وحده، الإسناد، النشر، المحاكاة للقراءة فقط)، الموقع العام (النص المثبَّت حرفاً بحرف، لا يُعلَّم إلا المنشور)، والمثبّت.
- `src/v2_selftest.py` يطبع `SELFTEST PASS` على ثوابت: الدرجات والتوجيه وسقف الشاهد الفارغ (≤ ٥٩) و`PACKET_HASH_MISSING`.
- CI: الفحص الذاتي، pytest، بناء القارئ مرتين ومقارنته بايتاً بايتاً، المسارات المجمّدة، والمثبّت على Ubuntu وmacOS. وخادم الإنتاج لا ينشر إيداعاً إلا بعد نجاح فحص `test` ويتراجع تلقائياً عند فشل فحص الصحة.

### ٧. ما يُقاس لاحقاً

١. **اتفاق المراجعين** (كابا كوهين على المنهج الرئيسي، وF1 على الحدود) حين يقرر متخصصان في النوافذ نفسها.
٢. **دقة الترشيح**: المعتمد ÷ مرشَّحو الرئيس، لكل تفسير ولكل ذراع (أ مقابل ب)، أعداداً مع المقام.
٣. **معدل الامتناع** وتوزيع رموز الأسباب لكل نموذج.
٤. **عينة معمّاة بعد الوسم** (`docs/TAGGING_PLAN_NUR.md`): عشر نوافذ على الأقل لكل تفسير يعيد وسمها نموذج من عائلة ثالثة وتُقارن آلياً؛ عند الاختلاف يؤخذ الحكم الأشد؛ بلا نسب ولا اعتماد آلي.
٥. الزمن لكل قرار، ونسبة القرارات التي أعيدت فيها مقارنة المصدر.
