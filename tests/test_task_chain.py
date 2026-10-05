"""Retries belong to their original task: one chain, one combined result, and a
retry runs only what is still open in the whole chain."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from console import auth, config, db, runner  # noqa: E402
from console.app import create_app  # noqa: E402

H = {"X-Mirqah": "1"}
AGENTS = ("classifier", "method_specialist", "chair")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VAR_DIR", tmp_path / "var")
    monkeypatch.setattr(config, "REPO_ROOT", ROOT)
    auth.reset_rate_limits()
    client = TestClient(create_app(start_worker=False))
    yield client
    runner.stop()


def admin(client: TestClient) -> dict:
    rid = db.scalar("SELECT id FROM roles WHERE key='super_admin'")
    uid = db.execute("INSERT INTO users(email,name,role_id,lang,active,created_at) VALUES"
                     " ('sa@example.com','SA',?,'',1,?)", (rid, db.now()))
    code = client.post("/api/auth/request-otp", json={"email": "sa@example.com"},
                       headers=H).json()["mock_code"]
    assert client.post("/api/auth/verify-otp", json={"email": "sa@example.com", "code": code},
                       headers=H).status_code == 200
    return {"id": uid, "permissions": ["run_tasks"]}


def make_task(steps: list[tuple[str, str, str]], status: str, *, retry_of: int | None = None,
              legacy: bool = False, title: str = "t") -> int:
    """steps: (agent, window, status). legacy=True writes the link only in params, like
    the releases before task chains."""
    params = {"kind": "committee", "variant": "profile", "skip_done": False}
    if retry_of:
        params["retry_of"] = retry_of
    counts = {k: sum(1 for s in steps if s[2] == k) for k in ("done", "failed", "skipped")}
    tid = db.execute(
        "INSERT INTO tasks(kind,title_ar,params,status,created_at,total_steps,done_steps,"
        "failed_steps,skipped_steps) VALUES ('committee',?,?,?,?,?,?,?,?)",
        (title, db.dumps(params), status, db.now(), len(steps), counts["done"], counts["failed"],
         counts["skipped"]))
    if retry_of and not legacy:
        origin = db.scalar("SELECT COALESCE(origin_id, id) FROM tasks WHERE id=?", (retry_of,))
        db.execute("UPDATE tasks SET retry_of=?, origin_id=? WHERE id=?", (retry_of, origin, tid))
    for i, (agent, window, st) in enumerate(steps):
        result = db.dumps({"reason": "agent_missing", "missing": ["classifier"]}) \
            if st == "skipped" else None
        tail = "timed out: no model reply within 585 s" if st == "failed" else ""
        db.execute("INSERT INTO task_steps(task_id,seq,agent,tafsir,window,model,status,variant,"
                   "result,output_tail,exit_code) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (tid, i, agent, "ibn_kathir", window, "qwen2.5:14b", st, "profile", result, tail,
                    1 if st == "failed" else 0))
    return tid


def ab_like_chain() -> tuple[int, int, int, int]:
    """Like task #5 → #6 → #7 → #8: one window fails, two retries fail, the third works."""
    ok = [(a, "24_11_p01", "done") for a in AGENTS]
    bad = [("classifier", "24_11_p02", "failed"), ("method_specialist", "24_11_p02", "failed"),
           ("chair", "24_11_p02", "skipped")]
    t5 = make_task(ok + bad, "failed", title="A/B")
    t6 = make_task(bad, "failed", retry_of=t5)
    t7 = make_task(bad, "failed", retry_of=t6)
    t8 = make_task([(a, "24_11_p02", "done") for a in AGENTS], "done", retry_of=t7)
    return t5, t6, t7, t8


def test_old_retries_are_linked_to_their_original_on_start(env, tmp_path):
    t5 = make_task([("classifier", "24_11_p02", "failed")], "failed")
    t6 = make_task([("classifier", "24_11_p02", "failed")], "failed", retry_of=t5, legacy=True)
    t7 = make_task([("classifier", "24_11_p02", "done")], "done", retry_of=t6, legacy=True)
    assert db.scalar("SELECT origin_id FROM tasks WHERE id=?", (t7,)) is None
    db.init(config.VAR_DIR / "console.db")  # what a restart after the deploy does
    rows = {r["id"]: r for r in db.rows("SELECT id, retry_of, origin_id FROM tasks")}
    assert rows[t5]["origin_id"] is None
    assert (rows[t6]["retry_of"], rows[t6]["origin_id"]) == (t5, t5)
    assert (rows[t7]["retry_of"], rows[t7]["origin_id"]) == (t6, t5)
    con = sqlite3.connect(config.VAR_DIR / "console.db")
    try:
        assert db.backfill_task_chain(con) == 0  # idempotent
    finally:
        con.close()


def test_list_shows_one_row_per_original_with_the_combined_result(env):
    admin(env)
    other = make_task([("classifier", "24_35", "done")], "done", title="older")
    t5, t6, t7, t8 = ab_like_chain()
    tasks = env.get("/api/tasks").json()["tasks"]
    assert [t["id"] for t in tasks] == [t5, other]  # newest activity first, retries folded
    g = tasks[0]["chain"]
    assert [a["id"] for a in g["attempts"]] == [t5, t6, t7, t8]
    assert [a["n"] for a in g["attempts"]] == [0, 1, 2, 3]
    assert g["attempts"][1]["cause"] == "timeout"
    e = g["effective"]
    assert (e["status"], e["done"], e["failed"], e["total"]) == ("done", 6, 0, 6)
    assert e["recovered"] and e["retries"] == 3
    # the original keeps its own counts (history), the group shows the outcome
    assert tasks[0]["status"] == "failed" and tasks[0]["failed_steps"] == 2
    # mission control uses the same groups
    dash = env.get("/api/dashboard").json()["tasks"]
    assert dash[0]["id"] == t5 and dash[0]["chain"]["effective"]["status"] == "done"


def test_task_page_knows_its_chain_and_where_steps_were_fixed(env):
    admin(env)
    t5, t6, t7, t8 = ab_like_chain()
    d = env.get(f"/api/tasks/{t5}").json()
    ch = d["chain"]
    assert ch["origin_id"] == t5 and ch["position"] == 0
    assert ch["final"]["classifier|ibn_kathir|24_11_p02|profile"] == {"status": "done", "task_id": t8}
    assert ch["final"]["classifier|ibn_kathir|24_11_p01|profile"]["task_id"] == t5
    failed = [s for s in d["steps"] if s["status"] == "failed"]
    assert failed and all(s["cause"] == "timeout" for s in failed)
    d7 = env.get(f"/api/tasks/{t7}").json()
    assert d7["chain"]["position"] == 2 and d7["chain"]["origin_id"] == t5


def test_a_retry_runs_only_what_is_still_open_in_the_whole_chain(env):
    user = admin(env)
    ok = [(a, "24_11_p01", "done") for a in AGENTS]
    t1 = make_task(ok + [("classifier", "24_11_p02", "failed"),
                         ("classifier", "24_11_p03", "failed"),
                         ("chair", "24_11_p03", "skipped")], "failed")
    # retry 1 fixed p02 but not p03
    t2 = make_task([("classifier", "24_11_p02", "done"), ("classifier", "24_11_p03", "failed"),
                    ("chair", "24_11_p03", "skipped")], "failed", retry_of=t1)
    # «Retry» pressed on the ORIGINAL still continues the chain
    r = env.post(f"/api/tasks/{t1}/retry", headers=H)
    assert r.status_code == 200, r.text
    t3 = r.json()["id"]
    row = db.row("SELECT * FROM tasks WHERE id=?", (t3,))
    assert (row["retry_of"], row["origin_id"]) == (t2, t1)
    assert db.loads(row["params"])["attempt"] == 2
    keys = [(s["agent"], s["window"]) for s in
            db.rows("SELECT agent, window FROM task_steps WHERE task_id=? ORDER BY seq", (t3,))]
    assert keys == [("classifier", "24_11_p03"), ("chair", "24_11_p03")]  # not p02 again
    # while it is queued, no second retry of the same chain
    r2 = env.post(f"/api/tasks/{t2}/retry", headers=H)
    assert r2.status_code == 400 and r2.json()["detail"]["error"] == "retry_running"
    # once everything is done there is nothing to retry
    db.execute("UPDATE task_steps SET status='done' WHERE task_id=?", (t3,))
    db.execute("UPDATE tasks SET status='done' WHERE id=?", (t3,))
    with pytest.raises(runner.TaskError, match="nothing_to_retry"):
        runner.retry_failed(t1, user)
    g = runner.task_groups()[0]["chain"]["effective"]
    assert g["status"] == "done" and g["retries"] == 2


def test_method_specialist_is_skipped_not_failed_when_the_classifier_failed(env, monkeypatch):
    tid = make_task([("method_specialist", "24_11_p02", "queued")], "running")
    db.execute("UPDATE task_steps SET status='queued' WHERE task_id=?", (tid,))
    monkeypatch.setattr(runner, "_classifier_missing", lambda step: True)
    task = db.row("SELECT * FROM tasks WHERE id=?", (tid,))
    step = db.row("SELECT * FROM task_steps WHERE task_id=?", (tid,))
    runner._run_step(task, step)
    s = db.row("SELECT * FROM task_steps WHERE id=?", (step["id"],))
    assert s["status"] == "skipped"
    assert db.loads(s["result"]) == {"reason": "agent_missing", "missing": ["classifier"]}
    t = db.row("SELECT failed_steps, skipped_steps FROM tasks WHERE id=?", (tid,))
    assert (t["failed_steps"], t["skipped_steps"]) == (0, 1)
    assert runner._is_open(s)  # «retry failed steps» picks it up again
