"""Tests for the committee console (console/). Skipped when FastAPI is not installed.

The end-to-end test runs the real pipeline (src/run_window.py) against a copy of
one al-Nur tafsir in a temp folder, with a tiny fake Ollama server, so nothing
under the repo's data/ is touched.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from console import auth, config, db, runner, settings  # noqa: E402
from console.app import create_app  # noqa: E402

H = {"X-Mirqah": "1"}


# ------------------------------------------------------------------ fixtures

@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VAR_DIR", tmp_path / "var")
    monkeypatch.setattr(config, "REPO_ROOT", ROOT)
    auth.reset_rate_limits()
    app = create_app(start_worker=False)
    client = TestClient(app)
    yield client
    runner.stop()


def add_user(email: str, role: str, name: str = "Test") -> int:
    rid = db.scalar("SELECT id FROM roles WHERE key=?", (role,))
    return db.execute("INSERT INTO users(email,name,role_id,lang,active,created_at) VALUES"
                      " (?,?,?,?,1,?)", (email, name, rid, "", db.now()))


def login(client: TestClient, email: str) -> None:
    r = client.post("/api/auth/request-otp", json={"email": email}, headers=H)
    assert r.status_code == 200, r.text
    code = r.json()["mock_code"]
    r = client.post("/api/auth/verify-otp", json={"email": email, "code": code}, headers=H)
    assert r.status_code == 200, r.text


# ------------------------------------------------------------------ auth

def test_login_only_registered_users(env):
    add_user("admin@example.com", "super_admin")
    r = env.post("/api/auth/request-otp", json={"email": "stranger@example.com"}, headers=H)
    assert r.status_code == 200 and "mock_code" not in r.json()
    r = env.post("/api/auth/request-otp", json={"email": "Admin@Example.com"}, headers=H)
    assert r.status_code == 200 and re.fullmatch(r"\d{6}", r.json()["mock_code"])
    bad = env.post("/api/auth/verify-otp", json={"email": "admin@example.com", "code": "000000x"},
                   headers=H)
    assert bad.status_code == 401
    assert env.get("/api/me").status_code == 401
    good = env.post("/api/auth/verify-otp", json={"email": "admin@example.com",
                                                  "code": r.json()["mock_code"]}, headers=H)
    assert good.status_code == 200
    me = env.get("/api/me").json()["user"]
    assert me["role"]["key"] == "super_admin" and "manage_settings" in me["permissions"]
    # the code cannot be used twice
    again = env.post("/api/auth/verify-otp", json={"email": "admin@example.com",
                                                   "code": r.json()["mock_code"]}, headers=H)
    assert again.status_code == 401
    # mock mail landed in the outbox table and as an .eml file
    assert db.scalar("SELECT COUNT(*) FROM outbox WHERE to_addr='admin@example.com'") == 1
    assert list((config.VAR_DIR / "outbox").glob("*.eml"))


def test_otp_locks_after_max_attempts(env):
    add_user("a@example.com", "viewer")
    env.post("/api/auth/request-otp", json={"email": "a@example.com"}, headers=H)
    for _ in range(settings.get("security")["otp_max_attempts"]):
        env.post("/api/auth/verify-otp", json={"email": "a@example.com", "code": "999999"},
                 headers=H)
    r = env.post("/api/auth/verify-otp", json={"email": "a@example.com", "code": "999999"},
                 headers=H)
    assert r.json()["detail"]["error"] == "otp_locked"


def test_csrf_header_required(env):
    r = env.post("/api/auth/request-otp", json={"email": "a@example.com"})
    assert r.status_code == 403


def test_deactivated_user_loses_session(env):
    add_user("boss@example.com", "super_admin")
    uid = add_user("op@example.com", "committee_operator")
    login(env, "op@example.com")
    assert env.get("/api/dashboard").status_code == 200
    db.execute("UPDATE users SET active=0 WHERE id=?", (uid,))
    assert env.get("/api/dashboard").status_code == 401


# ------------------------------------------------------------------ RBAC

def test_viewer_cannot_change_settings_or_users(env):
    add_user("v@example.com", "viewer")
    login(env, "v@example.com")
    assert env.patch("/api/settings/smtp", json={"port": 25}, headers=H).status_code == 403
    assert env.get("/api/users").status_code == 403
    assert env.post("/api/tasks", json={"kind": "dryrun", "scope": "sample"},
                    headers=H).status_code == 403


def test_production_hides_mock_code_and_masks_real_mail(env, monkeypatch):
    from console import mailer
    add_user("p@example.com", "viewer")
    monkeypatch.setattr(config, "PRODUCTION", True)
    r = env.post("/api/auth/request-otp", json={"email": "p@example.com"}, headers=H)
    assert r.status_code == 200 and "mock_code" not in r.json()

    sent = []

    class FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, **k):
            pass

        def login(self, *a):
            pass

        def send_message(self, msg):
            sent.append(msg.get_body(("plain",)).get_content())

    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    settings.update("smtp", {"mode": "smtp", "host": "smtp.example.com",
                             "from_email": "no-reply@example.com"}, None)
    settings.update("security", {"otp_resend_s": 0}, None)
    r = env.post("/api/auth/request-otp", json={"email": "p@example.com"}, headers=H)
    assert r.status_code == 200 and "mock_code" not in r.json()
    code = re.search(r"\b(\d{6})\b", sent[-1]).group(1)
    stored = db.scalar("SELECT body FROM outbox WHERE mode='smtp' ORDER BY id DESC LIMIT 1")
    assert code not in stored and "••••••" in stored


def test_cloudflare_proxy_ip_secure_cookie_and_allowed_hosts(env, monkeypatch):
    add_user("cf@example.com", "viewer")
    monkeypatch.setattr(config, "TRUST_CF_IP", True)
    monkeypatch.setattr(config, "SECURE_COOKIES", True)
    monkeypatch.setattr(config, "ALLOWED_HOSTS", ("console.example.com",))
    assert env.get("/api/public").status_code == 421  # Host: testserver
    ok = env.get("/api/public", headers={"host": "console.example.com"})
    assert ok.status_code == 200
    assert ok.headers["strict-transport-security"].startswith("max-age=")
    assert env.get("/api/public", headers={"host": "127.0.0.1:8800"}).status_code == 200
    hh = {**H, "host": "console.example.com", "cf-connecting-ip": "203.0.113.7"}
    r = env.post("/api/auth/request-otp", json={"email": "cf@example.com"}, headers=hh)
    code = r.json()["mock_code"]
    r = env.post("/api/auth/verify-otp", json={"email": "cf@example.com", "code": code},
                 headers=hh)
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "secure" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert db.scalar("SELECT ip FROM audit WHERE action='auth.login' ORDER BY id DESC"
                     " LIMIT 1") == "203.0.113.7"
    # a forged header is ignored when the console is not behind Cloudflare
    monkeypatch.setattr(config, "TRUST_CF_IP", False)
    env.post("/api/auth/request-otp", json={"email": "nobody@example.com"},
             headers={**hh, "cf-connecting-ip": "198.51.100.9"})
    assert db.scalar("SELECT ip FROM audit WHERE action='auth.otp_unknown' ORDER BY id DESC"
                     " LIMIT 1") != "198.51.100.9"


def test_guest_access_is_off_by_default_and_read_only(env):
    add_user("boss@example.com", "super_admin")
    assert env.get("/api/public").json()["guest_access"] is False
    r = env.post("/api/auth/guest", headers=H)
    assert r.status_code == 403 and r.json()["detail"]["error"] == "guest_disabled"
    settings.update("security", {"guest_access": True}, None)
    assert env.get("/api/public").json()["guest_access"] is True
    r = env.post("/api/auth/guest", headers=H)
    assert r.status_code == 200, r.text
    me = env.get("/api/me").json()["user"]
    assert me["is_guest"] and set(me["permissions"]) <= set(config.GUEST_PERMISSIONS)
    assert env.get("/api/dashboard").status_code == 200
    assert env.patch("/api/settings/security", json={"guest_access": False},
                     headers=H).status_code == 403
    assert env.post("/api/tasks", json={"kind": "dryrun", "scope": "sample"},
                    headers=H).status_code == 403
    # even if someone gives the guest row a powerful role, guests stay read-only
    admin_role = db.scalar("SELECT id FROM roles WHERE key='super_admin'")
    db.execute("UPDATE users SET role_id=? WHERE email=?", (admin_role, config.GUEST_EMAIL))
    me = env.get("/api/me").json()["user"]
    assert "manage_settings" not in me["permissions"]
    assert env.get("/api/users").status_code == 403
    # deactivating the guest row ends guest sessions and blocks new ones
    db.execute("UPDATE users SET active=0 WHERE email=?", (config.GUEST_EMAIL,))
    assert env.get("/api/me").status_code == 401
    assert env.post("/api/auth/guest", headers=H).status_code == 403


def test_cli_settings_set_show_and_mail_test(env, capsys):
    from console.__main__ import main as cli
    assert cli(["settings-set", "smtp", "mode=smtp", "host=smtp-relay.brevo.com", "port=587",
                "security=starttls", "from_email=no-reply@example.com"]) == 0
    s = settings.get("smtp")
    assert (s["mode"], s["host"], s["port"]) == ("smtp", "smtp-relay.brevo.com", 587)
    assert cli(["settings-set", "security", "show_mock_code=false", "guest_access=on"]) == 0
    sec = settings.get("security")
    assert sec["show_mock_code"] is False and sec["guest_access"] is True
    assert cli(["settings-set", "smtp", "password=hunter2"]) == 2  # secrets stay in env
    assert cli(["settings-set", "smtp", "mode=carrier-pigeon"]) == 2
    assert cli(["settings-set", "nope", "a=b"]) == 2
    capsys.readouterr()
    assert cli(["settings-show", "smtp"]) == 0
    assert "smtp-relay.brevo.com" in capsys.readouterr().out
    assert cli(["settings-set", "smtp", "mode=mock"]) == 0
    assert cli(["mail-test", "--to", "x@example.com"]) == 0
    assert db.scalar("SELECT COUNT(*) FROM outbox WHERE to_addr='x@example.com'") == 1


def test_no_privilege_escalation_and_last_super_admin(env):
    sa = add_user("sa@example.com", "super_admin")
    rid = db.execute("INSERT INTO roles(key,name_ar,name_en,system,permissions) VALUES"
                     " ('user_admin','مدير','User admin',0,?)",
                     (json.dumps(["view_dashboard", "manage_users"]),))
    add_user("ua@example.com", "viewer")
    db.execute("UPDATE users SET role_id=? WHERE email='ua@example.com'", (rid,))
    login(env, "ua@example.com")
    sa_role = db.scalar("SELECT id FROM roles WHERE key='super_admin'")
    r = env.post("/api/users", json={"email": "x@example.com", "name": "X", "role_id": sa_role},
                 headers=H)
    assert r.status_code == 403
    r = env.patch(f"/api/users/{sa}", json={"active": False}, headers=H)
    assert r.status_code == 403
    env.post("/api/auth/logout", headers=H)
    login(env, "sa@example.com")
    r = env.patch(f"/api/users/{sa}", json={"active": False}, headers=H)
    assert r.json()["detail"]["error"] == "own_active"
    viewer = db.scalar("SELECT id FROM roles WHERE key='viewer'")
    r = env.patch(f"/api/users/{sa}", json={"role_id": viewer}, headers=H)
    assert r.json()["detail"]["error"] == "own_role"
    r = env.patch(f"/api/roles/{sa_role}", json={"permissions": []}, headers=H)
    assert r.json()["detail"]["error"] == "system_role"


# ------------------------------------------------------------------ settings & languages

def test_settings_validation_and_secret_redaction(env):
    add_user("sa@example.com", "super_admin")
    login(env, "sa@example.com")
    assert env.patch("/api/settings/smtp", json={"port": 0}, headers=H).status_code == 400
    r = env.patch("/api/settings/smtp", json={"host": "smtp.example.com", "username": "u",
                                              "password": "s3cret", "from_email": "n@example.com"},
                  headers=H)
    assert r.status_code == 200
    got = env.get("/api/settings").json()["settings"]["smtp"]
    assert got["password"] == "" and got["password_set"] is True
    # empty password on save keeps the stored one
    env.patch("/api/settings/smtp", json={"password": "", "port": 465}, headers=H)
    assert settings.get("smtp")["password"] == "s3cret"
    audit = db.rows("SELECT detail FROM audit WHERE action='settings.update'")
    assert all("s3cret" not in (a["detail"] or "") for a in audit)
    assert env.patch("/api/settings/llm", json={"classifier_model": "bad tag;rm"},
                     headers=H).status_code == 400


def test_languages_default_and_overrides(env):
    add_user("sa@example.com", "super_admin")
    login(env, "sa@example.com")
    pub = env.get("/api/public").json()
    assert pub["default_lang"] == "ar"
    assert {x["code"] for x in pub["languages"]} >= {"ar", "en", "zh", "ur"}
    assert env.patch("/api/languages/ar", json={"enabled": False},
                     headers=H).json()["detail"]["error"] == "default_must_be_enabled"
    assert env.post("/api/languages", json={"code": "fr", "name_native": "Français",
                                            "name_en": "French", "dir": "ltr"},
                    headers=H).status_code == 200
    env.put("/api/translations/fr", json={"nav.tasks": "Tâches"}, headers=H)
    b = env.get("/api/i18n/fr").json()
    assert b["strings"]["nav.tasks"] == "Tâches"
    assert b["strings"]["nav.users"] == "Users"  # falls back to English
    for code in ("ar", "en", "zh", "ur"):
        assert env.get(f"/api/i18n/{code}").json()["translated"] == \
            env.get("/api/i18n/en").json()["total"]


# ------------------------------------------------------------------ tasks & gates

def test_sample_preview_and_bulk_gate(env):
    add_user("sa@example.com", "super_admin")
    login(env, "sa@example.com")
    p = env.post("/api/tasks/preview", json={"kind": "committee", "scope": "sample"},
                 headers=H).json()
    assert p["windows"] == 9 and p["steps"] == 27 and not p["bulk"]
    p = env.post("/api/tasks/preview", json={"kind": "committee", "scope": "surah"},
                 headers=H).json()
    assert p["windows"] == 296 and p["blocked"] == "bulk_gate_phase0"
    r = env.post("/api/tasks", json={"kind": "committee", "scope": "surah"}, headers=H)
    assert r.json()["detail"]["error"] == "bulk_gate_phase0"
    p = env.post("/api/tasks/preview", json={"kind": "dryrun", "scope": "surah"},
                 headers=H).json()
    assert p["blocked"] is None  # a packet check never calls a model


def test_engine_offline_blocks_model_runs_but_not_packet_checks(env):
    add_user("op@example.com", "super_admin")
    login(env, "op@example.com")
    settings.update("llm", {"base_url": "http://127.0.0.1:9"}, None)  # nothing listens there
    r = env.post("/api/tasks", json={"kind": "committee", "scope": "sample"}, headers=H)
    assert r.status_code == 409 and r.json()["detail"]["error"] == "engine_offline"
    p = env.post("/api/tasks/preview", json={"kind": "committee", "scope": "sample"}, headers=H).json()
    assert p["blocked"] == "engine_offline"
    assert env.post("/api/tasks", json={"kind": "dryrun", "scope": "sample"}, headers=H).status_code == 200


# ------------------------------------------------------------------ view as user

def test_view_as_is_super_admin_only_read_only_and_audited(env):
    add_user("sa@example.com", "super_admin", "Admin")
    add_user("spec@example.com", "specialist", "Spec")
    add_user("view@example.com", "viewer", "Viewer")
    login(env, "sa@example.com")
    VA = {**H, "X-Mirqah-View-As": "spec@example.com"}
    users = env.get("/api/view-as/users").json()["users"]
    assert {u["email"] for u in users} == {"spec@example.com", "view@example.com"}
    assert env.post("/api/view-as", json={"email": "spec@example.com"}, headers=H).status_code == 200
    me = env.get("/api/me", headers=VA).json()["user"]
    assert me["email"] == "spec@example.com" and me["view_as"] and me["real_user"]["email"] == "sa@example.com"
    assert "review_units" in me["permissions"] and "manage_settings" not in me["permissions"]
    assert env.get("/api/settings", headers=VA).status_code == 403          # the specialist cannot
    for method, path, body in (("patch", "/api/me", {"name": "x"}),
                               ("post", "/api/users", {"email": "n@example.com", "name": "n", "role_id": 1}),
                               ("patch", "/api/settings/general", {"team_name": "x"})):
        r = getattr(env, method)(path, json=body, headers=VA)
        assert r.status_code == 423 and r.json()["detail"]["error"] == "view_as_read_only", path
    assert env.post("/api/view-as/stop", headers=VA).status_code == 200
    acts = [r["action"] for r in db.rows("SELECT action FROM audit WHERE action LIKE 'view_as.%' ORDER BY id")]
    assert acts == ["view_as.start", "view_as.stop"]
    assert db.scalar("SELECT user_id FROM audit WHERE action='view_as.start'") == \
        db.scalar("SELECT id FROM users WHERE email='sa@example.com'")
    # without the header the super admin is back
    assert env.get("/api/me", headers=H).json()["user"]["email"] == "sa@example.com"
    # a non-super-admin cannot switch: the header is ignored and the routes refuse
    env.post("/api/auth/logout", headers=H)
    login(env, "view@example.com")
    me = env.get("/api/me", headers={**H, "X-Mirqah-View-As": "sa@example.com"}).json()["user"]
    assert me["email"] == "view@example.com" and not me["view_as"]
    assert env.post("/api/view-as", json={"email": "sa@example.com"}, headers=H).status_code == 403
    assert env.get("/api/view-as/users").status_code == 403


# ------------------------------------------------------------------ demo mode

def test_demo_mode_is_isolated_and_read_only(env):
    from console import demo
    add_user("sa@example.com", "super_admin")
    login(env, "sa@example.com")
    assert env.get("/api/public").json()["demo_available"] is False
    assert env.post("/api/mode", json={"mode": "demo"}, headers=H).status_code == 409
    st = env.post("/api/demo/seed", json={"months": 3}, headers=H).json()
    assert st["available"] and st["counts"]["demo_units"] == 296 and st["counts"]["tasks"] > 0
    assert db.scalar("SELECT COUNT(*) FROM tasks") == 0                    # live DB untouched
    assert env.post("/api/mode", json={"mode": "demo"}, headers=H).status_code == 200
    assert env.get("/api/me").json()["user"]["mode"] == "demo"
    d = env.get("/api/dashboard").json()
    assert d["simulated"] and d["llm"]["simulated"] and d["progress"]["totals"]["windows"] == 296
    assert d["progress"]["totals"]["committee"] > 0 and d["gates"]["phase0_merged"]
    units = env.get("/api/review/units").json()["units"]
    assert units and all(u["committee"] for u in units)
    rv = env.get(f"/api/review/{units[0]['tafsir']}/{units[0]['window']}").json()
    assert rv["simulated"] and all(m["text"] is None for m in rv["moves"])  # never tafsir text
    assert env.get("/api/reports").json()["reports"]
    assert env.get("/api/tasks").json()["tasks"]
    # hover cards read the simulated steps (with simulated token counts) and model memory
    wk = env.get("/api/agents/classifier").json()["week"]
    assert wk["n"] > 0 and wk["tokens_in"] > 0 and wk["p95_s"] is not None
    brain = env.get("/api/agents/model").json()
    assert brain["ps"]["simulated"] and len(brain["ps"]["models"]) == 2
    spec = env.get("/api/agents/specialist").json()
    assert spec["review"]["moves"] >= spec["review"]["decided"] >= 0 and "n" in spec["week"]
    r = env.post("/api/tasks", json={"kind": "dryrun", "scope": "sample"}, headers=H)
    assert r.status_code == 423 and r.json()["detail"]["error"] == "demo_read_only"
    assert env.post("/api/review/decision", json={"tafsir": "al_saadi", "window": "24_35", "move_id": "P-m01",
                                                  "decision": "approve", "compared_with_source": True},
                    headers=H).status_code == 423
    # settings stay live and writable in demo mode
    assert env.patch("/api/settings/demo", json={"guest_mode": "demo"}, headers=H).status_code == 200
    assert env.post("/api/mode", json={"mode": "live"}, headers=H).status_code == 200
    d = env.get("/api/dashboard").json()
    assert not d["simulated"] and d["progress"]["totals"]["committee"] == 0
    # guests follow Settings → Demo → guest_mode until they switch themselves
    settings.update("security", {"guest_access": True}, None)
    g = TestClient(env.app)
    assert g.post("/api/auth/guest", headers=H).status_code == 200
    assert g.get("/api/me").json()["user"]["mode"] == "demo"
    assert g.get("/api/dashboard").json()["simulated"]
    demo.clear()
    assert env.get("/api/public").json()["demo_available"] is False


# ------------------------------------------------------------------ mail templates

def test_html_mail_with_inline_logo_masked_outbox_and_welcome(env, monkeypatch):
    from console import mailer
    sent = []

    class FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, **k):
            pass

        def login(self, *a):
            pass

        def send_message(self, msg):
            sent.append(msg)

    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    add_user("sa@example.com", "super_admin", "Admin")
    login(env, "sa@example.com")
    mock_html = db.scalar("SELECT html FROM outbox ORDER BY id DESC LIMIT 1")
    assert 'dir="rtl"' in mock_html and "cid:mqlogo" in mock_html
    settings.update("smtp", {"mode": "smtp", "host": "smtp.example.com", "from_email": "no-reply@example.com"},
                    None)
    settings.update("general", {"console_url": "https://console.example.com"}, None)
    settings.update("security", {"otp_resend_s": 0}, None)
    assert env.post("/api/auth/request-otp", json={"email": "sa@example.com"}, headers=H).status_code == 200
    msg = sent[-1]
    kinds = [p.get_content_type() for p in msg.walk()]
    assert {"text/plain", "text/html", "image/png"} <= set(kinds)
    html = msg.get_body(("html",)).get_content()
    code = re.search(r"\b(\d{6})\b", msg.get_body(("plain",)).get_content()).group(1)
    assert code in html and "https://console.example.com" in html
    stored = db.row("SELECT body, html FROM outbox ORDER BY id DESC LIMIT 1")
    assert code not in stored["body"] and code not in stored["html"] and "••••••" in stored["html"]
    rid = db.scalar("SELECT id FROM roles WHERE key='specialist'")
    r = env.post("/api/users", json={"email": "new@example.com", "name": "New", "role_id": rid}, headers=H)
    assert r.status_code == 200 and r.json()["mailed"] is True
    assert sent[-1]["To"] == "new@example.com" and "أهلاً" in sent[-1]["Subject"]
    mid = db.scalar("SELECT id FROM outbox ORDER BY id DESC LIMIT 1")
    page = env.get(f"/api/outbox/{mid}/html")
    assert page.status_code == 200 and "/static/brand/mail-wordmark.png" in page.text
    assert env.get("/static/brand/mail-wordmark.png").status_code == 200


def test_work_root_used_only_when_present(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_WORK", str(tmp_path / "work"))
    assert config.work_root() == config.REPO_ROOT          # missing → release folder
    (tmp_path / "work" / "data").mkdir(parents=True)
    assert config.work_root() == (tmp_path / "work").resolve()


# ------------------------------------------------------------------ end to end

class _FakeOllama(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/tags":
            self._json({"models": [{"name": "qwen2.5:14b", "details": {"family": "qwen2"}},
                                   {"name": "gemma3:12b", "details": {"family": "gemma3"}}]})
        elif self.path == "/api/version":
            self._json({"version": "0.0-test"})
        elif self.path == "/api/ps":
            self._json({"models": [{"name": "qwen2.5:14b", "model": "qwen2.5:14b",
                                    "size": 9_700_000_000, "size_vram": 9_700_000_000,
                                    "context_length": 8192,
                                    "expires_at": "2099-01-01T00:04:00.123456789+03:00"}]})
        else:
            self._json({}, 404)

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        user = data["messages"][-1]["content"]
        found = re.search(r"window_id: (\S+)", user)  # method specialists send no window id
        wid = found.group(1) if found else "none"
        ids = re.findall(r"\b(s\d{3})\b", user.split("## مخطط")[0])
        sid = ids[-1] if ids else "s001"
        reply = {"window": wid, "moves": [{
            "move_id": "m01", "span_ids": [sid], "primary": "M_LUGHA", "secondary": [],
            "content_tags": [], "certainty": "weak", "evidence_span_ids": [sid],
            "author_verdict_span_ids": [], "references": {"verses": [], "hadith": [],
                                                           "persons": []},
            "alternatives": [], "rationale_ar": "اختبار"}]}
        self._json({"choices": [{"message": {"content": json.dumps(reply, ensure_ascii=False)}}],
                    "usage": {"prompt_tokens": len(user) // 3, "completion_tokens": 120}})


def test_committee_runs_pipeline_end_to_end(env, tmp_path, monkeypatch):
    # isolated repo copy: src + one tafsir of al-Nur
    fake_root = tmp_path / "repo"
    shutil.copytree(ROOT / "src", fake_root / "src",
                    ignore=shutil.ignore_patterns("__pycache__"))
    for extra in ("schema", "method"):
        if (ROOT / extra).is_dir():
            shutil.copytree(ROOT / extra, fake_root / extra)
    src_base = ROOT / "data" / "nur" / "al_saadi"
    dst_base = fake_root / "data" / "nur" / "al_saadi"
    for sub in ("raw", "layers", "spans", "windows", "markers", "packets"):
        if (src_base / sub).is_dir():
            shutil.copytree(src_base / sub, dst_base / sub)
    monkeypatch.setattr(config, "REPO_ROOT", fake_root)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOllama)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        add_user("sa@example.com", "super_admin")
        login(env, "sa@example.com")
        port = server.server_address[1]
        assert env.patch("/api/settings/llm", json={"base_url": f"http://127.0.0.1:{port}"},
                         headers=H).status_code == 200
        probe = env.get("/api/llm/probe").json()
        assert probe["reachable"] and probe["classifier_installed"] and probe["verifier_installed"]
        r = env.post("/api/tasks", json={"kind": "committee", "scope": "sample",
                                         "tafsirs": ["al_saadi"]}, headers=H)
        assert r.status_code == 200, r.text
        tid = r.json()["id"]
        runner.start()
        deadline = time.time() + 120
        while time.time() < deadline:
            t = env.get(f"/api/tasks/{tid}").json()
            if t["task"]["status"] in ("done", "failed"):
                break
            time.sleep(0.5)
        assert t["task"]["status"] == "done", json.dumps(t, ensure_ascii=False)[:2000]
        assert [s["agent"] for s in t["steps"]] == ["classifier", "verifier", "chair"]
        assert all(s["result"]["moves"] == 1 for s in t["steps"][:2])
        assert t["steps"][2]["result"]["moves"] >= 1
        # outputs exist only in the temp copy, written by the pipeline
        assert (dst_base / "verified" / "qwen2_5_14b" / "24_35.json").is_file()
        assert (dst_base / "verified" / "gemma3_12b" / "24_35.json").is_file()
        assert (dst_base / "committee" / "24_35.json").is_file()
        assert (dst_base / "verified" / "committee" / "24_35.json").is_file()
        assert not (ROOT / "data" / "nur" / "al_saadi" / "moves").exists()

        # dashboard, progress, chair preview
        dash = env.get("/api/dashboard").json()
        saadi = next(x for x in dash["progress"]["tafsirs"] if x["tafsir"] == "al_saadi")
        assert saadi["classifier"] == 1 and saadi["both"] == 1 and saadi["committee"] == 1
        rv = env.get("/api/review/al_saadi/24_35").json()
        assert rv["is_committee"] and rv["annotator"] == "committee"
        first = rv["moves"][0]
        assert first["key"] == "P-m01" and first["committee"]["committee_route"] == "specialist"
        units = env.get("/api/review/units").json()["units"]
        assert units and units[0]["committee"] is True

        # only the specialist role decides — a super admin adds it as a second role
        body = {"tafsir": "al_saadi", "window": "24_35", "move_id": "P-m01", "decision": "approve"}
        assert env.post("/api/review/decision", json=body, headers=H).json()["detail"][
            "error"] == "specialists_only"
        assert rv["can_decide"] is False and rv["assignment"] is None
        uid = db.scalar("SELECT id FROM users WHERE email='sa@example.com'")
        role = {k: db.scalar("SELECT id FROM roles WHERE key=?", (k,))
                for k in ("super_admin", "specialist")}
        assert env.patch(f"/api/users/{uid}", json={"role_ids": [role["specialist"]]},
                         headers=H).json()["detail"]["error"] == "own_role"
        assert env.patch(f"/api/users/{uid}", json={"role_ids": list(role.values())},
                         headers=H).status_code == 200
        me = env.get("/api/me").json()["user"]  # still signed in: only a role was added
        assert me["can_decide"] and set(me["role_keys"]) == {"super_admin", "specialist"}
        assert env.get("/api/review/al_saadi/24_35").json()["can_decide"] is True
        # specialist decision rules (keyed by committee row, not bare move_id)
        assert env.post("/api/review/decision", json=body, headers=H).json()["detail"][
            "error"] == "compare_first"
        body["compared_with_source"] = True
        assert env.post("/api/review/decision", json=body, headers=H).status_code == 200
        assert env.post("/api/review/decision", json={**body, "decision": "reject"},
                        headers=H).json()["detail"]["error"] == "note_required"

        # skip_done: a second run skips both steps
        tid2 = env.post("/api/tasks", json={"kind": "committee", "scope": "sample",
                                            "tafsirs": ["al_saadi"]}, headers=H).json()["id"]
        deadline = time.time() + 60
        while time.time() < deadline:
            t2 = env.get(f"/api/tasks/{tid2}").json()
            if t2["task"]["status"] in ("done", "failed"):
                break
            time.sleep(0.3)
        assert t2["task"]["skipped_steps"] == 3

        # daily report
        day = runner.local_now().date().isoformat()
        rep = env.post(f"/api/reports/{day}/generate", headers=H).json()["content"]
        assert rep["agents"]["classifier"]["done"] == 1
        assert rep["agents"]["chair"]["done"] == 1 and rep["committee"]["windows"] == 1
        # hover cards: real timings and the token counts the model server reported
        cls = t["steps"][0]["result"]
        assert cls["model_calls"] == 1 and cls["tokens_out"] == 120 and cls["tokens_in"] > 1000
        card = env.get("/api/agents/classifier").json()
        assert card["model"] == "qwen2.5:14b" and card["today"]["ok"] == 1
        assert card["today"]["tokens_in"] == cls["tokens_in"] and card["today"]["tokens_out"] == 120
        assert card["today"]["median_s"] is not None and card["today"]["fail_pct"] == 0
        assert card["loaded"]["context_length"] == 8192 and card["loaded"]["expires_at"] is None
        assert card["arms_today"] == {"A": 1} and len(card["spark"]) == 1
        assert card["queue"]["waiting"] == 0 and "now" not in card
        assert env.get("/api/agents/verifier").json()["loaded"] == {"name": "gemma3:12b",
                                                                   "loaded": False}
        chair = env.get("/api/agents/chair").json()
        assert chair["outcomes_today"]["moves"] >= 1 and chair["today"]["tokens_in"] == 0
        assert env.get("/api/agents/checker").json()["today"]["ok"] == 2
        brain = env.get("/api/agents/model").json()
        assert brain["ps"]["available"] and brain["today"]["calls"] == 2
        assert brain["per_model"]["qwen2.5:14b"]["tokens_out"] == 120
        assert brain["llm"]["reachable"]
        assert env.get("/api/agents/nope").json()["detail"]["error"] == "agent_unknown"
        perf = env.get("/api/llm/perf").json()["agents"]
        assert {a["agent"] for a in perf} == {"classifier", "verifier", "chair"}
        assert all(a["median_s"] is not None for a in perf)
        assert rep["decisions"]["approve"] == 1
        md = env.get(f"/api/reports/{day}/markdown").text
        assert "التقرير اليومي" in md
        assert env.post(f"/api/reports/{day}/mail", headers=H).json()["sent"] == 1
    finally:
        runner.stop()
        server.shutdown()


def test_ui_assets_are_versioned_so_cdn_cache_never_hides_a_release(env):
    from console.app import asset_version
    r = env.get("/")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
    v = asset_version()
    for path in ("/static/app.js", "/static/app.css", "/static/logo.svg", "/static/brand/icon-180.png"):
        assert f'"{path}?v={v}"' in r.text
    assert "immutable" in env.get(f"/static/app.js?v={v}").headers["cache-control"]
    assert env.get("/static/app.js").headers["cache-control"] == "no-cache"
    assert env.get("/static/app.js?v=stale").headers["cache-control"] == "no-cache"
    assert env.get("/static/brand/mirqah-wordmark.svg").headers["cache-control"] == "no-cache"


def test_steps_grouped_by_model_and_timeout_passed_to_pipeline(env, monkeypatch):
    pairs = [("al_tabari", "24_2_p01"), ("al_tabari", "24_2_p02"), ("ibn_kathir", "24_2")]
    from console import pipeline
    monkeypatch.setattr(pipeline, "resolve_scope", lambda scope, ayat, tafsirs: pairs)
    steps = runner.plan_steps("committee", "ayat", "2", ["al_tabari", "ibn_kathir"])
    assert [s["agent"] for s in steps] == ["classifier"] * 3 + ["verifier"] * 3 + ["chair"] * 3
    assert [(s["tafsir"], s["window"]) for s in steps[:3]] == pairs
    assert {s["model"] for s in steps[:3]} == {"qwen2.5:14b"}
    assert {s["model"] for s in steps[3:6]} == {"gemma3:12b"}

    monkeypatch.setattr(pipeline, "window_ids", lambda tafsir: ["24_2_p01"])
    cmd, envv = runner._step_command({"agent": "verifier", "tafsir": "al_tabari",
                                      "window": "24_2_p01", "model": "gemma3:12b"})
    assert envv["LLM_TIMEOUT_S"] == str(settings.get("llm")["step_timeout_s"] - 15)
    assert "--api" in cmd and "gemma3:12b" in cmd


def test_chair_waits_for_both_verified_outputs(env):
    assert runner._chair_inputs_missing({"tafsir": "al_tabari", "window": "24_99_p99"}) == [
        "classifier", "verifier"]


def test_classify_api_timeout_from_env(monkeypatch):
    sys.path.insert(0, str(ROOT / "src"))
    import classify_api
    monkeypatch.delenv("LLM_TIMEOUT_S", raising=False)
    assert classify_api.request_timeout_s() == 120
    monkeypatch.setenv("LLM_TIMEOUT_S", "585")
    assert classify_api.request_timeout_s() == 585
    monkeypatch.setenv("LLM_TIMEOUT_S", "99999")
    assert classify_api.request_timeout_s() == 3600
    monkeypatch.setenv("LLM_TIMEOUT_S", "abc")
    assert classify_api.request_timeout_s() == 120


def test_retry_failed_groups_steps_by_model(env):
    uid = add_user("op@example.com", "super_admin")
    tid = db.execute("INSERT INTO tasks(kind,title_ar,params,status,created_by,created_at,total_steps)"
                     " VALUES ('committee','t','{}','failed',?,?,4)", (uid, db.now()))
    for seq, agent in enumerate(["verifier", "chair", "classifier", "verifier"]):
        db.execute("INSERT INTO task_steps(task_id,seq,agent,tafsir,window,model,status)"
                   " VALUES (?,?,?,?,?,?,'failed')", (tid, seq, agent, "al_tabari", f"24_2_p0{seq}", None))
    new_id = runner.retry_failed(tid, {"id": uid})
    agents = [r["agent"] for r in db.rows("SELECT agent FROM task_steps WHERE task_id=? ORDER BY seq", (new_id,))]
    assert agents == ["classifier", "verifier", "verifier", "chair"]


def test_chair_without_verifier_is_skipped_not_failed_and_retried(env, monkeypatch):
    uid = add_user("op2@example.com", "super_admin")
    tid = db.execute("INSERT INTO tasks(kind,title_ar,params,status,created_by,created_at,total_steps)"
                     " VALUES ('committee','t','{}','running',?,?,1)", (uid, db.now()))
    sid = db.execute("INSERT INTO task_steps(task_id,seq,agent,tafsir,window,model,status)"
                     " VALUES (?,0,'chair','al_tabari','24_99_p99',NULL,'queued')", (tid,))
    task = db.row("SELECT * FROM tasks WHERE id=?", (tid,))
    step = db.row("SELECT * FROM task_steps WHERE id=?", (sid,))
    runner._run_step(task, step)
    st = db.row("SELECT * FROM task_steps WHERE id=?", (sid,))
    assert st["status"] == "skipped"
    assert json.loads(st["result"]) == {"reason": "agent_missing", "missing": ["classifier", "verifier"]}
    t = db.row("SELECT * FROM tasks WHERE id=?", (tid,))
    assert t["failed_steps"] == 0 and t["skipped_steps"] == 1
    db.execute("UPDATE tasks SET status='done' WHERE id=?", (tid,))  # retries start once it ended
    new_id = runner.retry_failed(tid, {"id": uid})
    assert [r["agent"] for r in db.rows("SELECT agent FROM task_steps WHERE task_id=?", (new_id,))] == ["chair"]
    for lang in ("ar", "en", "zh", "ur"):
        d = json.loads((ROOT / "console/static/i18n" / f"{lang}.json").read_text(encoding="utf-8"))
        assert all(k in d for k in ("tasks.skip.no_verifier", "tasks.skip.no_classifier",
                                    "tasks.skip.no_both", "tasks.skip.already"))


# ------------------------------------------------------------------ A/B arms and teaching

def test_ab_task_runs_both_arms_blind_review_and_teaching(env, tmp_path, monkeypatch):
    fake_root = tmp_path / "repo"
    shutil.copytree(ROOT / "src", fake_root / "src", ignore=shutil.ignore_patterns("__pycache__"))
    for extra in ("schema", "method"):
        if (ROOT / extra).is_dir():
            shutil.copytree(ROOT / extra, fake_root / extra)
    src_base = ROOT / "data" / "nur" / "al_saadi"
    dst_base = fake_root / "data" / "nur" / "al_saadi"
    for sub in ("raw", "layers", "spans", "windows", "markers", "packets"):
        if (src_base / sub).is_dir():
            shutil.copytree(src_base / sub, dst_base / sub)
    monkeypatch.setattr(config, "REPO_ROOT", fake_root)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOllama)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        add_user("sa@example.com", "super_admin")
        add_user("dr@example.com", "specialist")
        login(env, "sa@example.com")
        port = server.server_address[1]
        env.patch("/api/settings/llm", json={"base_url": f"http://127.0.0.1:{port}"}, headers=H)
        bad = env.post("/api/tasks/preview", json={"kind": "committee", "scope": "sample",
                                                   "tafsirs": ["al_saadi"], "variant": "x"},
                       headers=H)
        assert bad.json()["detail"]["error"] == "variant_unknown"
        r = env.post("/api/tasks", json={"kind": "committee", "scope": "sample",
                                         "tafsirs": ["al_saadi"], "variant": "ab"}, headers=H)
        assert r.status_code == 200, r.text
        tid = r.json()["id"]
        runner.start()
        deadline = time.time() + 120
        while time.time() < deadline:
            t = env.get(f"/api/tasks/{tid}").json()
            if t["task"]["status"] in ("done", "failed"):
                break
            time.sleep(0.5)
        assert t["task"]["status"] == "done", json.dumps(t, ensure_ascii=False)[:2000]
        assert [(s["agent"], s["variant"]) for s in t["steps"]] == [
            ("classifier", ""), ("classifier", "profile"), ("method_specialist", "profile"),
            ("verifier", ""), ("verifier", "profile"), ("chair", ""), ("chair", "profile")]
        # the fake model does not answer as a specialist: an untrusted reply never confirms
        spec = {k: v for k, v in t["steps"][2]["result"].items()
                if k not in ("model_calls", "tokens_in", "tokens_out", "max_prompt")}
        assert spec == {"moves": 1, "confirm": 0, "reject": 0, "reframe": 0, "abstain": 0,
                        "invalid": 1}
        assert t["steps"][2]["result"]["model_calls"] == 2  # one retry after an invalid reply
        assert (dst_base / "specialist_profile" / "24_35.json").is_file()
        assert "ملف المفسر" in t["task"]["title_ar"]
        card = env.get("/api/agents/method_specialist").json()
        assert card["model"] == "qwen2.5:14b" and card["arms_today"] == {"B": 1}
        assert card["outcomes_today"]["invalid"] == 1 and card["today"]["model_calls"] >= 1
        assert env.get("/api/agents/classifier").json()["arms_today"] == {"A": 1, "B": 1}
        # each arm writes its own outputs; arm B packets are rebuilt in the workspace copy
        assert (dst_base / "committee" / "24_35.json").is_file()
        assert (dst_base / "committee_profile" / "24_35.json").is_file()
        assert (dst_base / "verified" / "qwen2_5_14b__profile" / "24_35.json").is_file()
        assert (dst_base / "verified" / "committee__profile" / "24_35.json").is_file()
        assert (dst_base / "packets_profile" / "24_35.json").is_file()
        assert (dst_base / "packets" / "24_35.json").read_bytes() == \
            (src_base / "packets" / "24_35.json").read_bytes()

        # operators see which arm is which
        units = [u for u in env.get("/api/review/units").json()["units"] if u["window"] == "24_35"]
        assert sorted(u["arm"] for u in units) == ["X", "Y"]
        b_arm = next(u["arm"] for u in units if u["variant"] == "profile")
        a_arm = "X" if b_arm == "Y" else "Y"

        # the specialist reviews blind
        env.post("/api/auth/logout", headers=H)
        login(env, "dr@example.com")
        units = [u for u in env.get("/api/review/units").json()["units"] if u["window"] == "24_35"]
        assert all("variant" not in u and "annotator" not in u for u in units)
        rv = env.get(f"/api/review/al_saadi/24_35?arm={b_arm}").json()
        assert rv["arm"] == b_arm and rv["variant"] is None and rv["annotator"] is None
        assert "annotator" not in json.dumps(rv["models"])
        assert "verse_in_report" in rv["error_types"] and "M_SUNNAH" in rv["methods"]
        assert env.get("/api/review/al_saadi/24_35?arm=Z").json()["detail"]["error"] == "bad_arm"

        body = {"tafsir": "al_saadi", "window": "24_35", "move_id": "P-m01", "arm": b_arm,
                "decision": "needs_edit", "teach": True}
        assert env.post("/api/review/decision", json=body, headers=H).json()["detail"][
            "error"] == "note_required"
        body.update(error_type="paraphrase_not_lugha", correct_primary="M_RAY")
        ok = env.post("/api/review/decision", json=body, headers=H).json()
        assert ok["ok"] and ok["teaching_examples"] == 1
        assert env.post("/api/review/decision", json={**body, "error_type": "nope"},
                        headers=H).json()["detail"]["error"] == "bad_error_type"
        # the lesson is in the bank (references only, no text)
        bank = json.loads((dst_base / "gold" / "examples.json").read_text(encoding="utf-8"))
        ex = bank["examples"][0]
        assert ex["window"] == "24_35" and ex["correct_primary"] == "M_RAY"
        assert ex["error_type"] == "paraphrase_not_lugha" and "text" not in ex
        # a decision on arm A is kept apart from arm B
        env.post("/api/review/decision", json={"tafsir": "al_saadi", "window": "24_35",
                                               "move_id": "P-m01", "arm": a_arm,
                                               "decision": "reject", "note": "x"}, headers=H)
        decided = {u["arm"]: u["decided"] for u in env.get("/api/review/units").json()["units"]
                   if u["window"] == "24_35"}
        assert decided == {"X": 1, "Y": 1}

        learn = env.get("/api/learning").json()
        saadi = next(x for x in learn["tafsirs"] if x["tafsir"] == "al_saadi")
        assert learn["lessons"] == 1 and saadi["bank"]["count"] == 1
        assert saadi["profile"]["version"] and len(saadi["profile"]["golden_rules_ar"]) == 8
        assert "ab" not in saadi and learn["reveals_arms"] is False

        env.post("/api/auth/logout", headers=H)
        db.execute("UPDATE otp_codes SET created_at=created_at-3600")  # past the resend cooldown
        login(env, "sa@example.com")
        learn = env.get("/api/learning").json()
        saadi = next(x for x in learn["tafsirs"] if x["tafsir"] == "al_saadi")
        assert saadi["ab"]["paired_windows"] == ["24_35"]
        assert saadi["ab"]["arms"]["A"]["moves"] == saadi["ab"]["arms"]["B"]["moves"] == 1

        # the next arm B packet carries no example from the same ayah (no leakage)
        pkt = json.loads((dst_base / "packets_profile" / "24_35.json").read_text(encoding="utf-8"))
        assert not pkt.get("teaching_examples")
    finally:
        runner.stop()
        server.shutdown()


def test_ab_steps_and_variant_flags_in_commands(env, monkeypatch):
    from console import pipeline
    monkeypatch.setattr(pipeline, "resolve_scope", lambda scope, ayat, tafsirs: [("al_tabari", "24_2_p01")])
    steps = runner.plan_steps("committee", "ayat", "2", ["al_tabari"], "ab")
    assert [(s["agent"], s["variant"]) for s in steps] == [
        ("classifier", ""), ("classifier", "profile"), ("method_specialist", "profile"),
        ("verifier", ""), ("verifier", "profile"), ("chair", ""), ("chair", "profile")]
    assert steps[2]["model"] == "qwen2.5:14b"            # same model as the classifier
    assert [s["agent"] for s in runner.plan_steps("committee", "ayat", "2", ["al_tabari"])] == [
        "classifier", "verifier", "chair"]               # baseline arm: no specialists
    monkeypatch.setattr(pipeline, "window_ids", lambda tafsir: ["24_2_p01"])
    cmd, _ = runner._step_command({**steps[1]})
    assert cmd[cmd.index("--variant") + 1] == "profile" and "--api" in cmd
    cmd, _ = runner._step_command({**steps[2]})
    assert "src/specialist.py" in cmd and cmd[cmd.index("--classifier") + 1] == "qwen2_5_14b"
    cmd, _ = runner._step_command({**steps[6]})
    assert cmd[-2:] == ["--variant", "profile"] and "src/committee_chair.py" in cmd
    cmd, _ = runner._step_command({**steps[0]})
    assert "--variant" not in cmd
    assert runner._chair_inputs_missing({"tafsir": "al_tabari", "window": "24_99_p99",
                                         "variant": "profile"}) == ["classifier", "verifier"]
    with pytest.raises(runner.TaskError):
        runner._step_command({**steps[0], "variant": "other"})


def test_deploy_sync_keeps_arm_b_outputs_and_lessons():
    script = (ROOT / "deploy" / "server" / "mirqah-deploy").read_text(encoding="utf-8")
    for pat in ("committee_*/", "specialist_*/", "data/**/gold/", "markers_*/", "packets_*/"):
        assert pat in script, pat
    pull = (ROOT / "deploy" / "mac" / "pull-runs.sh").read_text(encoding="utf-8")
    assert "committee_profile" in pull and "gold" in pull


def test_hover_card_helpers(env):
    import os

    from console import pipeline
    # Ollama times carry nanoseconds; year 1 and far-future mean "kept loaded"
    assert pipeline._epoch("2026-10-05T14:38:31.837534123+03:00") == pytest.approx(1791200311.837534)
    assert pipeline._epoch("0001-01-01T00:00:00Z") is None
    assert pipeline._epoch("garbage") is None and pipeline._epoch(None) is None
    # the running step's process: resident memory and average CPU from /proc
    if os.path.exists(f"/proc/{os.getpid()}/status"):
        u = runner._proc_usage(os.getpid(), db.now() - 10)
        assert u["rss_mb"] > 1 and u["cpu_pct"] >= 0
    assert runner._proc_usage(None, None) is None
    assert runner._proc_usage(2 ** 22 + 7, None) is None  # gone
    m = runner._USAGE_RE.search("x\nusage: calls=3 prompt_tokens=9000 completion_tokens=410"
                                " max_prompt=3100\n")
    assert [int(x) for x in m.groups()] == [3, 9000, 410, 3100]
    # an unknown agent and an empty day
    with pytest.raises(runner.TaskError):
        runner.agent_detail("robot")
    d = runner.agent_detail("verifier")
    assert d["today"]["n"] == 0 and d["today"]["fail_pct"] is None and d["spark"] == []
