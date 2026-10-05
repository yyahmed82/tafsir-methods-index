"""Several roles per user, specialist-only decisions, the chair's assignments,
reminders, the chair report, automatic retries, failure alerts and publishing."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from console import auth, config, db, pipeline, publish, runner, settings, workflow  # noqa: E402
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


def outbox(kind_word: str = "") -> list[dict]:
    return [r for r in db.rows("SELECT * FROM outbox ORDER BY id") if kind_word in r["subject"]]


def fake_units(monkeypatch, windows: list[tuple[str, str, int, list[str] | None]]):
    """Committee review units without files: (tafsir, window, moves, arms)."""
    def units(tafsir=None):
        out = []
        for i, (t, w, n, arms) in enumerate(windows):
            for arm in (arms or [None]):
                out.append({"tafsir": t, "name_ar": config.TAFSIR_NAMES_AR[t], "window": w,
                            "ayah": "24:11", "ayah_number": 11 + i, "moves": n, "committee": True,
                            "arm": arm, "annotator": f"committee{'__profile' if arm == 'Y' else ''}"})
        return out
    monkeypatch.setattr(pipeline, "review_units", units)


# ------------------------------------------------------------------ roles

def test_user_holds_several_roles_and_only_specialists_decide(env):
    sa = add_user("sa@example.com", "super_admin")
    both = add_user("kh@example.com", ["super_admin", "specialist"])
    login(env, "kh@example.com")
    me = env.get("/api/me").json()["user"]
    assert set(me["role_keys"]) == {"super_admin", "specialist"} and me["can_decide"]
    assert me["role"]["key"] == "super_admin"  # primary role by rank
    login(env, "sa@example.com")
    me = env.get("/api/me").json()["user"]
    assert not me["can_decide"] and "review_units" in me["permissions"]
    rows = {u["email"]: u for u in env.get("/api/users").json()["users"]}
    assert {r["key"] for r in rows["kh@example.com"]["roles"]} == {"super_admin", "specialist"}
    roles = {r["key"]: r for r in env.get("/api/roles").json()["roles"]}
    assert roles["specialist"]["users"] == 1 and roles["super_admin"]["users"] == 2
    spec, op = roles["specialist"]["id"], roles["committee_operator"]["id"]
    r = env.post("/api/users", json={"email": "op@example.com", "name": "Op",
                                     "role_ids": [spec, op], "notify": False}, headers=H)
    assert r.status_code == 200
    new = {u["email"]: u for u in env.get("/api/users").json()["users"]}["op@example.com"]
    assert new["role_key"] == "committee_operator" and set(new["role_ids"]) == {spec, op}
    # the last super admin role is protected across several roles
    db.execute("DELETE FROM user_roles WHERE user_id=?", (both,))
    db.execute("UPDATE users SET role_id=? WHERE id=?", (spec, both))
    assert env.patch(f"/api/users/{sa}", json={"role_ids": [spec]},
                     headers=H).json()["detail"]["error"] == "own_role"


def test_cli_adds_roles_without_removing(env, capsys):
    from console.__main__ import main
    assert main(["create-user", "--email", "a@example.com", "--name", "A",
                 "--role", "super_admin"]) == 0
    assert main(["create-user", "--email", "a@example.com", "--name", "A",
                 "--role", "specialist"]) == 0
    out = capsys.readouterr().out
    assert "updated a@example.com → specialist, super_admin" in out
    u = auth.user_by_email("a@example.com")
    assert set(u["role_keys"]) == {"super_admin", "specialist"} and auth.can_decide(u)
    assert main(["create-user", "--email", "b@example.com", "--name", "B",
                 "--role", "specialist,viewer"]) == 0
    assert set(auth.user_by_email("b@example.com")["role_keys"]) == {"specialist", "viewer"}


# ------------------------------------------------------------------ assignment

def test_chair_assigns_whole_windows_to_least_loaded_specialist(env, monkeypatch):
    s1, s2, s3 = (add_user(f"s{i}@example.com", "specialist") for i in (1, 2, 3))
    fake_units(monkeypatch, [("al_tabari", "24_11_p01", 6, ["X", "Y"]),
                             ("ibn_kathir", "24_11_p01", 3, None),
                             ("al_saadi", "24_11", 2, None),
                             ("al_baghawi", "24_11_p01", 1, None)])
    out = workflow.sweep()
    assert out["assigned"] == 4
    amap = workflow.assignments_map()
    # both blind versions of a window are one assignment
    assert len(amap) == 4
    load = {}
    for (t, w), a in amap.items():
        load.setdefault(a["user_id"], 0)
        load[a["user_id"]] += {"24_11_p01": {"al_tabari": 12, "ibn_kathir": 3, "al_baghawi": 1},
                               "24_11": {"al_saadi": 2}}[w][t]
    assert sorted(load.values()) == [3, 3, 12]  # 12 | 3 | 2+1
    # decisions close a window
    t_a = amap[("al_saadi", "24_11")]
    for m in ("m01", "m02"):
        db.execute("INSERT INTO decisions(tafsir,window,annotator,move_id,decision,user_id,created_at)"
                   " VALUES ('al_saadi','24_11','committee',?,'approve',?,?)", (m, t_a["user_id"],
                                                                                db.now()))
    assert workflow.sweep()["closed"] == 1
    assert workflow.assignment("al_saadi", "24_11")["status"] == "done"
    # a specialist who loses the role hands the work on
    victim = amap[("ibn_kathir", "24_11_p01")]["user_id"]
    db.execute("DELETE FROM user_roles WHERE user_id=?", (victim,))
    db.execute("UPDATE users SET role_id=(SELECT id FROM roles WHERE key='viewer') WHERE id=?",
               (victim,))
    workflow.sweep()
    assert workflow.assignment("ibn_kathir", "24_11_p01")["user_id"] != victim
    assert {s1, s2, s3}


def test_assignee_only_decides_and_operator_reassigns(env, monkeypatch):
    s1 = add_user("s1@example.com", "specialist", "Dr One")
    s2 = add_user("s2@example.com", "specialist", "Dr Two")
    add_user("op@example.com", "committee_operator")
    fake_units(monkeypatch, [("al_saadi", "24_35", 1, None)])
    db.execute("INSERT INTO assignments(tafsir,window,user_id,assigned_at,status) VALUES"
               " ('al_saadi','24_35',?,?,'open')", (s1, db.now()))
    login(env, "s2@example.com")
    body = {"tafsir": "al_saadi", "window": "24_35", "move_id": "m01", "decision": "approve",
            "compared_with_source": True}
    err = env.post("/api/review/decision", json=body, headers=H).json()["detail"]
    assert err == {"error": "assigned_to_other", "name": "Dr One"}
    mine = env.get("/api/review/assignments?mine=true").json()
    assert mine["assignments"] == [] and mine["can_decide"]
    assert env.post("/api/review/assign", json={"tafsir": "al_saadi", "window": "24_35",
                                                "user_id": s2}, headers=H).status_code == 403
    login(env, "op@example.com")
    assert env.post("/api/review/assign", json={"tafsir": "al_saadi", "window": "24_35",
                                                "user_id": 999}, headers=H).json()["detail"][
        "error"] == "not_a_specialist"
    r = env.post("/api/review/assign", json={"tafsir": "al_saadi", "window": "24_35",
                                             "user_id": s2}, headers=H).json()
    assert r["assignment"]["user_id"] == s2 and r["assignment"]["assigned_by"]
    team = {p["name"]: p for p in env.get("/api/review/assignments").json()["team"]}
    assert team["Dr Two"]["open_windows"] == 1 and team["Dr One"]["open_windows"] == 0


def test_morning_reminders_once_a_day_until_decided(env, monkeypatch):
    s1 = add_user("s1@example.com", "specialist", "Dr One")
    add_user("s2@example.com", "specialist", "Dr Two")
    fake_units(monkeypatch, [("al_tabari", "24_11_p02", 4, ["X", "Y"]),
                             ("al_saadi", "24_11", 2, None)])
    workflow.sweep()
    settings.update("workflow", {"reminder_time": "00:00"}, None)
    did = runner.scheduler_tick({"swept": 9e18})
    assert did["reminders"] == {"sent": 2, "failed": 0}
    mails = outbox("بانتظار قرارك")
    assert len(mails) == 2 and any("حركة في 1 نافذة" in m["subject"] for m in mails)
    assert "reminders" not in runner.scheduler_tick({"swept": 9e18})  # once a day
    assert workflow.assignment("al_saadi", "24_11")["last_reminder_at"]
    assert s1


# ------------------------------------------------------------------ chair report

def test_chair_report_has_people_and_suggestions(env, monkeypatch):
    add_user("s1@example.com", "specialist", "Dr One")
    add_user("op@example.com", "committee_operator")
    add_user("sa@example.com", "super_admin")
    fake_units(monkeypatch, [("al_tabari", "24_11_p02", 14, None)])
    workflow.sweep()
    db.execute("UPDATE assignments SET assigned_at=?", (db.now() - 3 * 86400,))
    day = runner.local_now().date().isoformat()
    c = runner.save_report(day, None)
    ch = c["chair"]
    assert ch["specialists"][0]["open_moves"] == 14 and ch["open_windows"] == 1
    joined = " ".join(ch["suggestions_ar"])
    assert "عدد المتخصصين 1 من 3" in joined and "Dr One" in joined
    assert "## مقترحات رئيس اللجنة" in runner.report_markdown(c)
    res = runner.mail_report(day, None)
    assert res == {"sent": 2, "failed": 0}  # operators + super admins, not specialists
    html = db.row("SELECT html FROM outbox ORDER BY id DESC LIMIT 1")["html"]
    assert "مقترحات رئيس اللجنة" in html


# ------------------------------------------------------------------ retries and alerts

def _task_with_step(agent: str = "classifier", **cols) -> tuple[dict, dict]:
    tid = db.execute("INSERT INTO tasks(kind,title_ar,params,status,created_at,total_steps)"
                     " VALUES ('committee','t','{}','running',?,1)", (db.now(),))
    sid = db.execute("INSERT INTO task_steps(task_id,seq,agent,tafsir,window,model,status)"
                     " VALUES (?,0,?,'al_saadi','24_35','qwen2.5:14b','running')", (tid, agent))
    if cols:
        db.execute(f"UPDATE task_steps SET {', '.join(f'{k}=?' for k in cols)} WHERE id=?",
                   (*cols.values(), sid))
    return (db.row("SELECT * FROM tasks WHERE id=?", (tid,)),
            db.row("SELECT * FROM task_steps WHERE id=?", (sid,)))


def test_failed_step_is_retried_twice_then_final(env):
    task, step = _task_with_step()
    t0 = db.now()
    runner._record_step(task, step, t0, 1, '{"reason_code": "RUN_FAILURE", "error": "HTTP 500"}',
                        {"reason_code": "RUN_FAILURE"})
    s = db.row("SELECT * FROM task_steps WHERE id=?", (step["id"],))
    assert s["status"] == "queued" and s["attempt"] == 2 and s["not_before"] >= t0 + 299
    assert "automatic retry 1/2 in 5 min" in s["last_error"] and s["finished_at"] is None
    assert runner._next_step(task["id"]) [0] is None  # not due yet
    db.execute("UPDATE task_steps SET not_before=? WHERE id=?", (db.now() - 1, step["id"]))
    assert runner._next_step(task["id"])[0]["id"] == step["id"]
    runner._record_step(task, s, t0, 1, "boom", None)
    s = db.row("SELECT * FROM task_steps WHERE id=?", (step["id"],))
    assert s["attempt"] == 3 and s["not_before"] >= db.now() + 29 * 60
    runner._record_step(task, s, t0, 1, "boom", None)
    s = db.row("SELECT * FROM task_steps WHERE id=?", (step["id"],))
    assert s["status"] == "failed"
    assert db.row("SELECT failed_steps FROM tasks WHERE id=?", (task["id"],))["failed_steps"] == 1


def test_restart_and_offline_engine_do_not_use_attempts(env, monkeypatch):
    task, step = _task_with_step()
    runner._record_step(task, step, db.now(), -15, "", None, killed_externally=True)
    s = db.row("SELECT * FROM task_steps WHERE id=?", (step["id"],))
    assert s["status"] == "queued" and s["attempt"] == 1 and s["interruptions"] == 1
    monkeypatch.setattr(runner, "_engine_up", lambda force=False: False)
    runner._record_step(task, s, db.now(), 1, "network error: [Errno 111] Connection refused", None)
    s = db.row("SELECT * FROM task_steps WHERE id=?", (step["id"],))
    assert s["status"] == "queued" and s["attempt"] == 1 and "engine offline" in s["last_error"]
    assert db.meta_get("engine_down_since")
    # a console that died mid-step runs it again on start
    db.execute("UPDATE task_steps SET status='running' WHERE id=?", (step["id"],))
    runner.recover_interrupted()
    s = db.row("SELECT * FROM task_steps WHERE id=?", (step["id"],))
    assert s["status"] == "queued" and s["interruptions"] == 2


def test_dependent_step_waits_for_a_pending_retry(env):
    tid = db.execute("INSERT INTO tasks(kind,title_ar,params,status,created_at,total_steps)"
                     " VALUES ('committee','t','{}','running',?,3)", (db.now(),))
    for seq, agent in enumerate(("classifier", "verifier", "chair")):
        db.execute("INSERT INTO task_steps(task_id,seq,agent,tafsir,window,status,not_before)"
                   " VALUES (?,?,?,'al_saadi','24_35','queued',?)",
                   (tid, seq, agent, db.now() + 300 if agent == "classifier" else None))
    step, wait = runner._next_step(tid)
    assert step["agent"] == "verifier"  # the chair waits for the classifier's retry
    db.execute("UPDATE task_steps SET status='done' WHERE task_id=? AND agent='verifier'", (tid,))
    step, wait = runner._next_step(tid)
    assert step is None and 1 <= wait <= 30


def test_failure_alerts_are_batched_to_operators_and_admins(env):
    add_user("op@example.com", "committee_operator")
    add_user("sa@example.com", "super_admin")
    add_user("s1@example.com", "specialist")
    assert workflow.failure_alerts() is None  # first call only marks where alerts start
    assert db.meta_get("alerts_since")
    db.meta_set("alerts_since", db.now() - 3600)
    for _ in range(3):
        task, step = _task_with_step(attempt=3)
        runner._record_step(task, step, db.now() - 60, 1, "Traceback\nValueError: bad", None)
    db.execute("UPDATE task_steps SET finished_at=finished_at-60")
    out = workflow.failure_alerts()
    assert out == {"steps": 3, "sent": 2, "failed": 0}
    mail = outbox("تنبيه")[-1]
    assert "3 خطوة فشلت" in mail["subject"] and "ValueError: bad" in mail["html"]
    task, step = _task_with_step(attempt=3)
    runner._record_step(task, step, db.now() - 60, 1, "again", None)
    db.execute("UPDATE task_steps SET finished_at=finished_at-60 WHERE id=?", (step["id"],))
    assert workflow.failure_alerts() is None  # within the 10-minute batch window
    assert workflow.failure_alerts(force=True)["steps"] == 1


# ------------------------------------------------------------------ publishing

def _approved_window(tmp_path: Path, monkeypatch, text: str = "قال ابن عباس: هذا مثال.") -> dict:
    root = tmp_path / "repo"
    base = root / "data" / "nur" / "al_saadi"
    (base / "raw").mkdir(parents=True)
    (base / "verified" / "qwen2_5_14b").mkdir(parents=True)
    (base / "windows").mkdir(parents=True)
    raw = (base / "raw" / "24_35.txt")
    raw.write_text(text, encoding="utf-8")
    sha = hashlib.sha256(raw.read_bytes()).hexdigest()
    moves = [{"move_id": "m01", "span_ids": ["s001"], "start": 0, "end": 12, "text": text[:12],
              "primary": "M_ATHAR", "certainty": "explicit", "secondary": []},
             {"move_id": "m02", "span_ids": ["s002"], "start": 12, "end": len(text),
              "text": text[12:], "primary": "M_LUGHA", "certainty": "weak"}]
    (base / "verified" / "qwen2_5_14b" / "24_35.json").write_text(json.dumps(
        {"window_id": "24_35", "ayah": "24:35", "source_file": "data/nur/al_saadi/raw/24_35.txt",
         "source_sha256": sha, "moves": moves}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(config, "REPO_ROOT", root)
    return {"base": base, "raw": raw}


def test_publish_review_versions_rollback_and_public_endpoint(env, tmp_path, monkeypatch):
    w = _approved_window(tmp_path, monkeypatch)
    sa = add_user("sa@example.com", "super_admin")
    spec = add_user("dr@example.com", "specialist", "Dr Khaled")
    for m, d in (("m01", "approve"), ("m02", "approve")):
        db.execute("INSERT INTO decisions(tafsir,window,annotator,move_id,decision,"
                   "compared_with_source,user_id,created_at) VALUES ('al_saadi','24_35',"
                   "'qwen2_5_14b',?,?,1,?,?)", (m, d, spec, db.now()))
    assert env.get("/public/v1/published.json").status_code == 404
    login(env, "dr@example.com")
    assert env.get("/api/publish").status_code == 403  # specialists decide, admins publish
    login(env, "sa@example.com")
    pv = env.get("/api/publish").json()
    assert pv["counts"]["units"] == 2 and len(pv["added"]) == 2 and pv["live"] is None
    assert pv["failed"] == [] and pv["public_url"].endswith("/public/v1/published.json")
    r = env.post("/api/publish", json={"note": "أول نشر"}, headers=H).json()
    assert r["live"]["version"] == 1 and r["live"]["units"] == 2
    pub = env.get("/public/v1/published.json")
    assert pub.status_code == 200 and pub.headers["access-control-allow-origin"] == "*"
    body = pub.json()
    assert body["version"] == 1 and {u["primary"] for u in body["units"]} == {"M_ATHAR", "M_LUGHA"}
    assert "Dr Khaled" not in pub.text and "dr@example.com" not in pub.text
    assert body["units"][0]["text"] == "قال ابن عباس"
    assert env.get("/public/v1/published.json",
                   headers={"If-None-Match": pub.headers["etag"]}).status_code == 304
    assert env.post("/api/publish", json={}, headers=H).json()["detail"]["error"] == \
        "nothing_to_publish"
    # a later rejection removes the unit from the next version
    db.execute("INSERT INTO decisions(tafsir,window,annotator,move_id,decision,note,user_id,"
               "created_at) VALUES ('al_saadi','24_35','qwen2_5_14b','m02','reject','x',?,?)",
               (spec, db.now() + 1))
    pv = env.get("/api/publish").json()
    assert len(pv["removed"]) == 1 and pv["changes"] == 1
    assert env.post("/api/publish", json={}, headers=H).json()["live"]["version"] == 2
    assert env.get("/public/v1/manifest.json").json()["units"] == 1
    # roll back = make an older version live again
    assert env.post("/api/publish/1/live", headers=H).json()["live"]["version"] == 1
    assert env.get("/public/v1/published.json").json()["version"] == 1
    hist = env.get("/api/publish").json()["history"]
    assert [h["version"] for h in hist] == [2, 1] and hist[1]["live"]
    # the source changed under an approved unit: it is held back, with the reason
    w["raw"].write_text("نص آخر تمامًا لا يطابق", encoding="utf-8")
    pv = env.get("/api/publish").json()
    assert pv["counts"]["units"] == 0 and {f["reason"] for f in pv["failed"]} == {"source_changed"}
    assert sa
