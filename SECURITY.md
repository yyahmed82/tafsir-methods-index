# Security policy — سياسة الأمن · مِرْقاة / Mirqah

Status 6 October 2026. [English](#english) · [العربية](#العربية)

---

## English

### Reporting a vulnerability

Please report privately — do not open a public issue for a security problem.

1. GitHub → **Security** → **Report a vulnerability** (private advisory) on `yyahmed82/tafsir-methods-index`, or
2. e-mail the repository owner (`CODEOWNERS`; the address is in the Git history), subject `mirqah security`.

Include the URL or file, the steps, and what you observed. Acknowledgement within 72 hours; a fix or a mitigation before any public note. Testing against `console.mirqah.app` is welcome as long as it stays read-only (the judges' link is read-only by design) and does not touch other users' sessions or send mail.

### What runs where

| Component | Where | Exposure |
|---|---|---|
| Committee console (FastAPI + SQLite) | one Ubuntu server, `127.0.0.1:8800`, reached only through a Cloudflare Tunnel (`cloudflared` dials out; no inbound ports) | `https://console.mirqah.app`, sign-in required; `/judges` opens a read-only guest session when enabled |
| Public reader (static) | Cloudflare Worker `mirqah` serving `site/` | `https://mirqah.app`, no login, no cookies |
| Model engine (Ollama) | the team's machine, bound to its localhost, reached by the server over Tailscale | not on the public internet; the server never runs a model |
| Local installs (`install.sh`) | the user's own machine, `127.0.0.1` by default | nothing leaves the machine; mail in mock mode |

### Authentication and sessions (`console/auth.py`, `console/app.py`)

- Sign-in by a **one-time e-mail code**: 6 digits (configurable 4–8), valid 10 minutes, 5 attempts then the code is locked, resend after 60 s. Only the HMAC-SHA256 of `email:code` is stored, keyed by a local pepper. The reply is identical for unknown e-mails (unknown attempts are audited).
- Sessions: `secrets.token_urlsafe(32)`, stored hashed with IP and user agent; cookie `mirqah_session` is `HttpOnly`, `SameSite=Strict`, `Secure` in production; lifetime 12 h (1–72); guests 4 h at most. Logout, deactivation, role loss and an admin endpoint revoke sessions.
- CSRF: every state-changing `/api/` call must carry the header `x-mirqah: 1`.
- In-app rate limits: 20 code requests / 10 min per IP and 5 per e-mail; 30 verifications / 10 min per IP; 10 guest sign-ins / 10 min per IP. A Cloudflare WAF rate-limit rule covers `/api/auth/` in front of that.
- Roles: `super_admin` (all 14 permissions), `committee_operator`, `specialist`, `viewer`, plus custom roles. **Only the specialist role can decide on a unit; only `publish_units` (super admin by default) can publish.** Users can grant only roles and permissions they hold; system roles cannot be edited; the last super admin cannot be removed.
- "View as user" (super admins): read-only, every write answers 423, start and stop are audited under the super admin.
- Demo mode: separate database, invented people marked «(تجريبي)», every write answers 423.
- Interactive API docs are disabled (`docs_url=None`).

### Data the console stores

`VAR_DIR/console.db` (`/var/lib/mirqah` on the server, `console/var/` locally): users (name, e-mail, roles, language, active flag, last login), hashed one-time codes, hashed sessions (IP, user agent), settings, languages and translations, tasks and step logs, daily reports, **decisions** (tafsir, window, move, decision, source-compared flag, note, error type), assignments, publications (version, SHA-256, note), the mail outbox and an **append-only audit log** (no code path updates or deletes audit or decision rows). No tafsir text, tags or approvals of record live in the database: the pinned text is in git, approvals become versioned snapshots.

- Backups: nightly 03:15 (online SQLite backup, gzip, `umask 077`, `/var/backups/mirqah`, 14 days). The secret key is backed up alongside; published snapshots and the demo database are not.
- Retention: nothing is purged automatically yet; users are deactivated, not deleted.
- Mail: in **mock mode** (local installs) nothing leaves the machine and the code is shown on screen and written to the outbox; in production the code is never shown on screen and the outbox keeps a masked copy (`••••••`). Mails never carry tafsir text, tags or approvals.
- Public snapshots carry no reviewer names or e-mails; the public endpoints are `published.json`, `languages.json`, `i18n/<code>.json` and `manifest.json` only (CORS `*`, `noindex`).

### Secrets

- No secret is in this repository or its history (scanned 6 Oct 2026 for SMTP keys, private keys, cloud and token patterns; only fake test values exist in `tests/`). `.gitignore` excludes `.env`, `.env.*`, `*.key`, `quran.db` and `console/var/`.
- The pepper for codes and tokens is a 32-byte file `VAR_DIR/secret.key` (0600) created on first start — there is no `MIRQAH_SECRET_KEY` variable to leak.
- On the server, secrets live only in `/etc/mirqah/mirqah.env` (root:mirqah 0640): `MIRQAH_SMTP_PASSWORD`, optionally `LLM_API_KEY` (hosted models need a team decision first). They are written with `sudo mirqah set-env KEY` (hidden prompt) and never through the web UI, chat or CI. `settings-show` and `GET /api/settings` redact the SMTP password; the audit log records `password (secret)`, never the value. Model endpoints are hidden from users without `run_tasks`.

### Transport and headers

- TLS terminates at Cloudflare ("Always use HTTPS", TLS ≥ 1.2); the console sends `Strict-Transport-Security: max-age=31536000` when running behind it, answers unknown hosts with 421, reads the client IP from `CF-Connecting-IP` only when `MIRQAH_PROXY=cloudflare`, and sets `Cache-Control: no-store` on every `/api/` response.
- Console headers: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, CSP `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'`.
- Public site headers (`site/_headers`): the same family plus `Permissions-Policy: camera=(), microphone=(), geolocation=()`; `connect-src` allows `https://console.mirqah.app` for the live snapshot only.
- Server: systemd sandbox (`NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome`, empty capability set, `UMask=0077`), fail2ban, unattended upgrades; `uvicorn` with `server_header=False`.

### Model engine and what a model sees

- Production inference is local (Ollama on the team's machine over Tailscale); no third-party API is called. The `hosted` runtime exists in the code but is off, needs `LLM_API_KEY` in the server environment and a team decision.
- A model receives the **packet** only: the window's spans (pinned source text), their deterministic markers, the editor's footnotes labelled as such, the ten method definitions, the certainty rules and the output schema; on arm B also the commentator's profile card and taught examples that hold span ids and labels, never names, e-mails or notes. **No personal data is in any prompt.** The model's reply is kept only in schema fields and bound to the packet hash.

### Integrity and audit

- Source text is pinned by SHA-256 (`data/raw/manifest.json`, `source_sha256` in every window) and re-verified at review time (`/source` check), at publish time and by the public site on load.
- Published snapshots are canonical JSON with a SHA-256 per version; the ETag is that hash; rollback is making an earlier version live again.
- Audited events include every sign-in attempt and guest login, mode switches, view-as start/stop/denied, decisions, assignments and reminders, task create/cancel/retry, report generation and mailing, publish and make-live, user/role/settings/language changes, demo seed/clear and SMTP/LLM tests.

### Supply chain and deploys

- Deploys are **pull-based and CI-gated**: the server fetches GitHub every 2 minutes, installs a commit only when the `test` check is green, verifies `/api/public` reports the new release and rolls back on a failed health check (`deploy/server/mirqah-deploy`, 5 releases kept). No deploy keys, no inbound ports, no secrets in CI. `CODEOWNERS` requires the owner's review on every file.
- Pins: `jsonschema==4.26.0`, `playwright==1.63.0`; the console requirements use lower bounds (`fastapi>=0.110`, `uvicorn>=0.29`); GitHub Actions are pinned by major tag.

### Known gaps (tracked)

- No automatic retention/purge of sessions, codes, audit rows or outbox entries.
- Console dependencies are not fully pinned and there is no lock file; Actions are not pinned by SHA.
- In mock mode the one-time code is also written to the application log (local installs only).
- Users with `view_tasks` (guests included, when guest access is on) see reviewer **names** and notes in the review history; e-mails are never shown.
- The method-specialist verdict (A/B arm B) is visible on the review screen; fix pending.
- Private vulnerability reporting must be switched on in the repository settings for route 1 above to work.

---

## العربية

### الإبلاغ عن ثغرة

أبلِغ بشكل خاص ولا تفتح مشكلة عامة: من GitHub ← **Security** ← **Report a vulnerability** في `yyahmed82/tafsir-methods-index`، أو بريد مالك المستودع (`CODEOWNERS`؛ العنوان في سجل Git) بعنوان `mirqah security`. اذكر الرابط أو الملف والخطوات وما لاحظته. الردّ خلال ٧٢ ساعة؛ والإصلاح أو التخفيف قبل أي إعلان. الاختبار على `console.mirqah.app` مرحَّب به ما دام للقراءة فقط (رابط المحكّمين للقراءة فقط بالتصميم) ولا يمس جلسات الآخرين ولا يرسل بريداً.

### ما يعمل أين

| المكوّن | المكان | التعرّض |
|---|---|---|
| لوحة اللجنة (FastAPI + SQLite) | خادم Ubuntu واحد على `127.0.0.1:8800`، لا يُوصل إليه إلا عبر نفق Cloudflare (لا منافذ واردة) | `https://console.mirqah.app` بتسجيل دخول؛ `/judges` يفتح جلسة ضيف للقراءة فقط عند تفعيلها |
| القارئ العام (ثابت) | Cloudflare Worker يقدّم `site/` | `https://mirqah.app`، بلا دخول ولا كعكات |
| محرّك النماذج (Ollama) | جهاز الفريق، مربوط بمضيفه المحلي، يصل إليه الخادم عبر Tailscale | ليس على الإنترنت العام؛ الخادم لا يشغّل نموذجاً |
| التثبيت المحلي (`install.sh`) | جهاز المستخدم على `127.0.0.1` | لا يخرج شيء من الجهاز؛ البريد في وضع المحاكاة |

### المصادقة والجلسات

- الدخول **برمز بريدي لمرة واحدة**: ٦ أرقام (٤–٨)، صالح ١٠ دقائق، ٥ محاولات ثم يُقفل الرمز، إعادة إرسال بعد ٦٠ ثانية. لا يُحفظ إلا HMAC-SHA256 لـ`email:code` بمفتاح محلي. الرد واحد للبريد المجهول (وتُسجَّل المحاولة).
- الجلسات: رمز عشوائي ٣٢ بايتاً يُحفظ مجزّأً مع IP ووكيل المستخدم؛ الكعكة `mirqah_session` بسمات `HttpOnly` و`SameSite=Strict` و`Secure` في الإنتاج؛ العمر ١٢ ساعة (١–٧٢)؛ الضيف ٤ ساعات على الأكثر. الخروج وإيقاف الحساب وفقدان الدور ونقطة إدارية تُلغي الجلسات.
- CSRF: كل طلب مغيِّر للحالة تحت `/api/` يحمل الترويسة `x-mirqah: 1`.
- حدود المعدل داخل التطبيق: ٢٠ طلب رمز / ١٠ دقائق لكل IP و٥ لكل بريد؛ ٣٠ تحققاً / ١٠ دقائق لكل IP؛ ١٠ دخولات ضيف / ١٠ دقائق لكل IP؛ وأمامها قاعدة WAF في Cloudflare على `/api/auth/`.
- الأدوار: `super_admin` (كل الصلاحيات الأربع عشرة)، `committee_operator`، `specialist`، `viewer`، وأدوار مخصصة. **لا يقرر في وحدة إلا دور المتخصص؛ ولا ينشر إلا من يملك `publish_units` (المشرف العام افتراضياً).** لا يمنح المستخدم إلا ما يملكه من أدوار وصلاحيات؛ أدوار النظام لا تُعدَّل؛ وآخر مشرف عام لا يُحذف.
- «العرض بصفة مستخدم» (للمشرفين العامين): للقراءة فقط، كل كتابة تُجاب بـ423، والبدء والإيقاف مسجَّلان.
- وضع المحاكاة: قاعدة منفصلة وأشخاص مخترعون «(تجريبي)» وكل كتابة تُجاب بـ423. وثائق API التفاعلية معطَّلة.

### ما تحفظه اللوحة

قاعدة `console.db`: المستخدمون (الاسم، البريد، الأدوار، اللغة، الحالة، آخر دخول)، رموز مجزّأة، جلسات مجزّأة (IP، وكيل المستخدم)، الإعدادات، اللغات والترجمات، المهام وسجلات الخطوات، التقارير اليومية، **القرارات** (التفسير، النافذة، الحركة، القرار، علم مقارنة المصدر، الملاحظة، نوع الخطأ)، الإسنادات، الإصدارات (الرقم، البصمة، الملاحظة)، صندوق البريد الصادر، و**سجل تدقيق للإلحاق فقط** (لا مسار في الكود يعدّل صفوف التدقيق أو القرارات أو يحذفها). لا نص تفسير ولا وسوم ولا اعتمادات معتمدة في القاعدة: النص المثبَّت في git، والاعتمادات تصير لقطات مرقّمة.

- النسخ الاحتياطي: ليلياً ٠٣:١٥ (نسخة SQLite حية مضغوطة، `/var/backups/mirqah`، ١٤ يوماً)؛ يُنسخ المفتاح السري معها؛ ولا تُنسخ اللقطات المنشورة ولا قاعدة المحاكاة.
- الاحتفاظ: لا حذف تلقائي بعد؛ المستخدمون يُوقَفون ولا يُحذفون.
- البريد: في **وضع المحاكاة** (التثبيت المحلي) لا يخرج شيء من الجهاز ويظهر الرمز على الشاشة ويُكتب في الصندوق الصادر؛ وفي الإنتاج لا يظهر الرمز على الشاشة ويحتفظ الصندوق بنسخة مقنَّعة. ولا يحمل أي بريد نص تفسير ولا وسوماً ولا اعتمادات.
- اللقطات العامة بلا أسماء مراجعين ولا بريدهم؛ والنقاط العامة هي `published.json` و`languages.json` و`i18n/<code>.json` و`manifest.json` فقط.

### الأسرار

- لا سرّ في المستودع ولا في تاريخه (فُحص في ٦ أكتوبر ٢٠٢٦ لمفاتيح SMTP والمفاتيح الخاصة وأنماط الرموز؛ لا توجد إلا قيم اختبار وهمية في `tests/`). يستثني `.gitignore` ملفات `.env` و`.env.*` و`*.key` و`quran.db` و`console/var/`.
- مفتاح التجزئة ملف `VAR_DIR/secret.key` (٣٢ بايتاً، 0600) يُنشأ عند أول تشغيل؛ لا متغيّر `MIRQAH_SECRET_KEY` يمكن تسريبه.
- على الخادم تعيش الأسرار في `/etc/mirqah/mirqah.env` فقط (root:mirqah 0640): `MIRQAH_SMTP_PASSWORD`، واختيارياً `LLM_API_KEY` (النماذج المستضافة تحتاج قرار الفريق أولاً). تُكتب بـ`sudo mirqah set-env KEY` (إدخال مخفي) لا عبر الواجهة ولا الدردشة ولا CI. تُحجب كلمة SMTP في `settings-show` و`GET /api/settings`؛ ويسجّل التدقيق `password (secret)` لا القيمة. وعنوان محرّك النماذج محجوب عمّن لا يملك `run_tasks`.

### النقل والترويسات

- TLS عند Cloudflare (HTTPS دائماً، TLS ≥ 1.2)؛ ترسل اللوحة `Strict-Transport-Security` خلفه، وتجيب المضيف المجهول بـ421، وتقرأ IP العميل من `CF-Connecting-IP` فقط عند `MIRQAH_PROXY=cloudflare`، وتضع `Cache-Control: no-store` على كل رد تحت `/api/`.
- ترويسات اللوحة: `nosniff` و`X-Frame-Options: DENY` و`Referrer-Policy: same-origin` وسياسة CSP تحصر السكربتات في المصدر نفسه وتمنع التضمين.
- ترويسات الموقع العام (`site/_headers`): العائلة نفسها مع `Permissions-Policy` تمنع الكاميرا والميكروفون والموقع؛ و`connect-src` يسمح بـ`https://console.mirqah.app` للقطة الحية فقط.
- الخادم: صندوق systemd (`NoNewPrivileges` و`ProtectSystem=strict` و`ProtectHome` وبلا صلاحيات و`UMask=0077`)، وfail2ban، وتحديثات تلقائية.

### محرّك النماذج وما يراه النموذج

- الاستدلال في الإنتاج محلي (Ollama على جهاز الفريق عبر Tailscale)؛ لا تُستدعى أي واجهة خارجية. وضع `hosted` موجود في الكود لكنه معطَّل ويحتاج `LLM_API_KEY` في بيئة الخادم وقرار الفريق.
- لا يستلم النموذج إلا **الحزمة**: أجزاء النافذة (النص المثبَّت) وعلاماتها الحتمية وحواشي المحقق موسومة وتعريفات المناهج وقواعد اليقين ومخطط الإخراج؛ وفي الذراع ب بطاقة المفسِّر وأمثلة معلَّمة تحمل معرّفات أجزاء ووسوماً لا أسماء ولا بريداً ولا ملاحظات. **لا بيانات شخصية في أي موجّه.** ويُحفظ من الرد حقول المخطط فقط مربوطة ببصمة الحزمة.

### السلامة والتدقيق

- النص مثبَّت بـSHA-256 (`data/raw/manifest.json` و`source_sha256` في كل نافذة) ويُعاد التحقق منه عند المراجعة (فحص `/source`) وعند النشر وعند فتح الموقع العام.
- اللقطات المنشورة JSON قانوني ببصمة SHA-256 لكل إصدار؛ وETag هو البصمة؛ والتراجع إعادة إحياء إصدار سابق.
- تُسجَّل في التدقيق: كل محاولة دخول ودخول ضيف، وتبديل الوضع، والعرض بصفة مستخدم (بدء/إيقاف/رفض)، والقرارات والإسنادات والتذكيرات، وإنشاء المهام وإلغاؤها وإعادتها، وتوليد التقارير وإرسالها، والنشر والإحياء، وتغييرات المستخدمين والأدوار والإعدادات واللغات، وبذر المحاكاة ومسحها، واختبارات SMTP والمحرّك.

### سلسلة التوريد والنشر

- النشر **بالسحب ومشروط بـCI**: يجلب الخادم GitHub كل دقيقتين، ولا يثبّت إيداعاً إلا بعد نجاح فحص `test`، ويتحقق أن `/api/public` يعلن الإصدار الجديد، ويتراجع تلقائياً عند فشل فحص الصحة (`deploy/server/mirqah-deploy`، خمسة إصدارات محفوظة). لا مفاتيح نشر ولا منافذ واردة ولا أسرار في CI. و`CODEOWNERS` يوجب مراجعة المالك لكل ملف.
- التثبيت: `jsonschema==4.26.0` و`playwright==1.63.0`؛ متطلبات اللوحة بحدود دنيا (`fastapi>=0.110` و`uvicorn>=0.29`)؛ وإجراءات GitHub مثبَّتة بالوسم الرئيسي.

### الثغرات المعروفة (متابَعة)

- لا حذف تلقائي للجلسات والرموز وسجل التدقيق والصندوق الصادر.
- تبعيات اللوحة غير مثبَّتة بالكامل ولا ملف قفل؛ والإجراءات غير مثبَّتة بالبصمة.
- في وضع المحاكاة يُكتب الرمز أيضاً في سجل التطبيق (التثبيت المحلي فقط).
- من يملك `view_tasks` (ومنهم الضيف عند تفعيل الضيوف) يرى **أسماء** المراجعين وملاحظاتهم في سجل المراجعة؛ ولا يظهر البريد أبداً.
- حكم أخصائي المنهج (الذراع ب) ظاهر في شاشة المراجعة؛ الإصلاح قيد العمل.
- يجب تفعيل الإبلاغ الخاص عن الثغرات في إعدادات المستودع ليعمل المسار الأول أعلاه.
