# قائمة لقطات الفيديو وأتمتة التسجيل (Shots & Playwright Guide)

دليل لقطات التسجيل المرئي للعرض التجريبي (≤ دقيقتين)، مع معايير التحكم عبر Playwright لكل لقطة لضمان التزامن الدقيق مع التعليق الصوتي المعتمد.

## المعايير العامة للتسجيل
- **المنصة**: منتج حقيقي عامل عبر الرابط الرسمي (`https://mirqah.app` أو الخادم الحقيقي).
- **أبعاد الشاشة (Viewport)**: 1920×1080 بكسل حصراً.
- **السمة (Theme)**: السمة الفاتحة (Light Theme) فقط.
- **وضع الطرفية**: البث الحي (LIVE mode)، وممنوع منعاً باتاً التسجيل في وضع المحاكاة (DEMO mode).
- **حساب التوقيت**: إجمالي المدة المستهدفة 116 ثانية (حد أقصى آمن 118 ثانية لتفادي تجاوز الدقيقتين).

---

## تفاصيل اللقطات وتوجيهات Playwright

### اللقطة ١: شاشة القارئ الرئيسية (٠:٠٠–٠:١٠ — ١٠ ثوانٍ)
- **المسار**: `/web/reader.html`
- **العناصر المستهدفة**: `#brand-logo`, `#reader-view`, عنوان «فهرس مناهج التفسير»، وقائمة اختيار التفسير والآية.
- **إجراءات Playwright**:
  ```python
  page.goto(f"{BASE_URL}/web/reader.html")
  page.wait_for_selector("#brand-logo")
  page.wait_for_selector("#reader-view")
  page.wait_for_timeout(10000)
  ```
- **الملاحظات**: إظهار الصفحة ثابتة وهادئة أثناء افتتاحية التعليق الصوتي.

### اللقطة ٢: تبديل التفسير وتلوين المناهج (٠:١٠–٠:٢٢ — ١٢ ثانية)
- **المسار**: نفس الصفحة (`reader.html`).
- **العناصر المستهدفة**: أزرار التلوين `#reader-dynamic-chips`, ونصوص التفسير الملونة في `#reading-article`.
- **إجراءات Playwright**:
  ```python
  # استعراض قائمة التفاسير الأربعة ثم النقر على تصنيف المنهج
  page.wait_for_selector("#reader-dynamic-chips")
  page.click("#reader-dynamic-chips button:first-child")
  page.wait_for_selector("#reading-article span.highlighted-span")
  page.wait_for_timeout(10000)
  ```
- **الملاحظات**: إبراز تلوين المقاطع بحسب المنهج على النص الأصلي دون أي تعديل حرف.

### اللقطة ٣: بطاقة الدليل ورابط التحقق (٠:٢٢–٠:٣٥ — ١٣ ثانية)
- **المسار**: نفس الصفحة (`reader.html`).
- **العناصر المستهدفة**: أول مقطع ملوّن في `#reading-article`, وظهور `#evidence-card` مع رابط «اقرأ في المصدر».
- **إجراءات Playwright**:
  ```python
  first_span = page.locator("#reading-article span.highlighted-span").first
  first_span.click()
  page.wait_for_selector("#evidence-card")
  page.wait_for_timeout(12000)
  ```
- **الملاحظات**: التأكد من وضوح زر «انسخ الموضع مع المرجع» ورابط «اقرأ في المصدر».

### اللقطة ٤: الانتقال إلى وضع المراجعة (٠:٣٥–٠:٥٠ — ١٥ ثانية)
- **المسار**: نفس الصفحة (`reader.html`).
- **العناصر المستهدفة**: زر الانتقال `#btn-toggle-mode`, ظهور `#review-view`, «طابور المواضع»، واقتراح المصنف.
- **إجراءات Playwright**:
  ```python
  page.click("#btn-toggle-mode")
  page.wait_for_selector("#review-view")
  page.wait_for_selector("#queue-items-container")
  page.wait_for_timeout(14000)
  ```
- **الملاحظات**: التركيز على أن الاقتراح مبني بمعرفات أجزاء النص فقط وليس بنص جديد.

### اللقطة ٥: المقارنة مع المصدر المثبّت (٠:٥٠–١:٠٦ — ١٦ ثانية)
- **المسار**: نفس الصفحة (`reader.html`).
- **العناصر المستهدفة**: اختيار عنصر من الطابور، النقر على `#act-compare`, وظهور لوحة المقارنة `#compare-subpanel`.
- **إجراءات Playwright**:
  ```python
  page.locator("#queue-items-container .queue-item").first.click()
  page.click("#act-compare")
  page.wait_for_selector("#compare-subpanel")
  page.wait_for_timeout(14000)
  ```
- **الملاحظات**: إظهار تطابق النص مع الأصل وبصمة sha256 المثبتة.

### اللقطة ٦: لوحة قرار المتخصص والتعديل (١:٠٦–١:٢٠ — ١٤ ثانية)
- **المسار**: نفس الصفحة (`reader.html`).
- **العناصر المستهدفة**: أزرار تعديل الحدود (`#btn-adj-before`, `#btn-adj-shrink-start`) وأزرار القرار (`#act-approve`, `#act-reject`).
- **إجراءات Playwright**:
  ```python
  page.click("#act-edit")
  page.wait_for_selector("#edit-bounds-panel")
  page.wait_for_timeout(12000)
  ```
- **الملاحظات**: إظهار مرونة التعديل مع التأكيد الصوتي على أن الاعتماد حق حصري للمتخصص البشري.

### اللقطة ٧: بطاقة الحوكمة ودليل الواجهة (١:٢٠–١:٤٨ — ٢٨ ثانية)
- **المسار**: `/web/fahras.html`
- **العناصر المستهدفة**: تبويب «كيف يعمل الموقع» ومخطط تدفق العمل (المصدر المثبت ← اقتراح الوكيلين ← الفاحص الحتمي ← مراجعة المتخصص).
- **إجراءات Playwright**:
  ```python
  page.goto(f"{BASE_URL}/web/fahras.html")
  page.click("#tab-how-it-works")
  page.wait_for_selector("#pipeline-architecture-diagram")
  page.wait_for_timeout(26000)
  ```
- **الملاحظات**: إبراز العقد المؤسسي القابل للاستبدال، مع ظهور سبب الرفض المغلق إن وُجد.

### اللقطة ٨: الشاشة الختامية (١:٤٨–١:٥٦ — ٨ ثوانٍ)
- **المسار**: شاشة المنتج الرئيسية أو بطاقة نصية هادئة.
- **العناصر المستهدفة**: واجهة المتصفح النظيفة مع إبراز شعار «مِرْقاة · فهرس مناهج التفسير».
- **إجراءات Playwright**:
  ```python
  page.wait_for_timeout(8000)
  ```
- **الملاحظات**: التذكير الصوتي الختامي بأن الأرقام أعداد توجيه وليست دقة.
