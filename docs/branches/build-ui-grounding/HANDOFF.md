# تسليم فرع إسناد الواجهة — `build/ui-grounding`

## ماذا تغيّر ولماذا
صارت قاعدة المسابقة «مسار إجابة من المصادر المعتمدة» ظاهرة في درج الحركة: امتناع واضح، شاهد دقيق، وملاحظة النموذج معزولة عن الدليل. الاعتماد للمتخصص البشري بعد فحص الدلالة.

## الملفات
- <bdi dir="ltr">src/build_fahras.py</bdi> — يقرأ <bdi dir="ltr">REASON_CODES</bdi> و<bdi dir="ltr">COMMITTEE_REASON_CODES</bdi> من العقد ويحقنهما JSON في الصفحة
- <bdi dir="ltr">src/fahras_template.html</bdi> و<bdi dir="ltr">src/fahras_v2_template.html</bdi> — الدرج وبطاقة الدليل
- <bdi dir="ltr">web/fahras.html</bdi> و<bdi dir="ltr">web/reader.html</bdi> — مولَّدان لا يُحرَّران باليد
- <bdi dir="ltr">tests/test_ui_grounding.py</bdi> — فحص الخريطة والعلامات والشاهد
- هذه الحزمة. لا <bdi dir="ltr">data/**</bdi>. لا تعديل على الفاحص أو العقد أو رئيس اللجنة.

## من الشريحة إلى الشاشة

| بند الشريحة | أين في الواجهة |
|---|---|
| هل الدليل كافٍ؟ لا ← امتناع أو إحالة | **G-UI-1**: «بانتظار المتخصص» + معنى الرمز من الخريطة المحقونة؛ إن وُجد <bdi dir="ltr">verified/committee</bdi> يُعرض رمز اللجنة. المرشّح: «مرشّح للمراجعة — ليس اعتماداً». بلا رمز: سطر الانتظار فقط |
| عرض الإجابة ومواضع الاستشهاد | **G-UI-2**: زر «أظهر الشاهد» يضيء <bdi dir="ltr">evidence_span_ids</bdi> فقط، وحكم المؤلف بأسلوب مختلف؛ معرّف مجهول = لا تظليل |
| وجود الاستشهاد لا يثبت صحة الاستنتاج | **G-UI-3/4**: ملاحظة النموذج تحت «غير مُسنَدة، ليست دليلاً»؛ تذييل الدرج: الاعتماد للمتخصص بعد فحص الدلالة |

## طريقة الاستخدام
من جذر المستودع، بايثون 3.11+ (لا خيارات لـ <bdi dir="ltr">build_fahras.py</bdi>؛ الأمر هو الملف نفسه):
١. <bdi dir="ltr"><code>python src/build_fahras.py</code></bdi>
٢. <bdi dir="ltr"><code>python -m http.server 8791 --directory web</code></bdi>
٣. افتح <bdi dir="ltr"><code>http://127.0.0.1:8791/reader.html?mode=review</code></bdi> أو <bdi dir="ltr">fahras.html</bdi> ثم تمييزاً.
٤. اقرأ سطر المسار في أعلى الدرج. اضغط «أظهر الشاهد». اقرأ صندوق الملاحظة ثم التذييل.

الناتج المتوقع للبناء: سطر فيه <bdi dir="ltr"><code>br/source fidelity self-test PASS (12 windows)</code></bdi> و<bdi dir="ltr"><code>data_version=93742a2b286e</code></bdi>.

## كيف تتحقق
- <bdi dir="ltr"><code>python src/build_fahras.py</code></bdi> مرتين ← نفس البصمة بايتاً
- <bdi dir="ltr"><code>python -m pytest tests/test_ui_grounding.py -q</code></bdi> ← <bdi dir="ltr"><code>5 passed</code></bdi>
- <bdi dir="ltr"><code>python -m pytest -q</code></bdi> ← <bdi dir="ltr"><code>148 passed, 2 skipped</code></bdi> (يتخطّيان بلا <bdi dir="ltr">QURAN_DB</bdi>)
- <bdi dir="ltr"><code>git status --porcelain data/</code></bdi> ← فارغ
- لقطات الدرج: <bdi dir="ltr">docs/branches/build-ui-grounding/shots/</bdi>

## ما لم يُنجز / مخاطر
لم ندرّب نموذجاً. لم نغيّر وسماً ولا اعتماداً. البيانات القديمة بلا <bdi dir="ltr">reason_code</bdi> تعرض الانتظار دون سطر الرمز. إن غاب ملف اللجنة لا يُختلق رمز. مراجعة مستقلة: قيد الانتظار (Codex).

## من نفّذ ومن راجع
بناه Cursor grok-4.6-high. المراجعة: قيد الانتظار (Codex).
