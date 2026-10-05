# تسليم فرع تطبيق تجربة المستخدم — `build/ux-apply`

## ماذا تغيّر ولماذا
أُزيلت نسب الدقة من الرئيسية، وصار الدخول بزرين إلى القراءة ووضع المختص، ووُحِّدت الصياغة، وأُصلح مفتاح الحواشي وطابور المواضع وإبراز الشاهد، ووُسمت الواجهة الكلاسيكية للمقارنة.

## الملفات
- <bdi dir="ltr">src/index_template.html</bdi> و<bdi dir="ltr">src/build_index.py</bdi> — UX-1 وUX-2
- <bdi dir="ltr">src/fahras_v2_template.html</bdi> — UX-3 وUX-4 وUX-5 وUX-6
- <bdi dir="ltr">src/fahras_template.html</bdi> — UX-8 و«اقتراح آلي»
- <bdi dir="ltr">src/app_template.html</bdi> — نفس الصياغة بلا نسب
- <bdi dir="ltr">web/*.html</bdi> مولَّدة · <bdi dir="ltr">tests/test_ux_apply.py</bdi> · هذه الحزمة
- لا <bdi dir="ltr">data/**</bdi>. لا UX-7. عقد الإسناد في الدرج كما هو.

## طريقة الاستخدام
من جذر المستودع، بايثون 3.11+ (لا خيارات لـ <bdi dir="ltr">build_fahras.py</bdi>؛ الأمر هو الملف نفسه):
١. <bdi dir="ltr"><code>python src/build_fahras.py</code></bdi>
٢. <bdi dir="ltr"><code>python src/build_index.py</code></bdi> — إن نقص الخام يُحقن <bdi dir="ltr">web/index_data.json</bdi>
٣. <bdi dir="ltr"><code>python -m http.server 8791 --directory web</code></bdi>
٤. افتح الرئيسية: «افتح وضع القراءة» و«افتح وضع المختص». في القارئ: «اعرض الأصل بجانبه» و«إظهار حواشي المحقق». في المراجعة: طابور المواضع ثم أظهر الشاهد.

الناتج المتوقع للبناء: <bdi dir="ltr"><code>br/source fidelity self-test PASS (12 windows)</code></bdi> و<bdi dir="ltr"><code>data_version=5f124f76aef0</code></bdi>. للرئيسية في هذا الجهاز: حقن JSON القائم.

## كيف تتحقق
- <bdi dir="ltr"><code>python src/build_fahras.py</code></bdi> مرتين ← نفس البايتات
- <bdi dir="ltr"><code>python -m pytest tests/test_ux_apply.py -q</code></bdi> ← نجاح (تخطي Playwright إن غاب)
- <bdi dir="ltr"><code>python -m pytest -q</code></bdi> ← <bdi dir="ltr"><code>164 passed, 2 skipped, 13 subtests passed</code></bdi>
- <bdi dir="ltr"><code>git status --porcelain data/</code></bdi> ← فارغ
- لقطات: <bdi dir="ltr">after-reader-sbs-light-1440.png</bdi> · <bdi dir="ltr">after-reader-sbs-dark-1440.png</bdi> · <bdi dir="ltr">after-reader-sbs-light-375.png</bdi>

## ما لم يُنجز / مخاطر
UX-7 (رأس الجوال) خارج النطاق. أُضيف «اعرض الأصل بجانبه» في القارئ الجديد. لم ندرّب. لم نغيّر وسماً ولا اعتماداً. بناء الرئيسية حقن JSON لأن <bdi dir="ltr">data/raw/quran_com/17_105.txt</bdi> ناقص. مراجعة مستقلة: قيد الانتظار.

## من نفّذ ومن راجع
بناه Cursor grok-4.6. المراجعة: قيد الانتظار.
