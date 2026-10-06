# Data card — بطاقة البيانات · `data/nur/` and the published snapshot

Datasheet for the data this repository holds and produces. Status 6 October 2026. [English](#english) · [العربية](#العربية)

---

## English

### 1. What the data is

Four classical commentaries (tafsir) on **Surah An-Nur (24), ayat 1–64**, cut by code into spans and windows so that a model can refer to text by id and a human can verify every unit against the source. The repository holds the **pinned source text and everything derived from it by deterministic code**. It does **not** hold model proposals for An-Nur (they live in the console's work folder) and it holds no human decisions (they live in the console database); what humans approved and a super admin published is served as a versioned snapshot.

| Layer | Where | Produced by |
|---|---|---|
| Pinned source text | `data/nur/<tafsir>/raw/24_<ayah>.txt` + `source_sha256` in every window | `src/run_surah.py` from `quran.db` (no model) |
| Layers (author text vs editor's apparatus vs HTML layout) | `data/nur/<tafsir>/layers/` | `src/multi_layers.py` |
| Spans (`s001…`, `[start, end)` character offsets, text) | `data/nur/<tafsir>/spans/` | `src/spans.py`, `src/spans_author.py` |
| Windows (one per ayah, or parts `_p01…` above 110 spans) | `data/nur/<tafsir>/windows/` | `src/run_surah.py` |
| Markers (deterministic phrase hits per span, by family) | `data/nur/<tafsir>/markers/` | `src/v2_markers.py` |
| Packets (what a model receives) | `data/nur/<tafsir>/packets/` | `src/v2_packets.py` |
| Model proposals ("moves"), verified moves, committee files | console work root (`MIRQAH_WORK_ROOT`), not committed | console runs |
| Human decisions, assignments, audit | console database | console |
| Published snapshot | `https://console.mirqah.app/public/v1/published.json` (`vNNNN.json`, SHA-256 per version) | `console/publish.py` |

### 2. Composition

| Tafsir | DB table | Windows | Ayat split into parts | Spans | Characters | of which apparatus |
|---|---|---:|---:|---:|---:|---:|
| al-Tabari (d. 310 AH) | `tafsir_tabary` | 84 | 11 → 31 | 4,435 | 354,825 | 69,812 |
| Ibn Kathir (d. 774) | `tafsir_katheer` | 82 | 10 → 28 | 2,817 | 294,948 | 56,148 |
| al-Baghawi (d. 516) | `tafsir_baghawy` | 66 | 1 → 3 | 1,129 | 191,161 | 27,450 |
| al-Saadi (d. 1376) | `tafsir_saadi` | 64 | 0 | 864 | 73,585 | 1,833 |
| **Total** | | **296** | 22 → 62 | **9,245** | **914,519** | 155,243 |

1,656 files (1,400 JSON, 256 text), all added in one commit (`abc9a0f`, 3 Oct 2026) and frozen since. Largest window: al-Baghawi 24:7 (17,328 characters); 12 windows sit exactly at the 110-span cap. Spans never overlap; the gaps between consecutive spans (2,405) are the editor's footnotes (1,914), brackets or `<br>` tags.

An earlier three-ayah pilot (2:255, 2:102, 17:105) is kept under `data/v2/`, `data/multi/`, `data/spans*/`, `data/tags/` for its tests and history, and Surah Al-Anfal is prepared under `data/anfal/` (325 windows, no proposals).

### 3. Source and collection

- **Dataset:** Tafsir Center for Quranic Studies (مركز تفسير, https://tafsir.net), `tafsircenter/tafsir-mcp-data` on Hugging Face — file `quran.db` (SQLite, 234,352,640 bytes), dataset revision `dbbfa775…` last modified 2026-05-13, fetched 2026-09-28 10:10 UTC, SHA-256 `10e61f615ab5e6a3440e8ecc8ba1dc2273d12cd9048752760fe53a44d191cc27` (`data/raw/manifest.json`). The DB itself is not committed (size, licence); every window carries the SHA-256 of its raw file and the strict checker compares the DB hash before reading.
- **Extraction:** `python3 src/run_surah.py --surah 24 --base data/nur/<tafsir>` once per tafsir — "never `--classify`", no model call (`reports/nur/PREP_TEXT.md`). The raw text is the DB row encoded as UTF-8 bytes, read back with `read_exact` (no newline translation).
- **Pilot sources:** the same dataset plus the quran.com v4 API as an independent second edition for Ibn Kathir (used for comparison only, not republished — `ATTRIBUTION.md`).
- **Print edition:** not identified by either source ("none present in API response"; "no print-edition identifier in DB schema"); recorded as *under verification* in `ATTRIBUTION.md`.

### 4. Processing rules (all deterministic)

1. **Layers.** Three kinds tile the text exactly: `author`, `apparatus` (editor's footnotes `¬…¥` (U+00AC … U+00A5), verse references in brackets, other brackets) and `layout` (HTML tags such as `<br>`). An unclosed `¬` turns the rest into footnote; an unclosed `[` stays author text.
2. **Spans** are cut from author ranges only, broken after `.؟!:؛` and newlines; spans under 5 words are merged, spans over 60 words split. Ids `s001…`, absolute character offsets into the raw file.
3. **Windows** are one ayah; an ayah above 110 spans is packed greedily into parts (`24_11_p01…`), cutting at the last `<br>` or newline before the cap. Each window stores its spans, apparatus ranges, `window_text`, `source_sha256` and the selection rule.
4. **Markers** are regex/phrase hits per span, grouped by family (QURAN, HADITH, ISNAD, SAHABA, TABIIN, LUGHA, QIRAAT, NUZUL, SIRA, ISRAILIYYAT, RAY, EDITOR); they are hints to the checker, never labels.
5. **Packets** carry the spans with their markers, the editor's footnotes labelled "not the commentator's words", the ten method definitions, the certainty rules and the output schema. They contain no model text and no personal data.
6. **Moves** (model output) refer to text by span ids only: `move_id, span_ids, primary, secondary, content_tags, certainty, evidence_span_ids, author_verdict_span_ids, references, alternatives, rationale_ar`. Verified moves add `route, score, flags, reason_code`. See [`DATA_FORMAT.md`](DATA_FORMAT.md) and `schema/annotation.schema.json` for the approved-record schema.
7. **Published units** (`published.json`): `kind: mirqah-published`, `schema 1`, `version`, `published_at`, `counts`, `units[{id, tafsir, window, ayah, move, primary, secondary, certainty, content_tags, span_ids, evidence_span_ids, references, start, end, text, slice, source_file, source_sha256, approved_at}]`, `windows` (source slices), `methods_ar`, `note`, `notice_ar`. No reviewer names, e-mails, scores, flags or rationales.

### 5. Integrity guarantees

- Text is read as bytes and decoded as UTF-8; it is never normalised, re-typed or "corrected" (the pilot found «القرن» for «القرآن» in one digital edition — it stays as in the source and is flagged for the specialist).
- Every derived range must tile its text with no gaps or overlaps (`assert_tiling` raises otherwise).
- Strict fidelity check for An-Nur: 76,773 / 76,773 ([`EVALUATION.md`](EVALUATION.md) §2). CI refuses pull requests that modify, delete or rename anything under `data/**/{raw,layers,spans,windows}`.
- A move that crosses an editor's footnote is compared span by span against the source; the public site re-reads every published unit from the pinned text on load and marks nothing it cannot match.

### 6. Licence and permitted use

- **Text and derived data:** CC BY 4.0 as stated on the dataset card; attribution wording «Tafsir Center for Quranic Studies (https://tafsir.net)». This repository restricts itself to **non-commercial research and education** and asks Tafsir Center before any commercial redistribution (`ATTRIBUTION.md`). Not a letter of the text was changed.
- **Code:** MIT (`LICENSE`), covering code only.
- **«آيات» (King Saud University):** linked as a reading reference from each passage; no text copied.
- **Quran text:** the public reader shows the ayah as it appears in the pinned tafsir text; it is not a mushaf and must not be cited as one.

### 7. Personal data

None in `data/`. The console stores the names and e-mails of registered team members and their decisions (see [`../SECURITY.md`](../SECURITY.md)); none of it enters packets, model prompts or public snapshots. Demo mode uses invented people marked «(تجريبي)».

### 8. Known issues and limitations

- Print edition of all four tafsirs unidentified (digital editions only).
- Editor's apparatus is dense (155 k characters; 1,914 inter-span gaps hold a footnote) — the main source of boundary problems for models.
- Digitisation artefacts preserved as-is: a verse reference split by a tag («[يو<br>سف: 18]», al-Tabari 24:11), mixed CR/LF line endings in Ibn Kathir, `<br>` layout tags in al-Tabari only.
- A specialist reported text missing from the digital source in one al-Tabari window (24:11 part 2); under review against the printed edition.
- 12 windows are capped at 110 spans; a long ayah is therefore reviewed in parts and context across parts is shown by the console, not by the file.
- Packets carry no `C_*` content-type codes although the output schema has `content_tags`; content typing is not evaluated.
- `data/raw/manifest.json` lists the pilot files and the DB; the An-Nur raw files are pinned through the DB hash and the per-file `source_sha256`, not through manifest entries.
- The dataset card permits commercial use; this repository is deliberately more conservative (see §6).

### 9. Maintenance

Adding a surah: `python3 src/run_surah.py --surah <n> --base data/<name>/<tafsir>` per tafsir, then the strict checker, then a pull request (data paths are reviewed by the owner — `CODEOWNERS`). Nothing under `data/` is edited by hand; models write only under `moves/<annotator>/`; approvals live in the console and reach git only through `src/import_reviews.py --out-root` by a team decision (`docs/DECISIONS_PROPOSAL.md`).

---

## العربية

### ١. ما هذه البيانات

أربعة تفاسير لسورة **النور (٢٤)، الآيات ١–٦٤**، قطّعها الكود إلى أجزاء ونوافذ ليشير النموذج إلى النص بالمعرّف ويتحقق الإنسان من كل وحدة في المصدر. يحوي المستودع **النص المثبَّت وكل ما اشتُق منه بكود حتمي**، ولا يحوي اقتراحات النماذج لسورة النور (في مجلد عمل اللوحة) ولا قرارات البشر (في قاعدة بيانات اللوحة)؛ وما اعتمده المتخصصون ونشره المشرف العام يُقدَّم لقطةً مرقّمة.

الطبقات: النص الخام (`raw/`) ← الطبقات (كلام المؤلف / جهاز المحقق / تنسيق HTML، `layers/`) ← الأجزاء (`spans/`) ← النوافذ (`windows/`، نافذة لكل آية أو أجزاء `_p01…` فوق ١١٠ جزءاً) ← العلامات (`markers/`) ← الحزم (`packets/`، ما يستلمه النموذج) ← الحركات (مخرجات النموذج، في مجلد عمل اللوحة لا في المستودع) ← القرارات (قاعدة اللوحة) ← اللقطة المنشورة (`/public/v1/published.json`، بصمة SHA-256 لكل إصدار).

### ٢. التكوين

| التفسير | الجدول | النوافذ | آيات مقسّمة | الأجزاء | الأحرف | منها جهاز المحقق |
|---|---|---:|---:|---:|---:|---:|
| الطبري (ت ٣١٠هـ) | `tafsir_tabary` | ٨٤ | ١١ ← ٣١ | ٤٬٤٣٥ | ٣٥٤٬٨٢٥ | ٦٩٬٨١٢ |
| ابن كثير (ت ٧٧٤هـ) | `tafsir_katheer` | ٨٢ | ١٠ ← ٢٨ | ٢٬٨١٧ | ٢٩٤٬٩٤٨ | ٥٦٬١٤٨ |
| البغوي (ت ٥١٦هـ) | `tafsir_baghawy` | ٦٦ | ١ ← ٣ | ١٬١٢٩ | ١٩١٬١٦١ | ٢٧٬٤٥٠ |
| السعدي (ت ١٣٧٦هـ) | `tafsir_saadi` | ٦٤ | ٠ | ٨٦٤ | ٧٣٬٥٨٥ | ١٬٨٣٣ |
| **المجموع** | | **٢٩٦** | ٢٢ ← ٦٢ | **٩٬٢٤٥** | **٩١٤٬٥١٩** | ١٥٥٬٢٤٣ |

١٬٦٥٦ ملفاً أُضيفت في إيداع واحد (`abc9a0f`، ٣ أكتوبر ٢٠٢٦) وجُمّدت منذئذ. أكبر نافذة: البغوي ٢٤:٧ (١٧٬٣٢٨ حرفاً)؛ ١٢ نافذة عند سقف ١١٠ أجزاء بالضبط. الأجزاء لا تتداخل؛ والفجوات بينها (٢٬٤٠٥) حواشي محقق (١٬٩١٤) أو أقواس أو وسوم `<br>`. التجربة الأولى (ثلاث آيات) محفوظة في `data/v2/` و`data/multi/`، وسورة الأنفال محضَّرة في `data/anfal/` (٣٢٥ نافذة بلا اقتراحات).

### ٣. المصدر والجمع

- **مجموعة البيانات:** مركز تفسير للدراسات القرآنية، `tafsircenter/tafsir-mcp-data` على Hugging Face — ملف `quran.db` (٢٣٤٬٣٥٢٬٦٤٠ بايتاً)، مراجعة `dbbfa775…` بتاريخ ٢٠٢٦-٠٥-١٣، جُلب في ٢٠٢٦-٠٩-٢٨، بصمته `10e61f61…cc27` (`data/raw/manifest.json`). القاعدة نفسها غير مودعة؛ وكل نافذة تحمل بصمة ملفها الخام، والفاحص الصارم يقارن بصمة القاعدة قبل القراءة.
- **الاستخراج:** `src/run_surah.py --surah 24` مرة لكل تفسير، دون أي استدعاء نموذج. النص الخام هو صف القاعدة ببايتات UTF-8 يُقرأ دون تحويل أسطر.
- **مصادر التجربة الأولى:** المجموعة نفسها، ونسخة ثانية مستقلة لابن كثير من واجهة quran.com للمقارنة فقط (لا تُعاد نشرها).
- **الطبعة المطبوعة:** غير محددة في المصدرين؛ مسجَّلة «قيد التحقق» في `ATTRIBUTION.md`.

### ٤. قواعد المعالجة (كلها حتمية)

١. **الطبقات:** ثلاثة أنواع تغطي النص بلا فجوة: كلام المؤلف، وجهاز المحقق (الحواشي `¬…¥`، وإحالات الآيات بين أقواس، وغيرها من الأقواس)، والتنسيق (وسوم HTML مثل `<br>`).
٢. **الأجزاء** تُقطع من كلام المؤلف وحده بعد `.؟!:؛` والأسطر؛ ما دون ٥ كلمات يُدمج وما فوق ٦٠ كلمة يُقسم؛ معرّفات `s001…` وإزاحات حرفية مطلقة في الملف الخام.
٣. **النوافذ** آية واحدة؛ والآية فوق ١١٠ أجزاء تُقسم أجزاءً (`24_11_p01…`) عند آخر `<br>` أو سطر قبل السقف. تحمل كل نافذة أجزاءها ومدى الجهاز ونصها وبصمة المصدر وقاعدة الاختيار.
٤. **العلامات** إصابات عبارات/تعابير منتظمة لكل جزء مجمَّعة بالعائلة؛ تلميحات للفاحص لا وسوماً.
٥. **الحزم** تحمل الأجزاء بعلاماتها، وحواشي المحقق موسومة «ليست كلام المفسِّر»، وتعريفات المناهج العشرة، وقواعد اليقين، ومخطط الإخراج. لا نص نموذج فيها ولا بيانات شخصية.
٦. **الحركات** (مخرج النموذج) تشير إلى النص بمعرّفات الأجزاء فقط؛ والمحقَّقة منها تضيف التوجيه والدرجة والأعلام ورمز السبب. انظر [`DATA_FORMAT.md`](DATA_FORMAT.md) و`schema/annotation.schema.json`.
٧. **الوحدات المنشورة** (`published.json`): نوع اللقطة ومخططها وإصدارها وتاريخها وأعدادها ووحداتها (المعرّف، التفسير، النافذة، الآية، الحركة، المنهج، اليقين، معرّفات الأجزاء والشاهد، الإحالات، البداية والنهاية، النص، الملف المصدر وبصمته، وقت الاعتماد) ومقاطع النوافذ وأسماء المناهج والملاحظة. لا أسماء مراجعين ولا بريد ولا درجات ولا أعلام ولا تعليلات.

### ٥. ضمانات السلامة

- يُقرأ النص بايتات ويُفكّ UTF-8 ولا يُطبَّع ولا يُعاد كتابته ولا «يُصحَّح» (وجدت التجربة الأولى «القرن» موضع «القرآن» في نسخة رقمية — تبقى كما في المصدر ويُنبَّه المتخصص).
- كل مدى مشتق يجب أن يغطي نصه بلا فجوة ولا تداخل وإلا رُفض.
- الفحص الصارم لسورة النور ٧٦٬٧٧٣ / ٧٦٬٧٧٣ ([`EVALUATION.md`](EVALUATION.md) §٢)؛ وCI يرفض أي طلب دمج يمس `data/**/{raw,layers,spans,windows}`.
- الحركة التي تعبر حاشية تُقارَن جزءاً جزءاً؛ والموقع العام يعيد قراءة كل وحدة منشورة من النص المثبَّت عند الفتح ولا يعلّم ما لا يطابقه.

### ٦. الترخيص والاستعمال

- **النص والبيانات المشتقة:** CC BY 4.0 كما في بطاقة المجموعة، بالنسبة «Tafsir Center for Quranic Studies (https://tafsir.net)». ويقصر هذا المستودع نفسه على **البحث والتعليم غير التجاريين** ويستأذن مركز تفسير قبل أي إعادة توزيع تجاري (`ATTRIBUTION.md`). لم يُغيَّر حرف من النص.
- **الكود:** MIT (`LICENSE`)، للكود وحده.
- **«آيات» (جامعة الملك سعود):** رابط للقراءة من كل موضع؛ لا نص منقول.
- **نص القرآن:** يعرض القارئ الآية كما وردت في نص التفسير المثبَّت؛ وهو ليس مصحفاً ولا يُستشهد به مصحفاً.

### ٧. البيانات الشخصية

لا شيء منها في `data/`. تحفظ اللوحة أسماء أعضاء الفريق المسجلين وبريدهم وقراراتهم (انظر [`../SECURITY.md`](../SECURITY.md))؛ ولا يدخل شيء منها في الحزم ولا في موجّهات النماذج ولا في اللقطات العامة. وضع المحاكاة يستعمل أشخاصاً مخترعين موسومين «(تجريبي)».

### ٨. المشكلات المعروفة والحدود

- الطبعة المطبوعة للتفاسير الأربعة غير محددة (نسخ رقمية فقط).
- جهاز المحقق كثيف (١٥٥ ألف حرف؛ ١٬٩١٤ فجوة بين الأجزاء فيها حاشية) — المصدر الأول لمشكلات الحدود عند النماذج.
- آثار الرقمنة محفوظة كما هي: إحالة آية مقطوعة بوسم («[يو<br>سف: 18]»، الطبري ٢٤:١١)، وأسطر CR/LF مختلطة في ابن كثير، ووسوم `<br>` في الطبري وحده.
- أبلغ متخصص عن نص ناقص في المصدر الرقمي في نافذة من الطبري (٢٤:١١ الجزء ٢)؛ قيد المراجعة على المطبوع.
- ١٢ نافذة عند سقف ١١٠ أجزاء؛ فتُراجَع الآية الطويلة أجزاءً، والسياق عبر الأجزاء تعرضه اللوحة لا الملف.
- الحزم لا تحمل رموز `C_*` لنوع المحتوى مع أن مخطط الإخراج فيه `content_tags`؛ فنوع المحتوى غير مقيَّم.
- `data/raw/manifest.json` يسجّل ملفات التجربة الأولى والقاعدة؛ وملفات النور الخام مثبَّتة ببصمة القاعدة وبصمة كل ملف في النوافذ لا بمدخلات في البيان.
- بطاقة المجموعة تجيز الاستعمال التجاري؛ وهذا المستودع أكثر تحفظاً عمداً (§٦).

### ٩. الصيانة

إضافة سورة: `python3 src/run_surah.py --surah <n> --base data/<name>/<tafsir>` لكل تفسير، ثم الفاحص الصارم، ثم طلب دمج (مسارات البيانات يراجعها المالك — `CODEOWNERS`). لا يُحرَّر شيء تحت `data/` يدوياً؛ النماذج لا تكتب إلا تحت `moves/<annotator>/`؛ والاعتمادات في اللوحة ولا تصل إلى git إلا عبر `src/import_reviews.py --out-root` بقرار الفريق.
