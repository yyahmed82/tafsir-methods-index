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
            sent.append(msg.get_content())

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
        else:
            self._json({}, 404)

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        user = data["messages"][-1]["content"]
        wid = re.search(r"window_id: (\S+)", user).group(1)
        ids = re.findall(r"\b(s\d{3})\b", user.split("## مخطط")[0])
        sid = ids[-1] if ids else "s001"
        reply = {"window": wid, "moves": [{
            "move_id": "m01", "span_ids": [sid], "primary": "M_LUGHA", "secondary": [],
            "content_tags": [], "certainty": "weak", "evidence_span_ids": [sid],
            "author_verdict_span_ids": [], "references": {"verses": [], "hadith": [],
                                                           "persons": []},
            "alternatives": [], "rationale_ar": "اختبار"}]}
        self._json({"choices": [{"message": {"content": json.dumps(reply, ensure_ascii=False)}}]})


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

        # specialist decision rules (keyed by committee row, not bare move_id)
        body = {"tafsir": "al_saadi", "window": "24_35", "move_id": "P-m01", "decision": "approve"}
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
