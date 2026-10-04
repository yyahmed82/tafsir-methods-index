# مهارات المشروع والمهارات المساندة (Skills)

دليل المهارات المعتمدة لفريق «مِرْقاة» لتمكين وكلاء الذكاء الاصطناعي (Claude Code / Codex) من تنفيذ مهام المشروع بدقة واتساق هندسي كامل.

## ١. مهارات المشروع المضمّنة (Project Skills)

- **فهرسة مناهج التفسير (`fahras-tafsir-indexing`)**: `docs/team/skills/fahras-tafsir-indexing/SKILL.md` — تشغيل سلسلة الفهرسة بوكيلين من عائلتين وفاحص حتمي (٧٥) ورئيس لجنة (٨٥) على نص التفسير المثبّت، والاعتماد للمتخصص البشري.
- **بناء العرض التقديمي النهائي (`mirqah-deck-build`)**: `docs/team/skills/mirqah-deck-build/SKILL.md` — بناء وتحديث العرض التقديمي الرسمي (`fahras_final_v7.pptx`) عبر `build_final.py` ومعالجة النصوص إجبارياً بـ `fix_bidi.py`، وملء علامات التحديث بالأرقام الحقيقية.
- **تسجيل العرض المرئي للمنتج (`mirqah-demo-recording`)**: `docs/team/skills/mirqah-demo-recording/SKILL.md` — تسجيل الفيديو التعريفي للمنتج (≤ دقيقتين) بمنتج حقيقي وبث حي للطرفية وفق جدول التعليق الصوتي VO v3 وقائمة لقطات Playwright.
- **مراجعة طلبات السحب (`mirqah-pr-review`)**: `docs/team/skills/mirqah-pr-review/SKILL.md` — المراجعة المستقلة العدائية لطلبات السحب والتحقق من الاختبار السلبي وثبات مسارات `data/**` واستيفاء حزمة الفرع وحكم PASS/BLOCK.
- **تدقيق جاهزية الإنتاج (`vibe-coding-project-auditor`)**: `docs/team/skills/vibe-coding-project-auditor/SKILL.md` — تدقيق هندسي لجاهزية المشروع عبر ٧ محاور وخطة إصلاح P0/P1/P2.

## ٢. مهارات خارجية مساندة (External Skills)

تُثبَّت من مصادرها الرسمية عبر أداة المهارات (أوامر وروابط فقط دون نسخ للمحتوى):

- **تصميم الواجهات (`frontend-design`)**:
  - المستودع: [anthropics/skills](https://github.com/anthropics/skills)
  - أمر التثبيت: `npx skills add anthropics/skills@frontend-design`
- **إرشادات واجهات الويب (`web-design-guidelines`)**:
  - المستودع: [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills)
  - أمر التثبيت: `npx skills add vercel-labs/agent-skills@web-design-guidelines`
