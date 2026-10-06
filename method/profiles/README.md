# ملفات منهج المفسرين (الذراع B)

ملف لكل تفسير، مستخلص من الدراسات العلمية التي أرسلها أبو أنس، مع فحص مدونة سورة النور.
تُستعمل في تشغيل «بملف المفسر» فقط؛ التشغيل الأساسي (الذراع A) لا يقرؤها.

| الحقل | ماذا يفعل |
|---|---|
| `card_ar` | نمط العرض عند المفسر — يدخل حزمة المصنّف والمدقّق |
| `golden_rules_ar` | ثماني قواعد قرار — تدخل الحزمة، ويراجعها أبو أنس |
| `families` | قواعد وفخاخ لكل عائلة منهج (للأخصائيين) |
| `lexicon` | علامات حتمية بالكود: `ray_add` صيغ رأي المفسر، `qultu` (`never` أو `author_voice`)، `heading_phrases` عنوان الآية المفسَّرة، `isnad_words_only`، `readers` أسماء القرّاء |
| `status` | `draft` حتى يراجع الفريق القواعد |

## التعديل

1. عدّل الملف على فرع، وارفع `version`.
2. `python -m pytest -q tests/test_profiles.py` (يتحقق من الحقول ومن أن الذراع A لم يتغير).
3. `python src/v2_profiles.py --base data/nur/<tafsir>` يطبع عدد العلامات المحذوفة والمضافة؛ لا تُرفع `markers_profile/` ولا `packets_profile/` (مولّدة).

## English

One methodology profile per tafsir (arm B of the A/B test), built from the four academic
studies plus a scan of the al-Nur corpus. The lexicon only adds the mufassir's own
formulas and removes known false markers; it never edits source text. Reviewer lessons
(`<base>/gold/examples.json`, references only) are added to arm B packets at run time.
