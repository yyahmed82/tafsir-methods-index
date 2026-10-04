# حزمة الفرع `build/ui-polish`

واجهة الفريق «مِرْقاة» على فهرس مناهج التفسير: علامة ووسم منفصلان، وصفّ مصدر واحد فيه قرآنبيديا بعد التحقق، وإصلاح بوابة الوصول. لا وسم جديد ولا اعتماد آلي.

## الملفات

القوالب الخمسة تحت `src/*_template.html`، والصفحات المولَّدة `web/*.html`، و`web/assets/brand/`، و`tests/test_ui_mirqat.py`، وهذه الحزمة. لا `data/**`. لا `src/v2_verify.py`. لا `tests/test_reader_v2.py`.

## ماذا تغيّر

- علامة الفريق «مِرْقاة» ثم فاصل عمودي (`brand-rule`، 1px × 18px) ثم عنوان المنتج «فهرس مناهج التفسير».
- صفّ واحد «اقرأ في المصدر»: الدرر السنية · quran.com · قرآنبيديا (ثانوية بالترتيب لا بالشفافية).
- روابط قرآنبيديا من `web/assets/brand/quranpedia-books.js` فقط، بالنمط `https://quranpedia.app/tafseer/{tabary|katheer|baghawy|saadi}/sura{S}-aya{A}.html`. التحقق بـ Playwright على الآية 24:35: العنوان والفتات يظهران الكتاب والآية؛ اللقطات في `shots/quranpedia_*.png`.
- بوابة UX (Codex): 9 ملاحظات، أُغلقت كلها: زر `#brand-logo` مع `aria-label`؛ أهداف لمس 24px على صف المصدر؛ بلا `opacity` على قرآنبيديا؛ `quran.com` داخل `bdi dir=ltr`؛ `aria-pressed` على تبديل المظهر؛ رموز العلامة موحّدة (`22×28`، `0.95rem`، `--mirqat-brand`).

## طريقة الاستخدام

من جذر المستودع، بايثون 3.11+:

```
python src/build_fahras.py
python src/build_methods.py
python src/build_reconcile.py
python src/build_index.py
python -m http.server 8791 --directory web
```

ثم افتح `http://127.0.0.1:8791/fahras.html` أو `reader.html`. إن نقص `data/raw/quran_com/17_105.txt` يعجز `build_index.py`؛ أعد حقن JSON الموجود في `web/index.html` داخل القالب ولا تلمس `data/`.

القارئ: يختار التفسير والآية، ثم «اقرأ في المصدر». المتخصص: «ابدأ المراجعة» أو زر العلامة في الواجهة الجديدة يعيد وضع القراءة. التبديل ◐ يغيّر الفاتح/الداكن (`aria-pressed`). Tab يصل إلى العلامة وروابط المصدر مع حلقة تركيز.

## كيف تتحقق

```
python src/build_fahras.py
python src/build_methods.py
python src/build_reconcile.py
python -m pytest -q
python docs/branches/build-ui-polish/shots/audit.py
git status --porcelain data/
```

المتوقع: إعادة البناء مرتين بلا فرق؛ `pytest` ينجح (اختباران يُتخطّيان بلا `QURAN_DB`)؛ جدول التدقيق بلا تمرير أفقي وتباين ≥ 4.5؛ لا مخرج تحت `data/`؛ لا مجلد `qa/`.

## ما لم يُنجز

لا تصنيف ولا تحقق آلي ولا اعتماد. لا كتب قرآنبيديا غير الأربعة المُثبتة. لا دفع ولا دمج.

## من نفّذ ومن راجع

بناه Cursor grok-4.6-high. بوابة UX: Codex (9 ملاحظات، أُغلقت). المراجعة البصرية وتحقق عناوين قرآنبيديا: Claude.

