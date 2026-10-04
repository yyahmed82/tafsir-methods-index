"""FastAPI application: JSON API under /api and the single-page UI."""

from __future__ import annotations

import json
import os
import re
import time
from contextlib import asynccontextmanager
import urllib.error
import urllib.request
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, auth, config, db, mailer, pipeline, runner, settings


# ------------------------------------------------------------------ setup

def create_app(start_worker: bool = True) -> FastAPI:
    db.init()
    settings.seed()
    auth.init()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):  # pragma: no cover - exercised by the real server
        if start_worker:
            runner.start()
        yield
        if start_worker:
            runner.stop()

    app = FastAPI(title="Mirqah committee console", version=__version__,
                  docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.method in (
                "POST", "PUT", "PATCH", "DELETE"):
            if request.headers.get(config.CSRF_HEADER) != "1":
                return JSONResponse({"error": "csrf"}, status_code=403)
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' "
            "https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com data:; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'self'; form-action 'self'")
        if request.url.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(config.STATIC_DIR / "index.html",
                            headers={"Cache-Control": "no-cache"})

    _routes(app)
    return app


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def current_user(request: Request) -> dict:
    user = auth.session_user(request.cookies.get(config.SESSION_COOKIE))
    if user is None:
        raise HTTPException(401, "login_required")
    return user


def need(*perms: str):
    def dep(user: dict = Depends(current_user)) -> dict:
        missing = [p for p in perms if p not in user["permissions"]]
        if missing:
            raise HTTPException(403, "forbidden")
        return user
    return dep


def _err(code: int, key: str, **extra: Any) -> HTTPException:
    return HTTPException(code, {"error": key, **extra})


# ------------------------------------------------------------------ models

class EmailIn(BaseModel):
    email: str = Field(max_length=200)


class OtpIn(BaseModel):
    email: str = Field(max_length=200)
    code: str = Field(max_length=12)


class MeIn(BaseModel):
    lang: str | None = None
    name: str | None = Field(default=None, max_length=80)


class TaskIn(BaseModel):
    kind: str
    scope: str
    ayat: str = ""
    tafsirs: list[str] = []
    skip_done: bool = True


class DecisionIn(BaseModel):
    tafsir: str
    window: str
    move_id: str = Field(max_length=20)
    decision: str
    compared_with_source: bool = False
    note: str = Field(default="", max_length=1000)


class UserIn(BaseModel):
    email: str = Field(max_length=200)
    name: str = Field(max_length=80)
    role_id: int
    lang: str = ""
    active: bool = True


class UserPatch(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    role_id: int | None = None
    lang: str | None = None
    active: bool | None = None


class RoleIn(BaseModel):
    key: str = Field(max_length=40)
    name_ar: str = Field(max_length=60)
    name_en: str = Field(max_length=60)
    description_ar: str = Field(default="", max_length=300)
    permissions: list[str] = []


class RolePatch(BaseModel):
    name_ar: str | None = Field(default=None, max_length=60)
    name_en: str | None = Field(default=None, max_length=60)
    description_ar: str | None = Field(default=None, max_length=300)
    permissions: list[str] | None = None


class LangIn(BaseModel):
    code: str = Field(max_length=10)
    name_native: str = Field(max_length=40)
    name_en: str = Field(max_length=40)
    dir: str = "ltr"
    enabled: bool = True


class LangPatch(BaseModel):
    name_native: str | None = Field(default=None, max_length=40)
    name_en: str | None = Field(default=None, max_length=40)
    dir: str | None = None
    enabled: bool | None = None
    is_default: bool | None = None
    sort: int | None = None


class SmtpTestIn(BaseModel):
    to: str = Field(max_length=200)


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LANG_RE = re.compile(r"^[a-z]{2,3}(-[A-Z]{2})?$")
ROLE_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
I18N_KEY_RE = re.compile(r"^[a-z0-9_.]{1,80}$")


# ------------------------------------------------------------------ i18n

def _lang_file(code: str) -> dict:
    p = config.I18N_DIR / f"{code}.json"
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def i18n_bundle(code: str) -> dict:
    base = _lang_file("en")
    own = _lang_file(code)
    overrides = {r["key"]: r["value"] for r in
                 db.rows("SELECT key, value FROM translations WHERE lang=?", (code,))}
    merged = {**base, **own, **overrides}
    translated = {k for k in base if k in own or k in overrides}
    return {"lang": code, "strings": merged, "total": len(base),
            "translated": len(translated) if code != "en" else len(base)}


def languages(enabled_only: bool = False) -> list[dict]:
    q = "SELECT * FROM languages" + (" WHERE enabled=1" if enabled_only else "") + \
        " ORDER BY sort, code"
    out = db.rows(q)
    base = _lang_file("en")
    for lang in out:
        lang["enabled"] = bool(lang["enabled"])
        lang["is_default"] = bool(lang["is_default"])
        lang["has_file"] = (config.I18N_DIR / f"{lang['code']}.json").is_file()
        if not enabled_only:
            b = i18n_bundle(lang["code"])
            lang["coverage"] = round(100 * b["translated"] / max(1, len(base)))
    return out


def default_lang() -> str:
    return db.scalar("SELECT code FROM languages WHERE is_default=1") or "ar"


# ------------------------------------------------------------------ routes

_PROBE_CACHE: dict[str, Any] = {"at": 0.0, "value": None}


def _probe(force: bool = False) -> dict:
    if force or time.time() - _PROBE_CACHE["at"] > 10:
        _PROBE_CACHE.update(at=time.time(), value=pipeline.probe_llm())
    return _PROBE_CACHE["value"]


def _routes(app: FastAPI) -> None:  # noqa: C901 - one place for the API surface

    # ---------- public
    @app.get("/api/public")
    def public() -> dict:
        gen = settings.get("general")
        return {
            "project_name": gen["project_name"], "team_name": gen["team_name"],
            "timezone": gen["timezone"],
            "languages": languages(enabled_only=True), "default_lang": default_lang(),
            "mail_mode": settings.get("smtp")["mode"],
            "has_users": bool(db.scalar("SELECT COUNT(*) FROM users")),
            "version": __version__,
        }

    @app.get("/api/i18n/{code}")
    def i18n(code: str) -> dict:
        if not LANG_RE.match(code):
            raise _err(400, "bad_lang")
        return i18n_bundle(code)

    # ---------- auth
    @app.post("/api/auth/request-otp")
    def request_otp(body: EmailIn, request: Request) -> dict:
        ip = _ip(request) or "?"
        email = auth.normalize_email(body.email)
        if not EMAIL_RE.match(email):
            raise _err(400, "bad_email")
        if auth.rate_limited(f"otp-ip:{ip}", 20, 600) or \
                auth.rate_limited(f"otp-mail:{email}", 5, 600):
            raise _err(429, "rate_limited")
        return auth.request_otp(email, ip)

    @app.post("/api/auth/verify-otp")
    def verify_otp(body: OtpIn, request: Request, response: Response) -> dict:
        ip = _ip(request) or "?"
        if auth.rate_limited(f"verify-ip:{ip}", 30, 600):
            raise _err(429, "rate_limited")
        try:
            token, _ = auth.verify_otp(body.email, body.code, ip,
                                       request.headers.get("user-agent"))
        except PermissionError as e:
            raise _err(401, str(e)) from e
        hours = settings.get("security")["session_hours"]
        response.set_cookie(config.SESSION_COOKIE, token, max_age=hours * 3600, httponly=True,
                            samesite="strict", secure=request.url.scheme == "https", path="/")
        user = auth.session_user(token)
        return {"ok": True, "user": auth.public_user(user)}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response) -> dict:
        tok = request.cookies.get(config.SESSION_COOKIE)
        u = auth.session_user(tok)
        auth.revoke(tok)
        response.delete_cookie(config.SESSION_COOKIE, path="/")
        if u:
            db.audit("auth.logout", user_id=u["id"], ip=_ip(request))
        return {"ok": True}

    @app.get("/api/me")
    def me(user: dict = Depends(current_user)) -> dict:
        return {"user": auth.public_user(user), "default_lang": default_lang()}

    @app.patch("/api/me")
    def me_patch(body: MeIn, user: dict = Depends(current_user)) -> dict:
        if body.lang is not None:
            if body.lang and not db.row("SELECT 1 FROM languages WHERE code=? AND enabled=1",
                                        (body.lang,)):
                raise _err(400, "bad_lang")
            db.execute("UPDATE users SET lang=? WHERE id=?", (body.lang, user["id"]))
        if body.name:
            db.execute("UPDATE users SET name=? WHERE id=?", (body.name.strip(), user["id"]))
        return {"ok": True}

    # ---------- dashboard & progress
    @app.get("/api/dashboard")
    def dashboard(user: dict = Depends(need("view_dashboard"))) -> dict:
        tasks = db.rows("SELECT id,kind,title_ar,status,total_steps,done_steps,failed_steps,"
                        "skipped_steps,created_at,started_at,finished_at FROM tasks"
                        " ORDER BY id DESC LIMIT 6")
        return {"llm": _probe(), "agents": runner.agents_state(), "progress": pipeline.progress(),
                "gates": settings.get("gates"), "tasks": tasks,
                "sample_ayah": settings.get("general")["sample_ayah"],
                "server_time": time.time()}

    @app.get("/api/progress")
    def progress(user: dict = Depends(need("view_dashboard"))) -> dict:
        return {"progress": pipeline.progress(), "matrix": pipeline.ayah_matrix()}

    @app.get("/api/llm/probe")
    def llm_probe(user: dict = Depends(need("view_dashboard"))) -> dict:
        return _probe(force=True)

    @app.post("/api/llm/test")
    def llm_test(user: dict = Depends(need("manage_settings"))) -> dict:
        llm = settings.get("llm")
        if llm["runtime"] != "ollama-local":
            raise _err(400, "hosted_runtime_not_tested")
        url = llm["base_url"].rstrip("/") + "/v1/chat/completions"
        body = json.dumps({"model": llm["classifier_model"], "temperature": 0,
                           "messages": [{"role": "user", "content": "Reply with OK only."}]})
        t0 = time.time()
        try:
            req = urllib.request.Request(url, data=body.encode(), method="POST", headers={
                "Content-Type": "application/json", "Authorization": "Bearer ollama"})
            with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310
                data = json.loads(r.read().decode("utf-8"))
            reply = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
            ok = True
        except (urllib.error.URLError, OSError, ValueError) as e:
            reply, ok = f"{type(e).__name__}: {getattr(e, 'reason', e)}"[:200], False
        db.audit("llm.test", user_id=user["id"], detail={"ok": ok})
        return {"ok": ok, "model": llm["classifier_model"], "reply": reply[:200],
                "ms": int((time.time() - t0) * 1000)}

    # ---------- tasks
    @app.get("/api/tasks")
    def tasks(user: dict = Depends(need("view_tasks")), limit: int = 50) -> dict:
        rows = db.rows("SELECT t.*, u.name AS created_by_name FROM tasks t LEFT JOIN users u"
                       " ON u.id=t.created_by ORDER BY t.id DESC LIMIT ?", (min(limit, 200),))
        for r in rows:
            r["params"] = db.loads(r["params"], {})
        return {"tasks": rows}

    @app.post("/api/tasks/preview")
    def task_preview(body: TaskIn, user: dict = Depends(need("run_tasks"))) -> dict:
        try:
            steps = runner.plan_steps(body.kind, body.scope, body.ayat, body.tafsirs)
        except runner.TaskError as e:
            raise _err(400, str(e)) from e
        wins = {(s["tafsir"], s["window"]) for s in steps}
        bulk = runner.is_bulk(body.scope, steps) and body.kind != "dryrun"
        gates = settings.get("gates")
        blocked = None
        if bulk:
            if "run_bulk" not in user["permissions"]:
                blocked = "bulk_no_permission"
            elif not gates["phase0_merged"]:
                blocked = "bulk_gate_phase0"
            elif not gates["sample_reviewed"]:
                blocked = "bulk_gate_sample"
        per = {}
        for t, _w in wins:
            per[t] = per.get(t, 0) + 1
        return {"steps": len(steps), "windows": len(wins), "per_tafsir": per, "bulk": bulk,
                "blocked": blocked, "models": pipeline.models()}

    @app.post("/api/tasks")
    def task_create(body: TaskIn, user: dict = Depends(need("run_tasks"))) -> dict:
        try:
            tid = runner.create_task(body.kind, body.scope, body.ayat, body.tafsirs,
                                     body.skip_done, user)
        except runner.TaskError as e:
            raise _err(400, str(e)) from e
        return {"id": tid}

    @app.get("/api/tasks/{task_id}")
    def task_get(task_id: int, user: dict = Depends(need("view_tasks"))) -> dict:
        t = db.row("SELECT t.*, u.name AS created_by_name FROM tasks t LEFT JOIN users u"
                   " ON u.id=t.created_by WHERE t.id=?", (task_id,))
        if t is None:
            raise _err(404, "task_not_found")
        t["params"] = db.loads(t["params"], {})
        steps = db.rows("SELECT * FROM task_steps WHERE task_id=? ORDER BY seq", (task_id,))
        for s in steps:
            s["result"] = db.loads(s["result"])
        return {"task": t, "steps": steps}

    @app.post("/api/tasks/{task_id}/cancel")
    def task_cancel(task_id: int, user: dict = Depends(need("manage_tasks"))) -> dict:
        try:
            runner.cancel_task(task_id, user)
        except runner.TaskError as e:
            raise _err(400, str(e)) from e
        return {"ok": True}

    @app.post("/api/tasks/{task_id}/retry")
    def task_retry(task_id: int, user: dict = Depends(need("run_tasks"))) -> dict:
        try:
            return {"id": runner.retry_failed(task_id, user)}
        except runner.TaskError as e:
            raise _err(400, str(e)) from e

    # ---------- reports
    @app.get("/api/reports")
    def reports(user: dict = Depends(need("view_reports"))) -> dict:
        rows = db.rows("SELECT r.day, r.generated_at, r.mailed_at, u.name AS generated_by_name,"
                       " r.content FROM reports r LEFT JOIN users u ON u.id=r.generated_by"
                       " ORDER BY r.day DESC LIMIT 60")
        for r in rows:
            c = db.loads(r.pop("content"), {})
            r["steps"] = c.get("steps")
            r["routes"] = c.get("routes")
        return {"reports": rows, "today": runner.local_now().date().isoformat()}

    def _day(day: str) -> str:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
            raise _err(400, "bad_day")
        return day

    @app.get("/api/reports/{day}")
    def report_get(day: str, user: dict = Depends(need("view_reports"))) -> dict:
        rec = db.row("SELECT * FROM reports WHERE day=?", (_day(day),))
        if rec is None:
            raise _err(404, "report_not_found")
        return {"day": day, "content": db.loads(rec["content"]), "mailed_at": rec["mailed_at"]}

    @app.get("/api/reports/{day}/markdown")
    def report_md(day: str, user: dict = Depends(need("view_reports"))) -> PlainTextResponse:
        rec = db.row("SELECT * FROM reports WHERE day=?", (_day(day),))
        if rec is None:
            raise _err(404, "report_not_found")
        return PlainTextResponse(
            runner.report_markdown(db.loads(rec["content"])), media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="report-{day}.md"'})

    @app.post("/api/reports/{day}/generate")
    def report_generate(day: str, user: dict = Depends(need("generate_reports"))) -> dict:
        return {"content": runner.save_report(_day(day), user["id"])}

    @app.post("/api/reports/{day}/mail")
    def report_mail(day: str, user: dict = Depends(need("generate_reports"))) -> dict:
        return runner.mail_report(_day(day), user["id"])

    # ---------- review
    @app.get("/api/review/units")
    def review_units(user: dict = Depends(need("view_tasks")), tafsir: str | None = None) -> dict:
        units = pipeline.review_units(tafsir)
        counts = {(r["tafsir"], r["window"]): r for r in db.rows(
            "SELECT tafsir, window, COUNT(DISTINCT move_id) AS decided FROM decisions"
            " GROUP BY tafsir, window")}
        for u in units:
            u["decided"] = (counts.get((u["tafsir"], u["window"])) or {}).get("decided", 0)
        return {"units": units, "models": pipeline.models()}

    @app.get("/api/review/{tafsir}/{window}")
    def review_window(tafsir: str, window: str,
                      user: dict = Depends(need("view_tasks"))) -> dict:
        if tafsir not in config.TAFSIRS or not pipeline.WINDOW_RE.match(window):
            raise _err(400, "bad_unit")
        m = pipeline.models()
        v = pipeline.load_verified(tafsir, m["classifier_slug"], window)
        if v is None:
            raise _err(404, "unit_not_found")
        dec = db.rows("SELECT d.*, u.name AS user_name FROM decisions d JOIN users u"
                      " ON u.id=d.user_id WHERE tafsir=? AND window=? AND annotator=?"
                      " ORDER BY d.id", (tafsir, window, m["classifier_slug"]))
        latest = {}
        for d in dec:
            latest[d["move_id"]] = d
        moves = []
        for mv in v.get("moves") or []:
            moves.append({k: mv.get(k) for k in (
                "move_id", "span_ids", "start", "end", "text", "primary", "secondary",
                "content_tags", "certainty", "evidence_span_ids", "flags", "score", "route",
                "rationale_ar", "alternatives")}
                | {"decision": latest.get(mv.get("move_id"))})
        return {"tafsir": tafsir, "name_ar": config.TAFSIR_NAMES_AR[tafsir], "window": window,
                "ayah": v.get("ayah"), "annotator": v.get("annotator"),
                "source_file": v.get("source_file"), "source_sha256": v.get("source_sha256"),
                "summary": v.get("summary"), "moves": moves,
                "chair": pipeline.chair_preview(tafsir, window), "history": dec}

    @app.post("/api/review/decision")
    def review_decide(body: DecisionIn, request: Request,
                      user: dict = Depends(need("review_units"))) -> dict:
        if body.decision not in ("approve", "needs_edit", "reject"):
            raise _err(400, "bad_decision")
        if body.tafsir not in config.TAFSIRS or not pipeline.WINDOW_RE.match(body.window):
            raise _err(400, "bad_unit")
        if body.decision == "approve" and not body.compared_with_source:
            raise _err(400, "compare_first")
        if body.decision != "approve" and not body.note.strip():
            raise _err(400, "note_required")
        m = pipeline.models()
        v = pipeline.load_verified(body.tafsir, m["classifier_slug"], body.window)
        if v is None or body.move_id not in {x.get("move_id") for x in v.get("moves") or []}:
            raise _err(404, "unit_not_found")
        db.execute(
            "INSERT INTO decisions(tafsir,window,annotator,move_id,decision,compared_with_source,"
            "note,user_id,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (body.tafsir, body.window, m["classifier_slug"], body.move_id, body.decision,
             int(body.compared_with_source), body.note.strip(), user["id"], db.now()))
        db.audit("review.decision", user_id=user["id"], ip=_ip(request),
                 target=f"{body.tafsir}/{body.window}/{body.move_id}",
                 detail={"decision": body.decision})
        return {"ok": True}

    @app.get("/api/review/export")
    def review_export(user: dict = Depends(need("review_units"))) -> JSONResponse:
        rows = db.rows("SELECT d.tafsir,d.window,d.annotator,d.move_id,d.decision,"
                       "d.compared_with_source,d.note,d.created_at,u.name AS reviewer,"
                       "u.email AS reviewer_email FROM decisions d JOIN users u ON"
                       " u.id=d.user_id ORDER BY d.id")
        payload = {"kind": "mirqah-console-decisions", "exported_at": time.time(),
                   "note_ar": "قرارات بشرية مسجّلة في اللوحة؛ لا تُكتب في data/ إلا عبر"
                              " src/import_reviews.py بقرار الفريق.",
                   "decisions": rows}
        return JSONResponse(payload, headers={
            "Content-Disposition": 'attachment; filename="mirqah-decisions.json"'})

    # ---------- users
    def _role(role_id: int) -> dict:
        r = db.row("SELECT * FROM roles WHERE id=?", (role_id,))
        if r is None:
            raise _err(400, "bad_role")
        r["permissions"] = db.loads(r["permissions"], [])
        return r

    def _can_assign(actor: dict, role: dict) -> bool:
        return set(role["permissions"]) <= set(actor["permissions"])

    def _super_admins(active_only: bool = True) -> int:
        return db.scalar("SELECT COUNT(*) FROM users u JOIN roles r ON r.id=u.role_id WHERE"
                         " r.key='super_admin'" + (" AND u.active=1" if active_only else "")) or 0

    @app.get("/api/users")
    def users(user: dict = Depends(need("manage_users"))) -> dict:
        rows = db.rows("SELECT u.id,u.email,u.name,u.lang,u.active,u.created_at,u.last_login_at,"
                       "u.role_id,r.key AS role_key,r.name_ar AS role_name_ar,r.name_en AS"
                       " role_name_en FROM users u JOIN roles r ON r.id=u.role_id ORDER BY u.id")
        for r in rows:
            r["active"] = bool(r["active"])
        return {"users": rows}

    @app.post("/api/users")
    def user_create(body: UserIn, request: Request,
                    user: dict = Depends(need("manage_users"))) -> dict:
        email = auth.normalize_email(body.email)
        if not EMAIL_RE.match(email):
            raise _err(400, "bad_email")
        role = _role(body.role_id)
        if not _can_assign(user, role):
            raise _err(403, "role_escalation")
        if db.row("SELECT 1 FROM users WHERE email=?", (email,)):
            raise _err(409, "email_exists")
        uid = db.execute("INSERT INTO users(email,name,role_id,lang,active,created_at,created_by)"
                         " VALUES (?,?,?,?,?,?,?)",
                         (email, body.name.strip(), role["id"], body.lang or "",
                          int(body.active), db.now(), user["id"]))
        db.audit("user.create", user_id=user["id"], target=email, ip=_ip(request),
                 detail={"role": role["key"]})
        return {"id": uid}

    @app.patch("/api/users/{user_id}")
    def user_patch(user_id: int, body: UserPatch, request: Request,
                   user: dict = Depends(need("manage_users"))) -> dict:
        target = db.row("SELECT u.*, r.key AS role_key FROM users u JOIN roles r ON"
                        " r.id=u.role_id WHERE u.id=?", (user_id,))
        if target is None:
            raise _err(404, "user_not_found")
        changes: dict[str, Any] = {}
        if target["role_key"] == "super_admin" and "super_admin" != user["role_key"]:
            raise _err(403, "role_escalation")
        if body.role_id is not None and body.role_id != target["role_id"]:
            if user_id == user["id"]:
                raise _err(400, "own_role")
            role = _role(body.role_id)
            if not _can_assign(user, role):
                raise _err(403, "role_escalation")
            if target["role_key"] == "super_admin" and _super_admins() <= 1:
                raise _err(400, "last_super_admin")
            changes["role_id"] = role["id"]
        if body.active is not None and bool(body.active) != bool(target["active"]):
            if user_id == user["id"]:
                raise _err(400, "own_active")
            if not body.active and target["role_key"] == "super_admin" and _super_admins() <= 1:
                raise _err(400, "last_super_admin")
            changes["active"] = int(body.active)
        if body.name:
            changes["name"] = body.name.strip()
        if body.lang is not None:
            changes["lang"] = body.lang
        if changes:
            sets = ", ".join(f"{k}=?" for k in changes)
            db.execute(f"UPDATE users SET {sets} WHERE id=?", (*changes.values(), user_id))
            if changes.get("active") == 0 or "role_id" in changes:
                auth.revoke_user_sessions(user_id)
            db.audit("user.update", user_id=user["id"], target=target["email"], ip=_ip(request),
                     detail={k: v for k, v in changes.items()})
        return {"ok": True}

    @app.post("/api/users/{user_id}/revoke-sessions")
    def user_revoke(user_id: int, user: dict = Depends(need("manage_users"))) -> dict:
        auth.revoke_user_sessions(user_id)
        db.audit("user.revoke_sessions", user_id=user["id"], target=str(user_id))
        return {"ok": True}

    # ---------- roles
    @app.get("/api/roles")
    def roles(user: dict = Depends(need("view_dashboard"))) -> dict:
        rows = db.rows("SELECT r.*, (SELECT COUNT(*) FROM users u WHERE u.role_id=r.id) AS users"
                       " FROM roles r ORDER BY r.system DESC, r.id")
        for r in rows:
            r["permissions"] = db.loads(r["permissions"], [])
            r["system"] = bool(r["system"])
        return {"roles": rows, "permissions": list(config.PERMISSIONS)}

    def _clean_perms(perms: list[str], actor: dict) -> list[str]:
        bad = [p for p in perms if p not in config.PERMISSIONS]
        if bad:
            raise _err(400, "bad_permission", detail=bad)
        if not set(perms) <= set(actor["permissions"]):
            raise _err(403, "role_escalation")
        return sorted(set(perms))

    @app.post("/api/roles")
    def role_create(body: RoleIn, user: dict = Depends(need("manage_roles"))) -> dict:
        if not ROLE_KEY_RE.match(body.key):
            raise _err(400, "bad_role_key")
        if db.row("SELECT 1 FROM roles WHERE key=?", (body.key,)):
            raise _err(409, "role_exists")
        perms = _clean_perms(body.permissions, user)
        rid = db.execute("INSERT INTO roles(key,name_ar,name_en,description_ar,system,permissions)"
                         " VALUES (?,?,?,?,0,?)", (body.key, body.name_ar.strip(),
                                                    body.name_en.strip(), body.description_ar,
                                                    db.dumps(perms)))
        db.audit("role.create", user_id=user["id"], target=body.key, detail={"permissions": perms})
        return {"id": rid}

    @app.patch("/api/roles/{role_id}")
    def role_patch(role_id: int, body: RolePatch,
                   user: dict = Depends(need("manage_roles"))) -> dict:
        r = db.row("SELECT * FROM roles WHERE id=?", (role_id,))
        if r is None:
            raise _err(404, "role_not_found")
        if r["system"]:
            raise _err(400, "system_role")
        changes: dict[str, Any] = {}
        for k in ("name_ar", "name_en", "description_ar"):
            v = getattr(body, k)
            if v is not None:
                changes[k] = v.strip()
        if body.permissions is not None:
            changes["permissions"] = db.dumps(_clean_perms(body.permissions, user))
        if changes:
            sets = ", ".join(f"{k}=?" for k in changes)
            db.execute(f"UPDATE roles SET {sets} WHERE id=?", (*changes.values(), role_id))
            db.audit("role.update", user_id=user["id"], target=r["key"],
                     detail={k: (db.loads(v) if k == "permissions" else v)
                             for k, v in changes.items()})
        return {"ok": True}

    @app.delete("/api/roles/{role_id}")
    def role_delete(role_id: int, user: dict = Depends(need("manage_roles"))) -> dict:
        r = db.row("SELECT * FROM roles WHERE id=?", (role_id,))
        if r is None:
            raise _err(404, "role_not_found")
        if r["system"]:
            raise _err(400, "system_role")
        if db.scalar("SELECT COUNT(*) FROM users WHERE role_id=?", (role_id,)):
            raise _err(400, "role_in_use")
        db.execute("DELETE FROM roles WHERE id=?", (role_id,))
        db.audit("role.delete", user_id=user["id"], target=r["key"])
        return {"ok": True}

    # ---------- settings
    @app.get("/api/settings")
    def settings_get(user: dict = Depends(need("manage_settings"))) -> dict:
        return {"settings": settings.get_all(),
                "env": {"smtp_password_from_env": bool(
                    os.environ.get("MIRQAH_SMTP_PASSWORD"))}}

    @app.patch("/api/settings/{section}")
    def settings_patch(section: str, body: dict, user: dict = Depends(need("manage_settings"))
                       ) -> dict:
        try:
            value = settings.update(section, body, user["id"])
        except settings.SettingsError as e:
            raise _err(400, "settings_invalid", detail=str(e)) from e
        _PROBE_CACHE["at"] = 0.0
        return {"section": section, "value": value}

    @app.post("/api/settings/smtp/test")
    def smtp_test(body: SmtpTestIn, user: dict = Depends(need("manage_settings"))) -> dict:
        to = auth.normalize_email(body.to)
        if not EMAIL_RE.match(to):
            raise _err(400, "bad_email")
        try:
            res = mailer.send(to, "اختبار البريد — مِرْقاة",
                              "هذه رسالة اختبار من لوحة لجنة مِرْقاة.\nThis is a test message.")
        except mailer.MailError as e:
            db.audit("smtp.test", user_id=user["id"], detail={"ok": False})
            raise _err(502, "mail_failed", detail=str(e)) from e
        db.audit("smtp.test", user_id=user["id"], detail={"ok": True, "mode": res["mode"]})
        return res

    @app.get("/api/outbox")
    def outbox(user: dict = Depends(need("manage_settings"))) -> dict:
        rows = db.rows("SELECT id,at,to_addr,subject,mode,status,error FROM outbox"
                       " ORDER BY id DESC LIMIT 50")
        return {"outbox": rows}

    # ---------- languages
    @app.get("/api/languages")
    def langs(user: dict = Depends(need("manage_languages"))) -> dict:
        return {"languages": languages()}

    @app.post("/api/languages")
    def lang_add(body: LangIn, user: dict = Depends(need("manage_languages"))) -> dict:
        if not LANG_RE.match(body.code) or body.dir not in ("ltr", "rtl"):
            raise _err(400, "bad_lang")
        if db.row("SELECT 1 FROM languages WHERE code=?", (body.code,)):
            raise _err(409, "lang_exists")
        sort = (db.scalar("SELECT MAX(sort) FROM languages") or 0) + 10
        db.execute("INSERT INTO languages(code,name_native,name_en,dir,enabled,is_default,sort)"
                   " VALUES (?,?,?,?,?,0,?)", (body.code, body.name_native.strip(),
                                                body.name_en.strip(), body.dir,
                                                int(body.enabled), sort))
        db.audit("lang.create", user_id=user["id"], target=body.code)
        return {"ok": True}

    @app.patch("/api/languages/{code}")
    def lang_patch(code: str, body: LangPatch,
                   user: dict = Depends(need("manage_languages"))) -> dict:
        lang = db.row("SELECT * FROM languages WHERE code=?", (code,))
        if lang is None:
            raise _err(404, "lang_not_found")
        if body.dir is not None and body.dir not in ("ltr", "rtl"):
            raise _err(400, "bad_lang")
        if body.enabled is False and (lang["is_default"] or body.is_default):
            raise _err(400, "default_must_be_enabled")
        with db.connect() as con:
            if body.is_default:
                con.execute("UPDATE languages SET is_default=0")
                con.execute("UPDATE languages SET is_default=1, enabled=1 WHERE code=?", (code,))
            for k in ("name_native", "name_en", "dir", "sort"):
                v = getattr(body, k)
                if v is not None:
                    con.execute(f"UPDATE languages SET {k}=? WHERE code=?", (v, code))
            if body.enabled is not None:
                con.execute("UPDATE languages SET enabled=? WHERE code=?",
                            (int(body.enabled), code))
        db.audit("lang.update", user_id=user["id"], target=code,
                 detail=body.model_dump(exclude_none=True))
        return {"ok": True}

    @app.get("/api/translations/{code}")
    def translations(code: str, user: dict = Depends(need("manage_languages"))) -> dict:
        if not LANG_RE.match(code):
            raise _err(400, "bad_lang")
        base = _lang_file("en")
        ar = _lang_file("ar")
        own = _lang_file(code)
        ov = {r["key"]: r["value"] for r in
              db.rows("SELECT key,value FROM translations WHERE lang=?", (code,))}
        items = [{"key": k, "en": base[k], "ar": ar.get(k, ""), "file": own.get(k),
                  "override": ov.get(k)} for k in sorted(base)]
        return {"lang": code, "items": items}

    @app.put("/api/translations/{code}")
    def translations_put(code: str, body: dict[str, str | None],
                         user: dict = Depends(need("manage_languages"))) -> dict:
        if not LANG_RE.match(code) or not db.row("SELECT 1 FROM languages WHERE code=?",
                                                 (code,)):
            raise _err(400, "bad_lang")
        base = _lang_file("en")
        n = 0
        with db.connect() as con:
            for k, v in body.items():
                if not I18N_KEY_RE.match(k) or k not in base:
                    continue
                if v is None or v == "":
                    con.execute("DELETE FROM translations WHERE lang=? AND key=?", (code, k))
                else:
                    con.execute("INSERT INTO translations(lang,key,value) VALUES (?,?,?)"
                                " ON CONFLICT(lang,key) DO UPDATE SET value=excluded.value",
                                (code, k, str(v)[:500]))
                n += 1
        db.audit("lang.translations", user_id=user["id"], target=code, detail={"keys": n})
        return {"ok": True, "updated": n}

    # ---------- audit
    @app.get("/api/audit")
    def audit_log(user: dict = Depends(need("view_audit")), limit: int = 200) -> dict:
        rows = db.rows("SELECT a.*, u.name AS user_name FROM audit a LEFT JOIN users u"
                       " ON u.id=a.user_id ORDER BY a.id DESC LIMIT ?", (min(limit, 500),))
        for r in rows:
            r["detail"] = db.loads(r["detail"])
        return {"audit": rows}

    @app.get("/api/llm/calls")
    def llm_calls(user: dict = Depends(need("view_tasks")), limit: int = 100) -> dict:
        rows = db.rows("SELECT id,task_id,agent,tafsir,window,model,status,started_at,"
                       "finished_at,duration_ms,exit_code,result FROM task_steps WHERE"
                       " finished_at IS NOT NULL AND agent IN ('classifier','verifier')"
                       " ORDER BY finished_at DESC LIMIT ?", (min(limit, 500),))
        for r in rows:
            r["result"] = db.loads(r["result"])
        return {"calls": rows}
