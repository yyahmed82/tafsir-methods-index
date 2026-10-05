# Vibe Code Audit — Mirqah — 2026-10-05

**Checkout:** `c9ae14e` (detached at `origin/build/committee-console`). **Scope:** current repository code and generated public pages, read-only inspection. This is an engineering and submission-risk score, not a measure of indexing accuracy or specialist approval. The October 3 audit scored 6.0/10; its opening correction supersedes its CI-pathspec and rights blockers.

## Executive Verdict

- **Status:** Proof-of-Concept Only under the requested rubric.
- **Composite score:** **4.9/10** (arithmetic mean, 34/7).
- **Submission blockers:** 2 verified P0. Three verified P1 items need attention before the feature freeze.
- **Review limit:** Static code-path inspection. Python was unavailable in this shell, so no Python, API, or browser tests were run. Live DNS, Cloudflare, deployed configuration, current database content, and full Git-history secret exposure are **UNVERIFIED**.

## Composite Score Breakdown

| Dimension | Score | Label | Basis |
|---|---:|---|---|
| 1. Infrastructure & Edge Resilience | 5 | Acceptable | Host, CSRF and CSP guards; local SMTP secret persistence and unverified deployment state. |
| 2. API Design & Network Optimization | 7 | Acceptable | Small bounded console API; no verified N+1 path; static pages remain separate from publication feed. |
| 3. Caching Strategy | 6 | Acceptable | Versioned console assets and public ETag; static site uses a separate five-minute cache. |
| 4. Concurrency, DB & Data Integrity | 2 | Critical | Arm B fails open on missing verdict; demo writes can reach live DB. |
| 5. Authentication & Session Lifecycle | 5 | Acceptable | Specialist-role gate, hashed OTP/session tokens and cookie flags; demo-mode write boundary incomplete. |
| 6. Architecture & Maintainability | 4 | At Risk | The 21k-line console spans many concerns, with inconsistent write-route guards and legacy public views. |
| 7. Tech Stack Suitability | 5 | Acceptable | FastAPI/SQLite fits a small committee, but new console dependencies are lower-bound only and runtime verification was unavailable. |

## Critical Vulnerabilities & Blockers

### P0-1 — Arm B accepts a candidate without a current method-specialist verdict (C-01)

**Path:** `console/runner.py:445-454` checks only classifier and verifier files before running the chair. `src/committee_chair.py:414-421` builds an empty verdict map when the specialist file is absent or stale. `src/committee_chair.py:452-461` vetoes only when `sv is not None`, leaving `evaluate_move()`'s `auto_candidate` unchanged. `src/committee_chair.py:466-475` copies that route to the verified committee move. `tests/test_specialist.py:165-169` explicitly expects a stale specialist file to leave an automatic candidate. **Impact:** a failed, skipped, absent, or stale specialist step can yield an automatic arm-B candidate, violating the grounding contract. Human approval is still required for publication, but the candidate label is wrong and can influence review. **Fix:** for arm B, require a current verdict for each proposer move; route absent, stale, invalid, or non-confirming verdicts to the specialist with a distinct reason. Update the stale/missing tests to assert blocking.

### P0-2 — Demo mode can mutate live settings and users (D-07)

**Path:** `console/app.py:187-203` refuses writes only on routes using `@operational(write=True)`; it switches to `demo.db` only inside that decorator. `console/app.py:1205-1213` settings PATCH and `console/app.py:1042-1055` user creation have no decorator and call `settings.update()` / `db.execute()` directly. `console/db.py:383-399` defaults connections to the live DB outside `db.use("demo")`. `console/app.py:470-483` sets the browser to demo mode, but this does not change the DB context for those routes. The same issue covers profile, roles, languages and translations (`console/app.py:519-527`, `1147-1195`, `1251-1322`). **Impact:** an authorized operator or administrator viewing the simulation can change live state despite the stated read-only boundary. **Fix:** enforce demo read-only for every state-changing request in one server-side dependency or middleware, with narrow, documented exceptions for mode switching and demo seeding; add API tests for each mutating route family.

## Detailed Findings by Dimension

### 1. Infrastructure & Edge Resilience

- **P1 — SMTP password stored as plaintext in SQLite (SEC-01).** `console/settings.py:265-287` merges a submitted SMTP password into the section and JSON-serializes it into `settings.value`; `console/settings.py:156-172` redacts only the API response. `console/mailer.py:65-78` reads it for SMTP login. The deployment instructions already support an environment secret (`deploy/README.md:50-55`). **Impact:** a copied database or backup contains the credential when set through the UI. **Fix:** use the environment secret as the sole production source, reject/remove persisted passwords, migrate existing rows, and rotate any password previously stored there. Local DB/backup contents are **UNVERIFIED**.
- **Verified controls:** `console/app.py:44-65` checks Host, requires a custom header for API mutations and sends CSP/no-store headers; `console/app.py:418-446` rate-limits OTP requests and verification. `console/auth.py:44-54` keeps its limiter in process memory, so behavior across multiple workers is **UNVERIFIED**. The repository search found no tracked `.env` file (`git ls-files`), and no literal Tailscale IPv4 in the inspected deployment lines (`deploy/README.md:85-95`); a complete secret/history scan is **UNVERIFIED**. No secret value is reproduced here.

### 2. API Design & Network Optimization

- **P1 — Console publication has no verified consumer in the checked-in public site.** `console/app.py:930-974` can make a version live and serve `/public/v1/published.json`; `console/publish.py:218-246` builds the snapshot. `netlify.toml:1-4` serves prebuilt `web/`, while the checked-in public builders/pages contain no reference to the publication endpoint (repository search across `web/` and `src/`; `src/build_app.py:21`, `web/index.html:984` show bundled data). `deploy/README.md:72` says the snapshot is what mirqah.app *may* show. **Impact:** pressing Publish in the console does not by itself establish that mirqah.app displays the approved snapshot. **Fix:** implement and test the public-page fetch/build path and release routing, or label the button as snapshot publication until that path exists. Live site behavior and DNS are **UNVERIFIED**.
- Console lists use bounded queries where inspected (`console/app.py:1229-1234`, `console/publish.py:163-167`). No verified N+1 query was found. Load at 10/50/500 active users is **UNVERIFIED**.

### 3. Caching Strategy

- Console assets get immutable caching only with the current version query (`console/app.py:66-72`); published JSON uses a short TTL and ETag (`console/app.py:955-974`). The separate static host caches HTML and JSON for 300 seconds (`netlify.toml:16-26`). **Risk:** the public pages cannot invalidate from a console publication until a consumer path is wired. **Fix:** after integrating publication, use the version/ETag and test update visibility.

### 4. Concurrency, Database & Data Integrity

- **P0-1 and P0-2 above** are the principal data-integrity failures. SQLite transactions are used for version selection and insertion (`console/publish.py:241-246`), while the snapshot file is written first (`console/publish.py:235-241`); a crash can leave an orphan file, a P2 cleanup issue. **Fix:** reconcile orphan snapshot files on startup or publish through a recoverable two-phase process.
- **Grounding cross-check:** `console/runner.py:490-498` records a chair with missing classifier/verifier input as a skipped step with `reason=agent_missing`; it does not run the chair. `console/pipeline.py:330-381` can display `agent_missing` in a read-only preview, but `console/publish.py:57-108` exports only latest human `approve` decisions and move fields; it does not export the preview reason as a tag. The skipped step is shown in task counts (`console/static/app.js:1025-1039`), not counted as a method tag. This part of the contract is **verified in the code path**; runtime behavior is untested.
- **Human approval cross-check:** `console/app.py:817-854` requires `auth.can_decide`, a valid move, and a source-comparison acknowledgment for approve; `console/auth.py:204-210` requires the actual `specialist` role plus permission. `console/publish.py:34-38`, `57-65` selects only the latest `approve` decisions. There is no code path observed that turns an automatic candidate directly into a published approval. The checkbox does not itself prove a comparison occurred; actual specialist practice is **UNVERIFIED**.

### 5. Authentication & Session Lifecycle

- The role requirement resolves the prior issue #9/R-10 concern in this build (`console/app.py:817-831`, `console/auth.py:204-210`). `console/auth.py:106-113`, `213-245` stores hashed tokens and revokes them server-side on logout; cookies are HttpOnly with SameSite and conditional Secure (`console/app.py:140-149`, `478-480`; `console/config.py:28-34`). OTP request/verify endpoints have bounds (`console/app.py:418-446`, `console/auth.py:145-168`).
- Demo mode remains a P0 authorization boundary because authenticated write routes do not all share its guard (`console/app.py:187-203`, `1205-1213`). The default mock mail setting displays test codes locally only outside production (`console/settings.py:43-50`, `console/auth.py:99-103`); whether production flags are set in the live service is **UNVERIFIED**.

### 6. Architecture & Maintainability

- **P1 — Public wording rule still fails on legacy pages.** Generated `web/app.html:940-941`, `1161-1164` presents percentage/quality claims; `web/index.html:1155-1164` dynamically renders three percentages from its bundled summary at `web/index.html:984`. The source is `src/app_template.html:940-941`, `1161-1164` and `src/build_index.py` for the old index. **Impact:** a judge opening either public route sees claims the current wording rule forbids. **Fix:** remove the percentage presentation from source templates/builders and rebuild generated pages through their scripts. Do not edit `web/*.html` by hand. The public `web/fahras.html` scan found no comparable percentage display outside its embedded data.
- Wording checks: `console/static/i18n/ar.json:88`, `325` correctly uses «الوكيلان» for the classifier/verifier pair. Search found no user-facing claim that model weights were trained, and no product superlative «الأول»; incidental uses such as “first retry” (`console/static/i18n/ar.json:554`) are not product claims. These are scoped text searches, not a full copy review.
- The console UI uses `innerHTML`, but its central `esc()` and translation wrapper escape inserted text (`console/static/app.js:11-18`); reviewed move fields reach it through `esc()` (`console/static/app.js:1172-1203`). The mail preview has a restrictive CSP (`console/app.py:1236-1244`). **No confirmed console XSS or injection path** was established in this audit; exhaustive taint analysis and a browser exploit test are **UNVERIFIED**.

### 7. Tech Stack Suitability

- FastAPI plus SQLite is coherent for a small committee (`console/requirements.txt:1-2`, `console/db.py:383-403`), with transactions on connection exit. Public pages are static (`netlify.toml:1-4`). `console/requirements.txt:1-2` uses lower bounds rather than exact pins, so deployments can resolve different FastAPI/Uvicorn versions; pin and record a tested lock set before sustained production operation. Known-CVE status is **UNVERIFIED** without a dependency audit.
- CI installs console dependencies and runs pytest (`.github/workflows/ci.yml:19-30`), an improvement over October 3. It builds `fahras.html` twice and compares the two builds, not the committed artifact (`.github/workflows/ci.yml:32-37`); browser QA is absent from that workflow. **P2:** add generated-artifact parity and browser smoke checks after the blockers.

## Change Since the 2026-10-03 Audit (6.0/10)

**Improved:** the prior CI frozen-path P0 was explicitly not reproduced and current CI uses separate pathspecs (`.github/workflows/ci.yml:47-52`); the owner publication decision is recorded in the previous report’s correction; the old methods-page escape issue is not carried forward without a new exploit trace. The console adds durable decisions, specialist-role enforcement, audit trails, OTP sessions, a public snapshot API and CI-installed console tests (`console/app.py:817-879`, `930-974`; `.github/workflows/ci.yml:19-30`).

**Regressed/new risk:** a network-facing console and mutable SQLite state now exist. Arm-B missing verdicts are treated as absent evidence rather than a veto (`src/committee_chair.py:414-461`), demo read-only is inconsistently enforced (`console/app.py:187-203`, `1205-1213`), and the UI can persist an SMTP credential in the database (`console/settings.py:265-287`). These new risks outweigh the governance gains, moving the engineering score from **6.0 to 4.9/10**.

## Remediation Action Plan

### P0 — Block submission

1. **C-01:** make missing/stale/failed arm-B verdicts block automatic candidates; change the current stale-file test expectation (`src/committee_chair.py:414-461`, `tests/test_specialist.py:165-169`).
2. **D-07:** enforce demo read-only globally for all state-changing routes; test settings, users, roles, languages and profile writes (`console/app.py:187-203`, `1042-1055`, `1205-1213`).

### P1 — Fix before freeze

1. **SEC-01:** stop storing SMTP passwords in `settings.value`; migrate and rotate existing stored credentials (`console/settings.py:265-287`).
2. Remove percentage/quality claims from source pages and rebuild `web/index.html` and `web/app.html` (`src/app_template.html:940-941`, `web/index.html:1155-1164`).
3. Connect the publication endpoint to the actual mirqah.app public build/route and test one approved version end to end, or accurately label the console action as a snapshot only (`console/app.py:930-974`, `netlify.toml:1-4`).

### P2 — Later

1. Pin console dependencies and audit their resolved versions (`console/requirements.txt:1-2`).
2. Reconcile orphan publication files after interrupted writes (`console/publish.py:235-246`).
3. Add committed-artifact parity and browser smoke checks to CI (`.github/workflows/ci.yml:32-37`).

## Verification and Scope

- `git status --short` and `git status --short -- data`: clean before this report; no data paths touched.
- `python --version` and `python -m pytest -q tests/test_console.py`: **could not run** because `python` is not installed/on PATH in this shell. No test is called passing here.
- Local `reader.html` and `assets/brand/quranpedia-books.js` targets referenced by `web/fahras.html:1970`, `2408` are tracked. External link availability is **UNVERIFIED**.
- The requested skill also calls for a separate HTML Artifact, but this audit's explicit read-only-except-one-report-file rule permits only this Markdown report; no artifact was created.
