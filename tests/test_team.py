"""Team & agents performance page and the manual «Remind» button."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from console import auth, config, db, pipeline, runner, workflow  # noqa: E402
from console.app import create_app  # noqa: E402

H = {"X-Mirqah": "1"}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VAR_DIR", tmp_path / "var")
    monkeypatch.setattr(config, "REPO_ROOT", ROOT)
    auth.reset_rate_limits()
    client = TestClient(create_app(start_worker=False))
    yield client
    runner.stop()


def add_user(email: str, roles: str | list[str], name: str | None = None) -> int:
    keys = [roles] if isinstance(roles, str) else roles
    rid = [db.scalar("SELECT id FROM roles WHERE key=?", (k,)) for k in keys]
    uid = db.execute("INSERT INTO users(email,name,role_id,lang,active,created_at) VALUES"
                     " (?,?,?,?,1,?)", (email, name or email.split("@")[0], rid[0], "", db.now()))
    for r in rid:
        db.execute("INSERT OR IGNORE INTO user_roles(user_id, role_id) VALUES (?,?)", (uid, r))
    return uid


def login(client: TestClient, email: str) -> None:
    db.execute("UPDATE otp_codes SET created_at=created_at-3600")
    code = client.post("/api/auth/request-otp", json={"email": email}, headers=H).json()["mock_code"]
    assert client.post("/api/auth/verify-otp", json={"email": email, "code": code},
                       headers=H).status_code == 200


def fake_units(monkeypatch, windows):
    def units(tafsir=None):
        return [{"tafsir": t, "name_ar": config.TAFSIR_NAMES_AR[t], "window": w, "ayah": "24:11",
                 "ayah_number": 11 + i, "moves": n, "committee": True, "arm": None,
                 "annotator": "committee"} for i, (t, w, n) in enumerate(windows)]
    monkeypatch.setattr(pipeline, "review_units", units)


def decide(uid: int, n: int, *, window: str = "24_11_p01", decision: str = "approve",
           at: float | None = None, teach: bool = False, annotator: str = "committee") -> None:
    t0 = at or db.now() - 3600
    for i in range(n):
        db.execute("INSERT INTO decisions(tafsir,window,annotator,move_id,decision,compared_with_source,"
                   "note,user_id,created_at,teach) VALUES (?,?,?,?,?,1,'',?,?,?)",
                   ("al_tabari", window, annotator, f"P-m{uid}{i:03d}", decision, uid, t0 + i,
                    db.dumps({"teach": True}) if teach and i == 0 else ""))


def test_managers_see_everyone_specialists_only_themselves(env, monkeypatch):
    fake_units(monkeypatch, [("al_tabari", "24_11_p01", 4)])
    add_user("op@example.com", "committee_operator", "Operator")
    a = add_user("a@example.com", "specialist", "Aisha")
    b = add_user("b@example.com", "specialist", "Bilal")
    add_user("v@example.com", "viewer", "Viewer")
    decide(a, 50, teach=True)
    decide(b, 3, decision="needs_edit", window="24_11_p02")
    login(env, "op@example.com")
    d = env.get("/api/team?days=7").json()
    assert d["scope"] == "all" and {p["name"] for p in d["people"]} == {"Aisha", "Bilal"}
    pa = next(p for p in d["people"] if p["name"] == "Aisha")
    assert (pa["decided"], pa["approve"], pa["lessons"]) == (50, 50, 1)
    assert d["team"]["decided"] == 53 and d["team"]["needs_edit"] == 3
    kinds = [(m["kind"], m.get("who"), m.get("n")) for m in d["milestones"]]
    assert ("first_review", "Aisha", None) in kinds and ("decisions_n", "Aisha", 50) in kinds
    assert ("first_lesson", "Aisha", None) in kinds
    assert sum(x["total"] for x in d["daily"]) == 53 and len(d["daily"]) == 7
    login(env, "a@example.com")
    d = env.get("/api/team").json()
    assert d["scope"] == "self" and [p["name"] for p in d["people"]] == ["Aisha"]
    assert d["team"]["decided"] == 53  # team totals stay visible
    assert sum(x["total"] for x in d["daily"]) == 50  # but the chart is their own work
    login(env, "v@example.com")
    d = env.get("/api/team").json()
    assert d["scope"] == "team" and d["people"] == []


def test_agents_counts_retries_and_causes(env):
    add_user("sa@example.com", "super_admin")
    login(env, "sa@example.com")
    tid = db.execute("INSERT INTO tasks(kind,title_ar,params,status,created_at,total_steps)"
                     " VALUES ('committee','t','{}','done',?,3)", (db.now(),))
    now = db.now() - 600
    for seq, (agent, st, attempt, tail) in enumerate([
            ("classifier", "done", 2, "usage: calls=1 prompt_tokens=8000 completion_tokens=900 max_prompt=8000"),
            ("classifier", "failed", 3, "timed out: no model reply within 585 s"),
            ("verifier", "done", 1, "")]):
        db.execute("INSERT INTO task_steps(task_id,seq,agent,tafsir,window,model,status,attempt,"
                   "duration_ms,finished_at,output_tail,result) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (tid, seq, agent, "al_tabari", f"24_1_p0{seq}", "qwen2.5:14b", st, attempt,
                    120000, now + seq, tail,
                    db.dumps({"model_calls": 1, "tokens_in": 8000, "tokens_out": 900})
                    if st == "done" else None))
    a = env.get("/api/team?days=7").json()["agents"]
    cls = next(r for r in a["table"] if r["agent"] == "classifier")
    assert (cls["ok"], cls["failed"], cls["retried_ok"]) == (1, 1, 1)
    assert cls["causes"] == {"timeout": 1}
    assert a["totals"]["done"] == 2 and a["totals"]["fail_pct"] == 33
    assert a["totals"]["tokens_in"] == 16000
    assert sum(x["by_agent"]["classifier"] for x in a["daily"]) == 1


def test_routing_shows_versions_only_to_those_who_may_see_them(env, monkeypatch):
    add_user("op@example.com", ["committee_operator"], "Operator")
    s = add_user("s@example.com", ["super_admin", "specialist"], "Sara")
    decide(s, 2, window="24_11_p01")
    decide(s, 1, window="24_11_p02", decision="reject", annotator="committee__profile")
    routes = {("24_11_p01", "committee"): {f"P-m{s}000": "auto_candidate", f"P-m{s}001": "specialist"},
              ("24_11_p02", "committee__profile"): {f"P-m{s}000": "specialist"}}
    monkeypatch.setattr(pipeline, "move_routes", lambda t, w, ann: routes.get((w, ann), {}))
    login(env, "op@example.com")
    r = env.get("/api/team").json()["routing"]
    assert r["suggested"]["approve"] == 1 and r["referred"]["approve"] == 1
    assert r["referred"]["reject"] == 1
    assert r["arms"]["profile"]["reject"] == 1 and r["arms"]["baseline"]["approve"] == 2
    login(env, "s@example.com")  # holds the Specialist role: reviews blind
    assert "arms" not in env.get("/api/team").json()["routing"]


def test_remind_one_specialist_with_a_cooldown(env, monkeypatch):
    fake_units(monkeypatch, [("al_tabari", "24_11_p01", 4), ("ibn_kathir", "24_11_p01", 2)])
    add_user("op@example.com", "committee_operator", "Operator")
    a = add_user("a@example.com", "specialist", "Aisha")
    b = add_user("b@example.com", "specialist", "Bilal")
    db.execute("INSERT INTO assignments(tafsir,window,user_id,assigned_at,status) VALUES"
               " ('al_tabari','24_11_p01',?,?,'open')", (a, db.now() - 3 * 86400))
    login(env, "op@example.com")
    r = env.post(f"/api/team/remind/{a}", headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["windows"] == 1
    mails = db.rows("SELECT * FROM outbox WHERE to_addr='a@example.com'")
    assert len(mails) == 1
    again = env.post(f"/api/team/remind/{a}", headers=H)
    assert again.status_code == 429 and again.json()["detail"]["error"] == "remind_cooldown"
    none = env.post(f"/api/team/remind/{b}", headers=H)
    assert none.status_code == 400 and none.json()["detail"]["error"] == "nothing_open"
    p = next(x for x in env.get("/api/team").json()["people"] if x["id"] == a)
    assert p["last_reminder_at"] and p["remind_after"]
    assert 71.9 < p["oldest_h"] < 72.1  # assigned three days ago, still open
    # the 09:00 batch does not e-mail the same person again within the hour
    assert workflow.send_reminders()["sent"] == 0
    # specialists cannot press it
    login(env, "a@example.com")
    assert env.post(f"/api/team/remind/{a}", headers=H).status_code == 403


def test_milestones_desk_cleared_and_published(env, monkeypatch):
    fake_units(monkeypatch, [("al_tabari", "24_11_p01", 1)])
    add_user("sa@example.com", "super_admin")
    a = add_user("a@example.com", "specialist", "Aisha")
    t0 = db.now() - 7200
    db.execute("INSERT INTO assignments(tafsir,window,user_id,assigned_at,status,done_at) VALUES"
               " ('al_tabari','24_11_p01',?,?,'done',?)", (a, t0, t0 + 1800))
    db.execute("INSERT INTO publications(version,created_at,units,sha256,path,live) VALUES"
               " (1,?,12,'x','p',1)", (t0 + 3600,))
    login(env, "sa@example.com")
    d = env.get("/api/team").json()
    kinds = {m["kind"] for m in d["milestones"]}
    assert {"desk_cleared", "published"} <= kinds
    p = next(x for x in d["people"] if x["id"] == a)
    assert p["median_clear_h"] == 0.5 and p["windows_cleared"] == 1


def test_page_works_in_demo_mode(env):
    from console import demo
    add_user("sa@example.com", "super_admin")
    demo.seed(months=3)
    login(env, "sa@example.com")
    assert env.post("/api/mode", json={"mode": "demo"}, headers=H).status_code == 200
    d = env.get("/api/team?days=90").json()
    assert d["simulated"] and d["people"] and d["team"]["decided"] > 0
    assert any(x["by_agent"]["classifier"] for x in d["agents"]["daily"])
    assert sum(sum(v.values()) for k, v in d["routing"].items() if k != "arms") > 0
    assert env.post(f"/api/team/remind/{d['people'][0]['id']}", headers=H).status_code in (400, 423)
