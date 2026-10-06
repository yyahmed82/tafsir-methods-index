"""FastAPI application: JSON API under /api and the single-page UI."""

from __future__ import annotations

import functools
import hashlib
import ipaddress
import json
import os
import re
import time
from contextlib import asynccontextmanager
import urllib.error
import urllib.request
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import (__version__, auth, config, db, demo, learning, mailer, mailtpl, pipeline, publish,
               runner, settings, team, workflow)


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
        if config.ALLOWED_HOSTS and _host(request) not in config.ALLOWED_HOSTS \
                and _host(request) not in config.LOCAL_HOSTS:
            return PlainTextResponse("unknown host", status_code=421)
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
        if config.SECURE_COOKIES:
            resp.headers["Strict-Transport-Security"] = "max-age=31536000"
        if request.url.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        elif request.url.path.startswith("/static/"):
            # Cloudflare caches .js/.css/.svg at the edge. A URL carrying the current
            # asset version never changes, so it may be cached for a year; anything
            # else must be revalidated, or a release keeps serving the old UI.
            fresh = request.query_params.get("v") == asset_version()
            resp.headers["Cache-Control"] = ("public, max-age=31536000, immutable"
                                             if fresh else "no-cache")
        return resp

    app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> HTMLResponse:
        return HTMLResponse(render_index(), headers={"Cache-Control": "no-cache"})

    _routes(app)
    return app


def _ip(request: Request) -> str | None:
    """Visitor IP. Behind Cloudflare Tunnel every request comes from 127.0.0.1, so the
    real address is taken from CF-Connecting-IP (only when MIRQAH_PROXY=cloudflare and
    the console listens on localhost, so nobody else can set that header)."""
    if config.TRUST_CF_IP:
        raw = (request.headers.get("cf-connecting-ip") or "").strip()
        try:
            return str(ipaddress.ip_address(raw))
        except ValueError:
            pass
    return request.client.host if request.client else None


def _asset_files() -> list:
    root = config.STATIC_DIR
    files = [root / "app.js", root / "app.css", root / "logo.svg"]
    files += sorted((root / "brand").glob("*")) if (root / "brand").is_dir() else []
    return [f for f in files if f.is_file()]


@functools.lru_cache(maxsize=16)
def _asset_hash(stamp: tuple) -> str:
    h = hashlib.sha1()
    for name, _mtime, _size in stamp:
        h.update(name.encode())
        h.update((config.STATIC_DIR / name).read_bytes())
    return h.hexdigest()[:10]


def asset_version() -> str:
    """Content hash of the UI files; changes whenever a release changes them."""
    root = config.STATIC_DIR
    stamp = tuple((str(f.relative_to(root)), f.stat().st_mtime_ns, f.stat().st_size)
                  for f in _asset_files())
    return _asset_hash(stamp)


def render_index() -> str:
    """index.html with ?v=<asset version> on every local /static/ link, so a new
    release is never hidden behind a stale browser or Cloudflare cache."""
    v = asset_version()
    html = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return re.sub(r'((?:href|src)="/static/[^"?]+)"', lambda m: f'{m.group(1)}?v={v}"', html)


def _release() -> str:
    """Commit of the running release (written by deploy/server/mirqah-deploy), or ""."""
    try:
        return (config.REPO_ROOT / ".release-sha").read_text(encoding="utf-8").strip()[:12]
    except OSError:
        return ""


def _host(request: Request) -> str:
    host = (request.headers.get("host") or "").strip().lower()
    if host.startswith("["):  # [::1]:8800
        return host[1:host.find("]")] if "]" in host else host
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def _set_session_cookie(request: Request, response: Response, token: str, hours: float) -> None:
    response.set_cookie(config.SESSION_COOKIE, token, max_age=int(hours * 3600), httponly=True,
                        samesite="strict",
                        secure=config.SECURE_COOKIES or request.url.scheme == "https", path="/")


VIEW_AS_ALLOW = {"/api/view-as/stop", "/api/mode"}
# Demo mode is read-only for the whole API, not only for the committee's routes
# (audit D-07). The few writes that stay open never touch live committee data:
# switching back to live, signing out, (re)building, configuring or deleting the
# simulation, looking through another account, and the viewer's interface language.
DEMO_ALLOW = {"/api/mode", "/api/auth/logout", "/api/demo/seed", "/api/demo",
              "/api/settings/demo", "/api/view-as", "/api/view-as/stop", "/api/me"}


def real_user(request: Request) -> dict:
    """The signed-in account, ignoring any view-as header."""
    user = auth.session_user(request.cookies.get(config.SESSION_COOKIE))
    if user is None:
        raise HTTPException(401, "login_required")
    user["mode"] = demo.mode_for(request, user)
    return user


def current_user(request: Request) -> dict:
    """The account the request acts as.

    A real super admin may look through another active user's account with the
    X-Mirqah-View-As header: that user's role, permissions and pages. Identity for
    the audit trail stays the super admin (``real_user``), and every write is refused
    while the switch is on, so a route added later is closed by default. For anyone
    who is not a super admin the header does nothing.
    """
    real = real_user(request)
    if real.get("mode") == "demo" and request.method not in ("GET", "HEAD", "OPTIONS") \
            and request.url.path not in DEMO_ALLOW:
        raise HTTPException(423, {"error": "demo_read_only"})
    target = auth.normalize_email(request.headers.get(config.VIEW_AS_HEADER) or "")
    if not target or not auth.has_role(real, "super_admin") or target == real["email"]:
        return real
    eff = auth.user_by_email(target)
    if eff is None:
        return real
    eff["real_user"] = {"id": real["id"], "email": real["email"], "name": real["name"],
                        "role_key": real["role_key"], "role_keys": real.get("role_keys")}
    eff["mode"] = real["mode"]
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path not in VIEW_AS_ALLOW:
        raise HTTPException(423, {"error": "view_as_read_only", "view_as": eff["email"]})
    return eff


def operational(write: bool = False):
    """Run the route against the simulation when the viewer is in demo mode.

    Demo mode is read-only: routes that write refuse with 423 ``demo_read_only``.
    """
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user = kwargs.get("user") or {}
            if user.get("mode") != "demo":
                return fn(*args, **kwargs)
            if write:
                raise HTTPException(423, {"error": "demo_read_only"})
            demo.tick()
            with db.use("demo"):
                return fn(*args, **kwargs)
        return wrapper
    return deco


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
    variant: str = "baseline"  # baseline | profile | ab (both arms, blind review)


class DecisionIn(BaseModel):
    tafsir: str
    window: str
    move_id: str = Field(max_length=20)
    decision: str
    compared_with_source: bool = False
    note: str = Field(default="", max_length=1000)
    arm: str = Field(default="", max_length=1)  # X | Y in a blind A/B window
    # the lesson for the agents (optional on approve)
    error_type: str = Field(default="", max_length=40)
    correct_primary: str = Field(default="", max_length=20)
    teach: bool = False


class UserIn(BaseModel):
    email: str = Field(max_length=200)
    name: str = Field(max_length=80)
    role_id: int | None = None
    role_ids: list[int] = []  # several roles; the primary is picked by rank
    lang: str = ""
    active: bool = True
    notify: bool = True


class UserPatch(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    role_id: int | None = None
    role_ids: list[int] | None = None
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


class AssignIn(BaseModel):
    tafsir: str = Field(max_length=20)
    window: str = Field(max_length=20)
    user_id: int


class PublishIn(BaseModel):
    note: str = Field(default="", max_length=500)


class SmtpTestIn(BaseModel):
    to: str = Field(max_length=200)


class ModeIn(BaseModel):
    mode: str = Field(max_length=10)


class ViewAsIn(BaseModel):
    email: str = Field(max_length=200)


class DemoSeedIn(BaseModel):
    months: int = 12


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
    if db.mode() == "demo":
        return pipeline.probe_llm()
    if force or time.time() - _PROBE_CACHE["at"] > 10:
        _PROBE_CACHE.update(at=time.time(), value=pipeline.probe_llm())
    return _PROBE_CACHE["value"]


def _llm_for(user: dict, llm: dict) -> dict:
    """The model server's address is for operators only: judges, guests, viewers and
    specialists see that a private engine answers, not where it lives."""
    if "run_tasks" in user.get("permissions", ()):
        return llm
    out = {k: v for k, v in (llm or {}).items() if k not in ("base_url", "work_root", "error")}
    out["base_url"] = ""
    out["address_hidden"] = True
    return out


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
            "guest_access": bool(settings.get("security").get("guest_access")),
            "demo_available": demo.available(),
            "version": __version__,
            "release": _release(),
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
        _set_session_cookie(request, response, token, settings.get("security")["session_hours"])
        user = auth.session_user(token)
        return {"ok": True, "user": auth.public_user(user)}

    @app.post("/api/auth/guest")
    def guest_login(request: Request, response: Response) -> dict:
        ip = _ip(request) or "?"
        if auth.rate_limited(f"guest-ip:{ip}", 10, 600):
            raise _err(429, "rate_limited")
        try:
            token, _ = auth.guest_session(ip, request.headers.get("user-agent"))
        except PermissionError as e:
            raise _err(403, str(e)) from e
        _set_session_cookie(request, response, token, config.GUEST_SESSION_HOURS)
        return {"ok": True, "user": auth.public_user(auth.session_user(token))}

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
        return {"user": {**auth.public_user(user), "sample_ayah": settings.get("general")["sample_ayah"]},
                "default_lang": default_lang(),
                "demo_available": demo.available()}

    # ---------- live / demo (per browser; the simulation is read-only)
    @app.post("/api/mode")
    def set_mode(body: ModeIn, request: Request, response: Response,
                 user: dict = Depends(current_user)) -> dict:
        if body.mode not in ("live", "demo"):
            raise _err(400, "bad_mode")
        if body.mode == "demo" and not demo.available():
            raise _err(409, "demo_not_seeded")
        response.set_cookie(config.MODE_COOKIE, body.mode, max_age=180 * 86400, httponly=True,
                            samesite="strict", secure=config.SECURE_COOKIES or request.url.scheme == "https",
                            path="/")
        db.audit("mode.switch", user_id=(user.get("real_user") or user)["id"], ip=_ip(request),
                 detail={"mode": body.mode})
        return {"mode": body.mode}

    # ---------- view as another user (super admin only, read-only, audited)
    def real_super(request: Request) -> dict:
        u = real_user(request)
        if not auth.has_role(u, "super_admin"):
            db.audit("view_as.denied", user_id=u["id"], ip=_ip(request))
            raise _err(403, "forbidden")
        return u

    @app.get("/api/view-as/users")
    def view_as_users(user: dict = Depends(real_super)) -> dict:
        rows = db.rows("SELECT u.email, u.name, r.key AS role_key, r.name_ar AS role_name_ar,"
                       " r.name_en AS role_name_en, u.last_login_at FROM users u JOIN roles r"
                       " ON r.id=u.role_id WHERE u.active=1 AND u.email<>? ORDER BY lower(u.name)",
                       (user["email"],))
        return {"users": rows}

    @app.post("/api/view-as")
    def view_as_start(body: ViewAsIn, request: Request, user: dict = Depends(real_super)) -> dict:
        email = auth.normalize_email(body.email)
        if email == user["email"]:
            raise _err(400, "view_as_self")
        target = auth.user_by_email(email)
        if target is None:
            raise _err(404, "user_not_found")
        db.audit("view_as.start", user_id=user["id"], target=email, ip=_ip(request),
                 detail={"role": target["role_key"]})
        return {"ok": True, "user": auth.public_user(target)}

    @app.post("/api/view-as/stop")
    def view_as_stop(request: Request, user: dict = Depends(real_super)) -> dict:
        target = auth.normalize_email(request.headers.get(config.VIEW_AS_HEADER) or "")
        db.audit("view_as.stop", user_id=user["id"], target=target or None, ip=_ip(request))
        return {"ok": True}

    @app.patch("/api/me")
    def me_patch(body: MeIn, user: dict = Depends(current_user)) -> dict:
        if body.name and user.get("mode") == "demo":
            raise _err(423, "demo_read_only")   # only the interface language may change
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
    @operational()
    def dashboard(user: dict = Depends(need("view_dashboard"))) -> dict:
        tasks = runner.task_groups(6)  # originals with their retries folded in
        return {"llm": _llm_for(user, _probe()),
                "agents": runner.redact_engine(runner.agents_state(), user),
                "progress": pipeline.progress(),
                "gates": pipeline.gates(), "tasks": tasks, "simulated": db.mode() == "demo",
                "sample_ayah": settings.get("general")["sample_ayah"],
                "server_time": time.time()}

    @app.get("/api/progress")
    @operational()
    def progress(user: dict = Depends(need("view_dashboard"))) -> dict:
        return {"progress": pipeline.progress(), "matrix": pipeline.ayah_matrix()}

    @app.get("/api/llm/probe")
    @operational()
    def llm_probe(user: dict = Depends(need("view_dashboard"))) -> dict:
        return _llm_for(user, _probe(force=True))

    # ---------- mission-control hover cards (real step timings and token counts)
    @app.get("/api/agents/{key}")
    @operational()
    def agent_card(key: str, user: dict = Depends(need("view_dashboard"))) -> dict:
        try:
            if key == "model":
                payload = {**runner.model_layer(), "llm": _llm_for(user, _probe())}
            else:
                payload = runner.agent_detail(
                    key, with_output="view_tasks" in user["permissions"])
        except runner.TaskError as e:
            raise _err(404, str(e)) from e
        return runner.redact_engine(payload, user)

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
    @operational()
    def tasks(user: dict = Depends(need("view_tasks")), limit: int = 50) -> dict:
        # one row per original task; its retries are attempts inside it (chain.attempts)
        return {"tasks": runner.task_groups(limit)}

    @app.post("/api/tasks/preview")
    @operational(write=True)
    def task_preview(body: TaskIn, user: dict = Depends(need("run_tasks"))) -> dict:
        try:
            steps = runner.plan_steps(body.kind, body.scope, body.ayat, body.tafsirs,
                                      body.variant)
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
        if blocked is None and body.kind != "dryrun" and not _probe().get("reachable"):
            blocked = "engine_offline"
        per = {}
        for t, _w in wins:
            per[t] = per.get(t, 0) + 1
        return {"steps": len(steps), "windows": len(wins), "per_tafsir": per, "bulk": bulk,
                "blocked": blocked, "models": pipeline.models()}

    @app.post("/api/tasks")
    @operational(write=True)
    def task_create(body: TaskIn, user: dict = Depends(need("run_tasks"))) -> dict:
        try:
            runner.check_gates(body.kind, body.scope,
                               runner.plan_steps(body.kind, body.scope, body.ayat, body.tafsirs,
                                                 body.variant), user)
        except runner.TaskError as e:
            raise _err(400, str(e)) from e
        if body.kind != "dryrun" and not _probe(force=True).get("reachable"):
            raise _err(409, "engine_offline")
        try:
            tid = runner.create_task(body.kind, body.scope, body.ayat, body.tafsirs,
                                     body.skip_done, user, variant=body.variant)
        except runner.TaskError as e:
            raise _err(400, str(e)) from e
        return {"id": tid}

    @app.get("/api/tasks/{task_id}")
    @operational()
    def task_get(task_id: int, user: dict = Depends(need("view_tasks"))) -> dict:
        t = db.row("SELECT t.*, u.name AS created_by_name FROM tasks t LEFT JOIN users u"
                   " ON u.id=t.created_by WHERE t.id=?", (task_id,))
        if t is None:
            raise _err(404, "task_not_found")
        t["params"] = db.loads(t["params"], {})
        steps = db.rows("SELECT * FROM task_steps WHERE task_id=? ORDER BY seq", (task_id,))
        for s in steps:
            s["cause"] = runner.failure_cause(s)
            s["result"] = db.loads(s["result"])
        return runner.redact_engine(
            {"task": t, "steps": steps, "chain": runner.task_chain(task_id)}, user)

    @app.post("/api/tasks/{task_id}/cancel")
    @operational(write=True)
    def task_cancel(task_id: int, user: dict = Depends(need("manage_tasks"))) -> dict:
        try:
            runner.cancel_task(task_id, user)
        except runner.TaskError as e:
            raise _err(400, str(e)) from e
        return {"ok": True}

    @app.post("/api/tasks/{task_id}/retry")
    @operational(write=True)
    def task_retry(task_id: int, user: dict = Depends(need("run_tasks"))) -> dict:
        try:
            return {"id": runner.retry_failed(task_id, user)}
        except runner.TaskError as e:
            raise _err(400, str(e)) from e

    # ---------- reports
    @app.get("/api/reports")
    @operational()
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
    @operational()
    def report_get(day: str, user: dict = Depends(need("view_reports"))) -> dict:
        rec = db.row("SELECT * FROM reports WHERE day=?", (_day(day),))
        if rec is None:
            raise _err(404, "report_not_found")
        return {"day": day,
                "content": runner.redact_engine(db.loads(rec["content"]), user),
                "mailed_at": rec["mailed_at"]}

    @app.get("/api/reports/{day}/markdown")
    @operational()
    def report_md(day: str, user: dict = Depends(need("view_reports"))) -> PlainTextResponse:
        rec = db.row("SELECT * FROM reports WHERE day=?", (_day(day),))
        if rec is None:
            raise _err(404, "report_not_found")
        return PlainTextResponse(
            runner.report_markdown(runner.redact_engine(db.loads(rec["content"]), user)),
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="report-{day}.md"'})

    @app.post("/api/reports/{day}/generate")
    @operational(write=True)
    def report_generate(day: str, user: dict = Depends(need("generate_reports"))) -> dict:
        return {"content": runner.redact_engine(runner.save_report(_day(day), user["id"]), user)}

    @app.post("/api/reports/{day}/mail")
    @operational(write=True)
    def report_mail(day: str, user: dict = Depends(need("generate_reports"))) -> dict:
        return runner.mail_report(_day(day), user["id"])

    # ---------- review
    def _reveals_arms(user: dict) -> bool:
        """Operators may see which blind arm is the profile run; reviewers may not —
        and anyone holding the specialist role decides blind, whatever else they hold."""
        return ("generate_reports" in user["permissions"]
                and not auth.has_role(user, config.DECIDER_ROLE))

    def _variant(tafsir: str, window: str, arm: str | None) -> str | None:
        try:
            return pipeline.variant_for_arm(tafsir, window, arm or None)
        except ValueError as e:
            raise _err(400, "bad_arm") from e

    @app.get("/api/review/units")
    @operational()
    def review_units(user: dict = Depends(need("view_tasks")), tafsir: str | None = None) -> dict:
        units = pipeline.review_units(tafsir)
        latest: dict[tuple, dict] = {}   # the last decision of every move (latest wins)
        for r in db.rows("SELECT tafsir, window, annotator, move_id, decision, note, teach,"
                         " created_at FROM decisions ORDER BY id"):
            latest[(r["tafsir"], r["window"], r["annotator"], r["move_id"])] = r
        by_unit: dict[tuple, list[dict]] = {}
        for (t, w, a, _m), r in latest.items():
            by_unit.setdefault((t, w, a), []).append(r)
        labels = learning.error_types()
        reveal = _reveals_arms(user)
        amap = workflow.assignments_map()
        for u in units:
            rows = by_unit.get((u["tafsir"], u["window"], u.get("annotator"))) or []
            u["decided"] = len(rows)
            u["decisions"] = {k: sum(1 for r in rows if r["decision"] == k)
                              for k in ("approve", "needs_edit", "reject")}
            notes = []
            for r in sorted(rows, key=lambda r: r["move_id"]):
                teach = db.loads(r.get("teach"), {}) or {}
                err = labels.get(teach.get("error_type") or "", "")
                if r.get("note") or err:
                    notes.append({"move": r["move_id"], "decision": r["decision"],
                                  "error": err, "note": r.get("note") or ""})
            u["notes"] = notes
            u["last_decision_at"] = max((r["created_at"] for r in rows), default=None)
            a = amap.get((u["tafsir"], u["window"]))
            u["assigned"] = ({"user_id": a["user_id"], "name": a.get("user_name"),
                              "status": a["status"], "assigned_at": a["assigned_at"]} if a else None)
            if not reveal:
                u.pop("variant", None)
                u.pop("annotator", None)
        mine = sum(1 for k, a in amap.items() if a["user_id"] == user["id"] and a["status"] == "open")
        return {"units": units, "models": pipeline.models(), "reveals_arms": reveal,
                "can_decide": auth.can_decide(user), "my_open_windows": mine,
                "can_assign": "manage_tasks" in user["permissions"]}

    _units = pipeline.unit_rows

    @app.get("/api/review/{tafsir}/{window}")
    @operational()
    def review_window(tafsir: str, window: str, arm: str | None = None,
                      user: dict = Depends(need("view_tasks"))) -> dict:
        if tafsir not in config.TAFSIRS or not pipeline.WINDOW_RE.match(window):
            raise _err(400, "bad_unit")
        if db.mode() == "demo":
            out = demo.review_window(tafsir, window)
            if out is None:
                raise _err(404, "unit_not_found")
            out["method_names"] = learning.method_names()
            return out
        variant = _variant(tafsir, window, arm)
        annotator, v, com = pipeline.review_source(tafsir, window, variant)
        if v is None:
            raise _err(404, "unit_not_found")
        dec = db.rows("SELECT d.*, u.name AS user_name FROM decisions d JOIN users u"
                      " ON u.id=d.user_id WHERE tafsir=? AND window=? AND annotator=?"
                      " ORDER BY d.id", (tafsir, window, annotator))
        reveal = _reveals_arms(user)
        for d in dec:
            d["teach"] = db.loads(d.get("teach"), {}) or {}
            if not reveal:
                d.pop("annotator", None)
        latest = {}
        for d in dec:
            latest[d["move_id"]] = d
        moves = []
        for key, mv, c in _units(v, com):
            row = {k: mv.get(k) for k in (
                "move_id", "span_ids", "start", "end", "text", "primary", "secondary",
                "content_tags", "certainty", "evidence_span_ids", "flags", "score", "route",
                "rationale_ar", "alternatives", "reason_code", "committee_reason_code",
                "committee_abstention_ar", "outcome", "method_specialist")}
            row["key"] = key
            row["decision"] = latest.get(key)
            if c:
                row["committee"] = {k: c.get(k) for k in (
                    "proposer_move_id", "reviewer_move_id", "primary_proposer",
                    "primary_reviewer", "score_proposer", "score_reviewer", "route_proposer",
                    "route_reviewer", "committee_route", "outcome", "abstention_reasons",
                    "abstention_ar")}
            moves.append(row)
        models = (com or {}).get("models")
        if models and not reveal:
            models = {k: {"tag": (x or {}).get("tag")} for k, x in models.items()}
        a = workflow.assignment(tafsir, window)
        mine_or_free = a is None or a["status"] != "open" or a["user_id"] == user["id"]
        return {"tafsir": tafsir, "name_ar": config.TAFSIR_NAMES_AR[tafsir], "window": window,
                "assignment": ({"user_id": a["user_id"], "name": a.get("user_name"),
                                "status": a["status"], "assigned_at": a["assigned_at"],
                                "assigned_by": a.get("assigned_by")} if a else None),
                "can_decide": auth.can_decide(user) and mine_or_free,
                "is_specialist": auth.has_role(user, config.DECIDER_ROLE),
                "specialists": ([{"id": p["id"], "name": p["name"]} for p in workflow.specialists()]
                                if "manage_tasks" in user["permissions"] else []),
                "ayah": v.get("ayah"), "annotator": annotator if reveal else None,
                "arm": arm or None, "variant": variant if reveal else None,
                **_window_context(tafsir, window),
                "source_file": v.get("source_file"), "source_sha256": v.get("source_sha256"),
                "packet_sha256": v.get("packet_sha256"),
                "summary": (com or {}).get("summary") or v.get("summary"),
                "models": models, "is_committee": com is not None,
                "moves": moves,
                "chair": None if com is not None else pipeline.chair_preview(tafsir, window,
                                                                             variant),
                "error_types": learning.error_types(), "methods": list(learning.METHODS),
                "method_names": learning.method_names(), "history": dec,
                "context": pipeline.window_context(tafsir, window)}

    def _window_context(tafsir: str, window: str) -> dict:
        """The pinned passage and where it sits: verse, part n of m, reading link."""
        w = pipeline.load_window(tafsir, window) or {}
        ayah = str(w.get("ayah") or "")
        n = int(w.get("ayah_number") or (ayah.split(":")[1] if ":" in ayah else 0) or 0)
        surah = int(w.get("surah") or (ayah.split(":")[0] if ":" in ayah else 0) or 0)
        parts = pipeline.window_parts(tafsir, n) if n else []
        return {"window_text": w.get("window_text"), "window_start": w.get("window_start"),
                "window_end": w.get("window_end"), "surah": surah,
                "surah_name_ar": pipeline.surah_name(surah), "ayah_number": n,
                "ayah_text": pipeline.ayah_text(tafsir, n) if n else None,
                "part": (parts.index(window) + 1) if window in parts else 1,
                "parts": len(parts) or 1,
                "source_url": pipeline.source_url(tafsir, surah, n)}

    @app.get("/api/review/{tafsir}/{window}/source")
    @operational()
    def review_source_check(tafsir: str, window: str, arm: str | None = None,
                            user: dict = Depends(need("view_tasks"))) -> dict:
        """Compare what the screen shows with the pinned source file, letter for letter:
        the file's sha256 against the pinned one, the window text against the file
        slice, and every move's text against its slice. Nothing is changed."""
        if tafsir not in config.TAFSIRS or not pipeline.WINDOW_RE.match(window):
            raise _err(400, "bad_unit")
        if db.mode() == "demo":
            raise _err(409, "demo_read_only")
        variant = _variant(tafsir, window, arm)
        annotator, v, com = pipeline.review_source(tafsir, window, variant)
        w = pipeline.load_window(tafsir, window)
        if v is None or w is None:
            raise _err(404, "unit_not_found")
        text, sha = publish._source(tafsir, w.get("source_file"))
        if text is None:
            return {"ok": False, "reason": "source_missing", "source_file": w.get("source_file")}
        start, end = int(w.get("window_start") or 0), int(w.get("window_end") or 0)
        slice_ = text[start:end]
        shown = w.get("window_text") or ""
        first_diff = next((i for i, (a, b) in enumerate(zip(shown, slice_)) if a != b),
                          None if len(shown) == len(slice_) else min(len(shown), len(slice_)))
        moves = []
        for key, mv, _c in _units(v, com):
            ms, me = mv.get("start"), mv.get("end")
            good = isinstance(ms, int) and isinstance(me, int) and 0 <= ms < me <= len(text)
            same = good and pipeline.span_text_ok(text, w, mv.get("span_ids") or [], mv.get("text"))
            moves.append({"key": key, "ok": bool(same)})
        sha_ok = sha == w.get("source_sha256") == v.get("source_sha256")
        ok = sha_ok and first_diff is None and all(m["ok"] for m in moves)
        db.audit("review.compare_source", user_id=user["id"], target=f"{tafsir}/{window}",
                 detail={"ok": ok, "sha_ok": sha_ok, "moves": len(moves)})
        return {"ok": ok, "sha_ok": sha_ok, "sha256": sha, "pinned_sha256": w.get("source_sha256"),
                "window_ok": first_diff is None, "first_diff": first_diff,
                "shown_chars": len(shown), "source_chars": len(slice_),
                "context": None if first_diff is None else {
                    "shown": shown[max(0, first_diff - 40):first_diff + 40],
                    "source": slice_[max(0, first_diff - 40):first_diff + 40]},
                "moves": moves, "moves_ok": sum(1 for m in moves if m["ok"]),
                "source_file": w.get("source_file"), "source_text": slice_,
                "checked_at": db.now()}

    @app.get("/api/review/ayah/{tafsir}/{ayah_number}")
    @operational()
    def review_ayah(tafsir: str, ayah_number: int,
                    user: dict = Depends(need("view_tasks"))) -> dict:
        """One ayah of one tafsir as a reader: every window of its commentary with the
        moves of each arm placed in the text, and the latest decision of each move."""
        if tafsir not in config.TAFSIRS:
            raise _err(400, "bad_unit")
        if db.mode() == "demo":
            raise _err(409, "demo_read_only")
        latest: dict[tuple, dict] = {}
        for r in db.rows("SELECT tafsir, window, annotator, move_id, decision FROM decisions"
                         " WHERE tafsir=? ORDER BY id", (tafsir,)):
            latest[(r["window"], r["annotator"], r["move_id"])] = r["decision"]
        units = {(u["window"], u.get("arm")): u for u in pipeline.review_units(tafsir)}
        wins = []
        for i, wid in enumerate(pipeline.window_parts(tafsir, ayah_number)):
            w = pipeline.load_window(tafsir, wid) or {}
            arms = []
            for (uw, arm), u in units.items():
                if uw != wid:
                    continue
                variant = u.get("variant")
                annotator, v, com = pipeline.review_source(tafsir, wid, variant)
                if v is None:
                    continue
                moves = [{"key": key, "start": mv.get("start"), "end": mv.get("end"),
                          "primary": mv.get("primary"), "route": mv.get("route"),
                          "certainty": mv.get("certainty"),
                          "decision": latest.get((wid, annotator, key))}
                         for key, mv, _c in _units(v, com)]
                arms.append({"arm": arm, "committee": u["committee"], "moves": moves,
                             "assigned": None, "decided": sum(1 for m in moves if m["decision"]),
                             "total": len(moves)})
            arms.sort(key=lambda a: a["arm"] or "")
            wins.append({"window": wid, "part": i + 1, "window_start": w.get("window_start"),
                         "window_end": w.get("window_end"), "text": w.get("window_text") or "",
                         "arms": arms})
        surah = int((pipeline.load_window(tafsir, wins[0]["window"]) or {}).get("surah") or 0) if wins else 0
        return {"tafsir": tafsir, "name_ar": config.TAFSIR_NAMES_AR[tafsir],
                "surah": surah, "surah_name_ar": pipeline.surah_name(surah),
                "source_url": pipeline.source_url(tafsir, surah, ayah_number),
                "ayah_number": ayah_number, "ayah_text": pipeline.ayah_text(tafsir, ayah_number),
                "windows": wins, "method_names": learning.method_names(),
                "ayat": sorted({w["ayah_number"] for w in pipeline.windows(tafsir)}),
                "ayat_with_moves": sorted({u["ayah_number"] for u in units.values()})}

    @app.post("/api/review/decision")
    @operational(write=True)
    def review_decide(body: DecisionIn, request: Request,
                      user: dict = Depends(need("review_units"))) -> dict:
        if not auth.can_decide(user):
            raise _err(403, "specialists_only")  # only the specialist role decides
        if body.decision not in ("approve", "needs_edit", "reject"):
            raise _err(400, "bad_decision")
        if body.tafsir not in config.TAFSIRS or not pipeline.WINDOW_RE.match(body.window):
            raise _err(400, "bad_unit")
        held = workflow.assignment(body.tafsir, body.window)
        if held and held["status"] == "open" and held["user_id"] != user["id"]:
            raise _err(403, "assigned_to_other", name=held.get("user_name"))
        if body.decision == "approve" and not body.compared_with_source:
            raise _err(400, "compare_first")
        if body.error_type and body.error_type not in learning.error_types():
            raise _err(400, "bad_error_type")
        if body.correct_primary and body.correct_primary not in learning.METHODS:
            raise _err(400, "bad_method")
        if body.decision != "approve" and not (body.note.strip() or body.error_type):
            raise _err(400, "note_required")
        if body.teach and body.decision != "approve" and not body.error_type:
            raise _err(400, "lesson_required")
        variant = _variant(body.tafsir, body.window, body.arm)
        annotator, v, com = pipeline.review_source(body.tafsir, body.window, variant)
        units = {k: (mv, c) for k, mv, c in _units(v, com)} if v is not None else {}
        if body.move_id not in units:
            raise _err(404, "unit_not_found")
        teach = {}
        if body.teach or body.error_type or body.correct_primary:
            teach = {"teach": bool(body.teach), "error_type": body.error_type or None,
                     "correct_primary": body.correct_primary or None}
        db.execute(
            "INSERT INTO decisions(tafsir,window,annotator,move_id,decision,compared_with_source,"
            "note,user_id,created_at,teach) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (body.tafsir, body.window, annotator, body.move_id, body.decision,
             int(body.compared_with_source), body.note.strip(), user["id"], db.now(),
             db.dumps(teach) if teach else ""))
        if held is None:
            workflow.claim(body.tafsir, body.window, user["id"])
        db.audit("review.decision", user_id=user["id"], ip=_ip(request),
                 target=f"{body.tafsir}/{body.window}/{body.move_id}",
                 detail={"decision": body.decision, "annotator": annotator,
                         "teach": bool(body.teach), "error_type": body.error_type or None})
        bank = learning.rebuild_bank(body.tafsir)
        done = workflow.close_if_done(body.tafsir, body.window)
        return {"ok": True, "teaching_examples": bank, "window_done": done}

    @app.get("/api/review/export")
    @operational()
    def review_export(user: dict = Depends(need("review_units"))) -> JSONResponse:
        rows = db.rows("SELECT d.tafsir,d.window,d.annotator,d.move_id,d.decision,"
                       "d.compared_with_source,d.note,d.teach,d.created_at,u.name AS reviewer,"
                       "u.email AS reviewer_email FROM decisions d JOIN users u ON"
                       " u.id=d.user_id ORDER BY d.id")
        for r in rows:
            r["teach"] = db.loads(r.get("teach"), {}) or {}
        payload = {"kind": "mirqah-console-decisions", "exported_at": time.time(),
                   "note_ar": "قرارات بشرية مسجّلة في اللوحة؛ لا تُكتب في data/ إلا عبر"
                              " src/import_reviews.py بقرار الفريق.",
                   "decisions": rows}
        return JSONResponse(payload, headers={
            "Content-Disposition": 'attachment; filename="mirqah-decisions.json"'})

    # ---------- assignment: the chair gives each window to one specialist
    @app.get("/api/review/assignments")
    @operational()
    def review_assignments(user: dict = Depends(need("view_tasks")), mine: bool = False) -> dict:
        rows = workflow.desk(user["id"] if mine else None)
        everyone = "manage_tasks" in user["permissions"]
        if not everyone and not mine:
            rows = [r for r in rows if r["user_id"] == user["id"]]
        return {"assignments": rows,
                "team": workflow.team_load() if everyone and db.mode() != "demo" else [],
                "can_assign": everyone, "can_decide": auth.can_decide(user)}

    @app.post("/api/review/assign")
    @operational(write=True)
    def review_assign(body: AssignIn, request: Request,
                      user: dict = Depends(need("manage_tasks"))) -> dict:
        if body.tafsir not in config.TAFSIRS or not pipeline.WINDOW_RE.match(body.window):
            raise _err(400, "bad_unit")
        try:
            a = workflow.reassign(body.tafsir, body.window, body.user_id, user["id"])
        except ValueError as e:
            raise _err(400, str(e)) from e
        return {"ok": True, "assignment": a}

    @app.get("/api/workflow")
    @operational()
    def workflow_status(user: dict = Depends(need("view_dashboard"))) -> dict:
        return workflow.status()

    @app.post("/api/workflow/sweep")
    @operational(write=True)
    def workflow_sweep(user: dict = Depends(need("manage_tasks"))) -> dict:
        out = workflow.sweep()
        db.audit("review.sweep", user_id=user["id"], detail=out)
        return out

    @app.post("/api/workflow/remind")
    @operational(write=True)
    def workflow_remind(user: dict = Depends(need("manage_tasks"))) -> dict:
        return workflow.send_reminders()

    # ---------- team & agents performance (history; mission control is the live view)
    @app.get("/api/team")
    @operational()
    def team_view(user: dict = Depends(need("view_dashboard")), days: int = 30) -> dict:
        return team.summary(user, days, reveal_arms=_reveals_arms(user))

    @app.post("/api/team/remind/{user_id}")
    @operational(write=True)
    def team_remind(user_id: int, user: dict = Depends(need("manage_tasks"))) -> dict:
        if db.mode() == "demo":
            raise _err(400, "demo_read_only")
        try:
            return workflow.remind_user(user_id, user)
        except ValueError as e:
            code = str(e)
            raise _err(429 if code == "remind_cooldown" else 400, code) from e

    # ---------- publishing to mirqah.app (super admins; no git merge)
    @app.get("/api/publish")
    @operational()
    def publish_view(user: dict = Depends(need("publish_units"))) -> dict:
        if db.mode() == "demo":
            return {"simulated": True, "history": [], "live": None}
        return {**publish.preview(), "history": publish.history()}

    @app.post("/api/publish")
    @operational(write=True)
    def publish_now(body: PublishIn, request: Request,
                    user: dict = Depends(need("publish_units"))) -> dict:
        try:
            return {"ok": True, "live": publish.publish(user, body.note)}
        except ValueError as e:
            raise _err(400, str(e)) from e

    @app.post("/api/publish/{version}/live")
    @operational(write=True)
    def publish_make_live(version: int, user: dict = Depends(need("publish_units"))) -> dict:
        try:
            return {"ok": True, "live": publish.make_live(version, user)}
        except ValueError as e:
            raise _err(404, str(e)) from e

    @app.get("/api/publish/{version}/download")
    def publish_download(version: int, user: dict = Depends(need("publish_units"))) -> Response:
        snap = publish.load(version)
        if snap is None:
            raise _err(404, "version_not_found")
        return JSONResponse(snap, headers={
            "Content-Disposition": f'attachment; filename="mirqah-published-v{version}.json"'})

    # ---------- public, read-only: what mirqah.app shows (no login, no names)
    def _public_json(body: bytes | dict, etag: str | None = None, status: int = 200) -> Response:
        raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        headers = {"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=60",
                   "X-Robots-Tag": "noindex"}
        if etag:
            headers["ETag"] = f'"{etag}"'
        return Response(raw, status_code=status, media_type="application/json; charset=utf-8",
                        headers=headers)

    @app.get("/public/v1/published.json", include_in_schema=False)
    def public_published(request: Request) -> Response:
        got = publish.live_bytes()
        if got is None:
            return _public_json({"error": "not_published"}, status=404)
        raw, meta = got
        if request.headers.get("if-none-match") == f'"{meta["sha256"]}"':
            return Response(status_code=304, headers={"ETag": f'"{meta["sha256"]}"',
                                                      "Access-Control-Allow-Origin": "*"})
        return _public_json(raw, meta["sha256"])

    @app.get("/public/v1/manifest.json", include_in_schema=False)
    def public_manifest() -> Response:
        meta = publish.live()
        if meta is None:
            return _public_json({"error": "not_published"}, status=404)
        return _public_json({"version": meta["version"], "published_at": meta["made_live_at"],
                             "units": meta["units"], "sha256": meta["sha256"],
                             "counts": (meta.get("summary") or {}).get("counts"),
                             "url": "/public/v1/published.json"}, meta["sha256"])

    # ---------- learning (how reviews teach the agents)
    @app.get("/api/learning")
    @operational()
    def learning_view(user: dict = Depends(need("view_tasks"))) -> dict:
        return learning.overview(reveal_arms=_reveals_arms(user))

    # ---------- users (a user may hold several roles)
    def _role(role_id: int) -> dict:
        r = db.row("SELECT * FROM roles WHERE id=?", (role_id,))
        if r is None:
            raise _err(400, "bad_role")
        r["permissions"] = db.loads(r["permissions"], [])
        return r

    def _can_assign(actor: dict, role: dict) -> bool:
        return set(role["permissions"]) <= set(actor["permissions"])

    def _super_admins(active_only: bool = True) -> int:
        return db.scalar(f"SELECT COUNT(DISTINCT u.id) FROM users u JOIN {db.USER_ROLES} ur ON"
                         " ur.user_id=u.id JOIN roles r ON r.id=ur.role_id WHERE"
                         " r.key='super_admin'" + (" AND u.active=1" if active_only else "")) or 0

    def _roles_of(user_id: int) -> list[dict]:
        return db.rows(f"SELECT r.id, r.key, r.name_ar, r.name_en FROM {db.USER_ROLES} ur JOIN"
                       " roles r ON r.id=ur.role_id WHERE ur.user_id=? ORDER BY r.id", (user_id,))

    def _pick_roles(ids: list[int], actor: dict) -> list[dict]:
        ids = sorted(set(ids))
        if not ids:
            raise _err(400, "bad_role")
        roles = [_role(i) for i in ids]
        for r in roles:
            if not _can_assign(actor, r):
                raise _err(403, "role_escalation")
        order = {k: i for i, k in enumerate(config.ROLE_ORDER)}
        roles.sort(key=lambda r: (order.get(r["key"], 99), r["id"]))  # primary first
        return roles

    def _set_roles(user_id: int, roles: list[dict]) -> None:
        with db.connect() as con:
            con.execute("UPDATE users SET role_id=? WHERE id=?", (roles[0]["id"], user_id))
            con.execute("DELETE FROM user_roles WHERE user_id=?", (user_id,))
            con.executemany("INSERT INTO user_roles(user_id, role_id) VALUES (?,?)",
                            [(user_id, r["id"]) for r in roles])

    @app.get("/api/users")
    def users(user: dict = Depends(need("manage_users"))) -> dict:
        rows = db.rows("SELECT u.id,u.email,u.name,u.lang,u.active,u.created_at,u.last_login_at,"
                       "u.role_id,r.key AS role_key,r.name_ar AS role_name_ar,r.name_en AS"
                       " role_name_en FROM users u JOIN roles r ON r.id=u.role_id ORDER BY u.id")
        for r in rows:
            r["active"] = bool(r["active"])
            r["roles"] = _roles_of(r["id"])
            r["role_ids"] = [x["id"] for x in r["roles"]]
        return {"users": rows}

    @app.post("/api/users")
    def user_create(body: UserIn, request: Request,
                    user: dict = Depends(need("manage_users"))) -> dict:
        email = auth.normalize_email(body.email)
        if not EMAIL_RE.match(email):
            raise _err(400, "bad_email")
        roles = _pick_roles(body.role_ids or ([body.role_id] if body.role_id else []), user)
        if db.row("SELECT 1 FROM users WHERE email=?", (email,)):
            raise _err(409, "email_exists")
        uid = db.execute("INSERT INTO users(email,name,role_id,lang,active,created_at,created_by)"
                         " VALUES (?,?,?,?,?,?,?)",
                         (email, body.name.strip(), roles[0]["id"], body.lang or "",
                          int(body.active), db.now(), user["id"]))
        _set_roles(uid, roles)
        db.audit("user.create", user_id=user["id"], target=email, ip=_ip(request),
                 detail={"roles": [r["key"] for r in roles]})
        mailed = None
        if body.notify and body.active:
            names = " + ".join(r["name_ar"] for r in roles)
            desc = " ".join(r["description_ar"] for r in roles if r["description_ar"])
            try:
                mailer.send_mail(email, mailtpl.welcome(body.name.strip(), email, names, desc,
                                                        user["name"]))
                mailed = True
            except mailer.MailError:
                mailed = False
        return {"id": uid, "mailed": mailed}

    @app.patch("/api/users/{user_id}")
    def user_patch(user_id: int, body: UserPatch, request: Request,
                   user: dict = Depends(need("manage_users"))) -> dict:
        target = db.row("SELECT u.*, r.key AS role_key FROM users u JOIN roles r ON"
                        " r.id=u.role_id WHERE u.id=?", (user_id,))
        if target is None:
            raise _err(404, "user_not_found")
        current = _roles_of(user_id)
        target_super = any(r["key"] == "super_admin" for r in current)
        changes: dict[str, Any] = {}
        if target_super and not auth.has_role(user, "super_admin"):
            raise _err(403, "role_escalation")
        new_ids = body.role_ids if body.role_ids is not None else (
            [body.role_id] if body.role_id is not None else None)
        new_roles = None
        if new_ids is not None and sorted(set(new_ids)) != sorted(r["id"] for r in current):
            new_roles = _pick_roles(new_ids, user)
            keeps_super = any(r["key"] == "super_admin" for r in new_roles)
            if user_id == user["id"] and not keeps_super and target_super:
                raise _err(400, "own_role")  # nobody removes their own super admin role
            if user_id == user["id"] and auth.has_role(user, "super_admin") is False:
                raise _err(400, "own_role")
            if target_super and not keeps_super and _super_admins() <= 1:
                raise _err(400, "last_super_admin")
        if body.active is not None and bool(body.active) != bool(target["active"]):
            if user_id == user["id"]:
                raise _err(400, "own_active")
            if not body.active and target_super and _super_admins() <= 1:
                raise _err(400, "last_super_admin")
            changes["active"] = int(body.active)
        if body.name:
            changes["name"] = body.name.strip()
        if body.lang is not None:
            changes["lang"] = body.lang
        if changes:
            sets = ", ".join(f"{k}=?" for k in changes)
            db.execute(f"UPDATE users SET {sets} WHERE id=?", (*changes.values(), user_id))
        if new_roles is not None:
            _set_roles(user_id, new_roles)
            changes["roles"] = [r["key"] for r in new_roles]
        if changes:
            lost = new_roles is not None and bool({r["id"] for r in current}
                                                  - {r["id"] for r in new_roles})
            # permissions are read on every request; sessions end only when access shrinks
            if changes.get("active") == 0 or (lost and user_id != user["id"]):
                auth.revoke_user_sessions(user_id)
            db.audit("user.update", user_id=user["id"], target=target["email"], ip=_ip(request),
                     detail={k: v for k, v in changes.items()})
            if "roles" in changes or "active" in changes:
                workflow.sweep()  # work held by someone who is no longer a specialist moves on
        return {"ok": True}

    @app.post("/api/users/{user_id}/revoke-sessions")
    def user_revoke(user_id: int, user: dict = Depends(need("manage_users"))) -> dict:
        auth.revoke_user_sessions(user_id)
        db.audit("user.revoke_sessions", user_id=user["id"], target=str(user_id))
        return {"ok": True}

    # ---------- roles
    @app.get("/api/roles")
    def roles(user: dict = Depends(need("view_dashboard"))) -> dict:
        rows = db.rows(f"SELECT r.*, (SELECT COUNT(*) FROM {db.USER_ROLES} ur JOIN users u ON"
                       " u.id=ur.user_id WHERE ur.role_id=r.id AND u.active=1) AS users"
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
        if db.scalar("SELECT COUNT(*) FROM user_roles WHERE role_id=?", (role_id,)) or \
                db.scalar("SELECT COUNT(*) FROM users WHERE role_id=?", (role_id,)):
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
            res = mailer.send_mail(to, mailtpl.test(to))
        except mailer.MailError as e:
            db.audit("smtp.test", user_id=user["id"], detail={"ok": False})
            raise _err(502, "mail_failed", detail=str(e)) from e
        db.audit("smtp.test", user_id=user["id"], detail={"ok": True, "mode": res["mode"]})
        return res

    @app.get("/api/outbox")
    def outbox(user: dict = Depends(need("manage_settings"))) -> dict:
        rows = db.rows("SELECT id,at,to_addr,subject,mode,status,error,html IS NOT NULL AS has_html"
                       " FROM outbox ORDER BY id DESC LIMIT 50")
        for r in rows:
            r["has_html"] = bool(r["has_html"])
        return {"outbox": rows}

    @app.get("/api/outbox/{mail_id}/html")
    def outbox_html(mail_id: int, user: dict = Depends(need("manage_settings"))) -> HTMLResponse:
        """Preview of a sent mail as the recipient sees it (real mail keeps the code masked)."""
        html = db.scalar("SELECT html FROM outbox WHERE id=?", (mail_id,))
        if not html:
            raise _err(404, "mail_not_found")
        html = html.replace(f"cid:{mailtpl.LOGO_CID}", "/static/brand/mail-wordmark.png")
        return HTMLResponse(html, headers={"Content-Security-Policy": (
            "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'none'")})

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

    # ---------- demo data (Settings → Demo)
    @app.get("/api/demo")
    def demo_status(user: dict = Depends(need("manage_settings"))) -> dict:
        return demo.status()

    @app.post("/api/demo/seed")
    def demo_seed(body: DemoSeedIn, request: Request,
                  user: dict = Depends(need("manage_settings"))) -> dict:
        if not 3 <= body.months <= 18:
            raise _err(400, "bad_months")
        try:
            out = demo.seed(body.months)
        except RuntimeError as e:
            raise _err(400, "demo_failed", detail=str(e)) from e
        db.audit("demo.seed", user_id=user["id"], ip=_ip(request), detail={"months": body.months})
        return out

    @app.delete("/api/demo")
    def demo_delete(request: Request, user: dict = Depends(need("manage_settings"))) -> dict:
        demo.clear()
        db.audit("demo.clear", user_id=user["id"], ip=_ip(request))
        return {"ok": True}

    # ---------- audit
    @app.get("/api/audit")
    @operational()
    def audit_log(user: dict = Depends(need("view_audit")), limit: int = 200) -> dict:
        rows = db.rows("SELECT a.*, u.name AS user_name FROM audit a LEFT JOIN users u"
                       " ON u.id=a.user_id ORDER BY a.id DESC LIMIT ?", (min(limit, 500),))
        for r in rows:
            r["detail"] = db.loads(r["detail"])
        return {"audit": rows}

    @app.get("/api/llm/perf")
    @operational()
    def llm_perf(user: dict = Depends(need("view_tasks"))) -> dict:
        return runner.perf_summary()

    @app.get("/api/llm/calls")
    @operational()
    def llm_calls(user: dict = Depends(need("view_tasks")), limit: int = 100) -> dict:
        rows = db.rows("SELECT id,task_id,agent,tafsir,window,model,status,started_at,"
                       "finished_at,duration_ms,exit_code,result FROM task_steps WHERE"
                       " finished_at IS NOT NULL AND agent IN ('classifier','verifier','chair')"
                       " ORDER BY finished_at DESC LIMIT ?", (min(limit, 500),))
        for r in rows:
            r["result"] = db.loads(r["result"])
        return runner.redact_engine({"calls": rows}, user)
