# مِرْقاة — فهرس مناهج التفسير

منهج المفسّر ظاهراً على نصّه: كل وسم بشاهده وموضعه، تقترحه لجنة وكيلين، ولا يُعتمد إلا بقرار متخصص.

**الفريق 840 · المسار ٠٤ — أدوات المعرفة والتحقق**

## جرّبه الآن

- [القارئ](https://mirqah.app/reader): اختر التفسير، وتصفّح مواضع المنهج وشواهدها.
- [الواجهة الكلاسيكية](https://mirqah.app/fahras.html): النص الأصل بجانب العرض الملوّن.
- [لوحة اللجنة](https://console.mirqah.app): متابعة الاقتراح والتدقيق والإحالة؛ دخول الحكّام للقراءة فقط.

## النطاق

سورة النور: **٦٤ آية × ٤ تفاسير** (الطبري، ابن كثير، البغوي، السعدي) في **٢٩٦ نافذة**. طابق التحقق الحرفي النصَّ المصدر في **76,773 من 76,773 حرفاً**. هذا فحص لسلامة نقل النص وتقسيمه، وليس حكماً على صحة الوسوم.

## كيف يعمل

1. يُثبَّت نص المصدر ببصمة `SHA-256`، ثم تقسّمه الشفرة إلى أجزاء ذات معرّفات.
2. يقترح المصنّف `qwen2.5:14b` الحدود والوسوم والشواهد بمعرّفات الأجزاء فقط؛ يعيد المدقّق الأعمى `gemma3:12b` النظر من عائلة نماذج أخرى. يعمل النموذجان محلياً عبر Ollama.
3. يتحقق رئيس اللجنة، وهو شفرة بقواعد ثابتة، من عتبة الترشيح **85**، واختلاف عائلتي النموذجين، وتطابق بصمتي الحزمة. يخرج **مرشّحاً للمراجعة** أو **إحالة برمز سبب واحد**.
4. تعيد الشفرة بناء النص من الأجزاء المثبّتة وتفحصه حرفاً بحرف. المتخصص البشري وحده يقرّر الاعتماد بعد مراجعة الشاهد والمصدر.

**وكيلان من عائلتين يقترحان، وأخصائيون آليون يمنعون فقط.** لم ندرّب النموذج ولم نعدّل أوزانه؛ نعلّمه بالسياق.

## النتائج

التشغيل الحقيقي المقصود هنا هو **المهمة ٥** في لوحة اللجنة، على النور **٢٤:١١**: **١١ نافذة، ٧٧ خطوة**. نتائج التوجيه من سجل المهمة نفسها:

| الحالة | العدد |
|---|---|
| مرشّح للمراجعة | يُحدَّث من المهمة ٥ |
| إحالة إلى المتخصص | يُحدَّث من المهمة ٥ |

**أعداد توجيه وليست دقة.** لا اعتماد متخصص بعد؛ لا يصبح أي مرشّح معتمداً إلا بقرار بشري موثّق.

## نسخة البداية (قبل ٤ أكتوبر ٢٠٢٦)

هذا المستودع يوثّق العمل السابق قبل ٤ أكتوبر ٢٠٢٦ كما تشترط المسابقة. نسخة البداية هي الالتزام [`ec616f4`](https://github.com/yyahmed82/tafsir-methods-index/tree/ec616f4) بتاريخ ٣ أكتوبر ٢٠٢٦، ٢٢:٢٧ بتوقيت الرياض.

احتوت نسخة البداية، كما يظهر من `git log --first-parent ec616f4` و[README في ذلك الالتزام](https://github.com/yyahmed82/tafsir-methods-index/blob/ec616f4/README.md)، على تجربة ابن كثير المبكرة، وتشغيل لاحق على ثلاث آيات عبر أربعة تفاسير، وواجهة القارئ v2، وإصلاحات التدقيق للبناء الحتمي و`textcore` وحارس CI، وتجهيز نص سورة النور **64×4** و**296 نافذة** مع فحص مطابقة حرفي صارم، وموارد الفريق. أرقام تلك التجارب محفوظة في README عند ذلك الالتزام ولا تُنقل هنا كنسب نتائج حالية.

**تطوّر النطاق:** وصف عرض التسجيل التطبيقَ الأول على سورة الأنفال (تفسير الطبري)؛ وفي أيام التحدي وُسّع النطاق إلى سورة النور بأربعة تفاسير (الطبري، ابن كثير، البغوي، السعدي) لتظهر المقارنة بين المناهج على الآيات نفسها. الفكرة والمنهج والمسار كما هي.

جاءت النسخة السابقة من المستودع العام [fahras-manahij-al-tafsir](https://github.com/drkhaledalrefay-coder/fahras-manahij-al-tafsir)، وهو يوجّه الآن إلى هذا المستودع.

## ما أُنجز في أيام التحدي (٤–٦ أكتوبر)

- عقد الإسناد، [PR #9 في المستودع السابق](https://github.com/drkhaledalrefay-coder/fahras-manahij-al-tafsir/pull/9) (دُمج ٤ أكتوبر ٠٨:٠١).
- رئيس اللجنة، [PR #10 في المستودع السابق](https://github.com/drkhaledalrefay-coder/fahras-manahij-al-tafsir/pull/10) (دُمج ٤ أكتوبر ٠٨:٠٦).
- مهارة الفهرسة، PR #1.
- هوية «مِرْقاة» وروابط المصدر وإمكانية الوصول، PR #2.
- الشعار، PR #4.
- ترخيص MIT ومرجع «آيات»، PR #10.
- `CODEOWNERS` لمراجعة المالك.

قيد الدمج: لوحة اللجنة والمهمة ٥، PR #3؛ عرض رمز الامتناع، PR #5؛ تطبيق تجربة الاستخدام و«اعرض الأصل بجانبه»، PR #14. يمكن التحقق من الفرق عبر [مقارنة نسخة البداية مع main](https://github.com/yyahmed82/tafsir-methods-index/compare/ec616f4...main).

## الأدوات والنماذج

| الاستخدام | الأداة/النموذج |
|---|---|
| تشغيل اللجنة الآن | `qwen2.5:14b` مصنّفاً و`gemma3:12b` مدقّقاً عبر Ollama محلياً |
| تجارب نسخة البداية | DeepSeek v4.1 flash، MiMo v2.6 flash، Codex `gpt-6-sol`، Grok |
| أدوات التطوير | Codex، Cursor/Grok، Gemini/AGY، Claude، Cline |

الإفصاح عن الحقوق: الكود بترخيص MIT؛ النصوص من مركز تفسير بترخيص CC BY 4.0 وفق الشروط في [ATTRIBUTION.md](ATTRIBUTION.md)؛ لا نصوص من «آيات». سجل الأدوات مفصّل في [الإفصاح عن الذكاء الاصطناعي](docs/AI_DISCLOSURE.md).

## المصادر وتوثيقها

النصوص من النسخة الرقمية لمجموعة [مركز تفسير للدراسات القرآنية](https://huggingface.co/datasets/tafsircenter/tafsir-mcp-data)، المثبّتة في مسار المعالجة ببصمة المصدر. لا تحدد وثائق المصدر طبعة مطبوعة للتفاسير الأربعة.

| التفسير | المصدر | الطبعة/النسخة | الترخيص |
|---|---|---|---|
| الطبري | مركز تفسير، `tafsir_tabary` | نسخة رقمية؛ الطبعة المطبوعة: يُستكمل | CC BY 4.0 |
| ابن كثير | مركز تفسير، `tafsir_katheer` | نسخة رقمية؛ الطبعة المطبوعة: يُستكمل | CC BY 4.0 |
| البغوي | مركز تفسير، `tafsir_baghawy` | نسخة رقمية؛ الطبعة المطبوعة: يُستكمل | CC BY 4.0 |
| السعدي | مركز تفسير، `tafsir_saadi` | نسخة رقمية؛ الطبعة المطبوعة: يُستكمل | CC BY 4.0 |

[«آيات» (جامعة الملك سعود)](https://quran.ksu.edu.sa) مرجع قراءة مرتبط، لا يُنسخ نصه. الكود بترخيص [MIT](LICENSE)، أما النص والبيانات المشتقة فتخضع للشروط المفصّلة في [توثيق المصادر والتراخيص](ATTRIBUTION.md)، بما فيها النسب واشتراط الإذن المسبق لإعادة التوزيع التجاري.

## التشغيل محلياً

يتطلب Python 3.11 أو أحدث. من جذر المستودع:

```bash
pip install -r requirements.txt
python src/build_fahras.py
python src/v2_selftest.py
python -m unittest discover -s tests -p "test_*.py"
python -m http.server 8791 --directory web
```

افتح `web/fahras.html` عبر الخادم المحلي. تفاصيل إعادة البناء في [دليل التشغيل](docs/RUN.md)، وتشغيل التصنيف في [دليل الذكاء الاصطناعي](docs/AI_RUN.md). لا يتضمن المستودع قاعدة المصدر `quran.db`؛ يشرح توثيق المصدر طريقة الحصول عليها.

## للمساهمين

اعمل على فرع مستقل ← افتح طلب دمج (PR) ← اجتز CI ← انتظر مراجعة المالك. لا تعدّل `main` ولا تمسّ ملفات `data/` المصدرية أو المشتقة يدوياً. ابدأ بـ[دليل المساهمة](CONTRIBUTING.md)، و[قواعد الوكلاء](AGENTS.md)، و[مهارات الفريق](docs/team/SKILLS.md).

وثائق إضافية: [تعليمات Claude](CLAUDE.md) · [المهام التالية](docs/HANDOFF.md) · [تدقيق المشروع](docs/AUDIT_2026-10-02.md) · [قائمة التسليم](docs/SUBMISSION_CHECKLIST.md) · [سكربت العرض](docs/DEMO_SCRIPT.md) · [الإفصاح عن الذكاء الاصطناعي](docs/AI_DISCLOSURE.md) · [صيغة البيانات](docs/DATA_FORMAT.md).

## English summary

**Mirqah — Tafsir Methods Index** makes a commentator’s method visible at its location in the source text, with a traceable witness for each proposed tag.
Team 840 · Track 4, Knowledge and Verification Tools.
The al-Nur scope covers 64 verses, four tafsirs, and 296 windows; the source text matched in 76,773 of 76,773 characters.
Two different local Ollama model families propose and check span ID based annotations; deterministic code checks the source and routes candidates or referrals.
Task 5 covers al-Nur 24:11, with 11 windows and 77 steps. Its routing counts await the task record and are not accuracy measures.
No specialist approvals have been recorded. Only a human specialist can approve an annotation.
Code is MIT licensed; tafsir text and derived data follow [ATTRIBUTION.md](ATTRIBUTION.md).
