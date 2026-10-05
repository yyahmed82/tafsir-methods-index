"""Task queue for the committee agents + daily reports.

One worker thread runs one step at a time (one model in memory at a time, as
the tagging plan requires). A step is one call to the pinned pipeline:

    python src/run_window.py --base data/<root>/<tafsir> --window <id> --api --model <tag>

which writes ``moves/<annotator>/`` and then runs the deterministic verifier
into ``verified/<annotator>/``. The console never writes those files itself.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import re
import subprocess
import threading
import time
from typing import Any

from . import config, db, mailer, mailtpl, pipeline, settings, workflow

log = logging.getLogger("mirqah.console")

KINDS = {
    # method_specialist runs only for the profile arm (arm B), right after the
    # classifier while the same model is still in memory
    "committee": ("classifier", "method_specialist", "verifier", "chair"),
    "classifier": ("classifier",),
    "verifier": ("verifier",),
    "chair": ("chair",),
    "dryrun": ("packet_check",),
}
KIND_TITLES_AR = {
    "committee": "تشغيل اللجنة (المصنّف ثم المدقّق ثم الرئيس)",
    "chair": "رئيس اللجنة على المخرجات الموجودة",
    "classifier": "تشغيل المصنّف",
    "verifier": "تشغيل المدقّق",
    "dryrun": "فحص الحزم دون نموذج",
}
SCOPE_TITLES_AR = {"sample": "العيّنة", "ayat": "آيات", "surah": "السورة كاملة"}
# Which arms a task runs: baseline (arm A), profile (arm B: methodology profiles),
# or ab (both, same windows, reviewed blind as X / Y).
TASK_VARIANTS = {"baseline": ("",), "profile": ("profile",), "ab": ("", "profile")}
VARIANT_TITLES_AR = {"baseline": "", "profile": " · بملف المفسر",
                     "ab": " · مقارنة A/B (الأساس + ملف المفسر)"}

_VERIFIER_RE = re.compile(
    r"verifier: moves=(\d+) auto=(\d+) specialist=(\d+) flags=(\d+)")
_SPEC_RE = re.compile(
    r"specialist: moves=(\d+) confirm=(\d+) reject=(\d+) reframe=(\d+) abstain=(\d+)"
    r" invalid=(\d+)")
_USAGE_RE = re.compile(
    r"usage: calls=(\d+) prompt_tokens=(\d+) completion_tokens=(\d+) max_prompt=(\d+)")
_CHAIR_RE = re.compile(
    r"processed (\d+) window\(s\), (\d+) move\(s\): (\d+) auto_candidate, (\d+) specialist")
_REASON_RE = re.compile(r'"reason_code":\s*"([A-Z_]+)"')
_stop = threading.Event()
_threads: list[threading.Thread] = []
_current: dict[str, Any] = {"proc": None, "step_id": None}


class TaskError(ValueError):
    pass


# ------------------------------------------------------------------ time

def tz():
    name = settings.get("general")["timezone"]
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:  # pragma: no cover
        return dt.timezone(dt.timedelta(hours=3))


def local_now() -> dt.datetime:
    return dt.datetime.now(tz())


def day_bounds(day: str) -> tuple[float, float]:
    d = dt.date.fromisoformat(day)
    start = dt.datetime.combine(d, dt.time(0, 0), tzinfo=tz())
    return start.timestamp(), (start + dt.timedelta(days=1)).timestamp()


# ------------------------------------------------------------------ tasks

def plan_steps(kind: str, scope: str, ayat: str, tafsirs: list[str],
               variant: str = "baseline") -> list[dict]:
    if kind not in KINDS:
        raise TaskError("kind_unknown")
    if variant not in TASK_VARIANTS:
        raise TaskError("variant_unknown")
    try:
        pairs = pipeline.resolve_scope(scope, ayat, tafsirs)
    except ValueError as e:
        raise TaskError(str(e)) from e
    if not pairs:
        raise TaskError("scope_empty")
    m = pipeline.models()
    steps = []
    # Agent by agent, not window by window: every classifier step, then every
    # verifier step, then the chair. A local runtime keeps one model in memory, so
    # alternating models per window reloads a model (tens of seconds) every step.
    # Both arms of an A/B task run back to back per agent (same model in memory).
    for agent in KINDS[kind]:
        model = m["classifier"] if agent == "classifier" else (
            m["verifier"] if agent == "verifier" else None)
        if agent == "method_specialist":
            model = m["classifier"]
        for arm in TASK_VARIANTS[variant]:
            if agent == "method_specialist" and not arm:
                continue  # the baseline arm has no specialists
            for tafsir, window in pairs:
                steps.append({"agent": agent, "tafsir": tafsir, "window": window,
                              "model": model, "variant": arm})
    return steps


def is_bulk(scope: str, steps: list[dict]) -> bool:
    windows = {(s["tafsir"], s["window"]) for s in steps}
    limit = settings.get("gates")["sample_max_windows"]
    return scope != "sample" and len(windows) > limit


def check_gates(kind: str, scope: str, steps: list[dict], user: dict) -> bool:
    """Raise TaskError when a bulk run is not allowed yet; return whether it is bulk."""
    bulk = is_bulk(scope, steps) and kind != "dryrun"
    if bulk:
        gates = settings.get("gates")
        if "run_bulk" not in user["permissions"]:
            raise TaskError("bulk_no_permission")
        if not gates["phase0_merged"]:
            raise TaskError("bulk_gate_phase0")
        if not gates["sample_reviewed"]:
            raise TaskError("bulk_gate_sample")
    return bulk


def create_task(kind: str, scope: str, ayat: str, tafsirs: list[str], skip_done: bool,
                user: dict, variant: str = "baseline") -> int:
    steps = plan_steps(kind, scope, ayat, tafsirs, variant)
    bulk = check_gates(kind, scope, steps, user)
    windows = sorted({(s["tafsir"], s["window"]) for s in steps})
    title = f"{KIND_TITLES_AR[kind]} — {SCOPE_TITLES_AR.get(scope, scope)}"
    if scope == "ayat":
        title += f" ({ayat.strip()})"
    title += f" · {len(windows)} نافذة" + VARIANT_TITLES_AR[variant]
    params = {"kind": kind, "scope": scope, "ayat": ayat, "tafsirs": tafsirs,
              "skip_done": bool(skip_done), "bulk": bulk, "variant": variant,
              "models": {k: v for k, v in pipeline.models().items()}}
    with db.connect() as con:
        cur = con.execute(
            "INSERT INTO tasks(kind,title_ar,params,status,created_by,created_at,total_steps)"
            " VALUES (?,?,?,?,?,?,?)",
            (kind, title, db.dumps(params), "queued", user["id"], db.now(), len(steps)),
        )
        task_id = int(cur.lastrowid)
        con.executemany(
            "INSERT INTO task_steps(task_id,seq,agent,tafsir,window,model,status,variant)"
            " VALUES (?,?,?,?,?,?,'queued',?)",
            [(task_id, i, s["agent"], s["tafsir"], s["window"], s["model"], s["variant"])
             for i, s in enumerate(steps)],
        )
    db.audit("task.create", user_id=user["id"], target=str(task_id),
             detail={"kind": kind, "scope": scope, "ayat": ayat, "steps": len(steps),
                     "bulk": bulk, "variant": variant})
    return task_id


def cancel_task(task_id: int, user: dict) -> None:
    t = db.row("SELECT * FROM tasks WHERE id=?", (task_id,))
    if t is None:
        raise TaskError("task_not_found")
    if t["status"] not in ("queued", "running"):
        raise TaskError("task_not_active")
    db.execute("UPDATE tasks SET cancel_requested=1 WHERE id=?", (task_id,))
    if t["status"] == "queued":
        _finish_task(task_id, "cancelled")
    db.audit("task.cancel", user_id=user["id"], target=str(task_id))


# ------------------------------------------------------------------ retries as one chain
# «Retry failed steps» never starts an unrelated task: every retry is attempt n of the
# original task (origin_id), runs only what is still open in the whole chain, and the
# original shows the combined result (the last outcome of every step).

_ACTIVE = ("queued", "running")


def _step_key(s: dict) -> tuple:
    return (s["agent"], s["tafsir"], s["window"], s.get("variant") or "")


def _is_open(s: dict) -> bool:
    """A step outcome that still needs a run: failed, interrupted, or skipped because
    an earlier agent of the same window had no result."""
    if s["status"] in ("failed", "interrupted"):
        return True
    if s["status"] == "skipped":
        r = s.get("result")
        r = db.loads(r, {}) if isinstance(r, str) else (r or {})
        return (r or {}).get("reason") == "agent_missing"
    return False


def failure_cause(s: dict) -> str | None:
    """Why a step failed, in one word the UI translates (no model output is shown)."""
    if s["status"] not in ("failed", "interrupted"):
        return None
    text = f"{s.get('output_tail') or ''} {s.get('last_error') or ''}"
    if s["status"] == "interrupted" or s.get("exit_code") in (-15, -9, -2):
        return "restart"
    if "repeating itself" in text or "repeated itself" in text:
        return "loop"
    if "timed out" in text:
        return "timeout"
    if workflow.ENGINE_DOWN_RE.search(text):
        return "engine"
    if "No such file" in text or "no verified result" in text:
        return "missing_input"
    return "error"


_HIDDEN = "[مخفي]"
# A full URL: host (or [IPv6]), optional :port, optional path. Used only to hide the engine.
_ENGINE_URL_RE = re.compile(
    r"https?://(?:\[[0-9A-Fa-f:]+\]|[^/\s?#:]+)(?::\d+)?(?:/[^\s\"'<>]*)?",
    re.IGNORECASE)


def redact_engine(value: Any, user: dict | None) -> Any:
    """Hide the model engine's address from anyone who cannot run tasks.

    Judges, guests, viewers and specialists keep the step text, with three
    substitutions: a line that starts with ``base_url:``, the configured engine
    URL itself, and any http(s) URL on that host or that port. Each becomes
    ``[مخفي]``. Operators (``run_tasks``) see the original.
    """
    if "run_tasks" in (user or {}).get("permissions", ()):
        return value
    base = ((settings.get("llm") or {}).get("base_url") or "").strip()
    host, port = _engine_endpoint(base)
    return _redact_value(value, base, host, port)


def _engine_endpoint(url: str) -> tuple[str, str]:
    """(host, port) of an http(s) URL. Port is '' when the URL does not name one."""
    m = re.match(r"https?://(\[[^\]]+\]|[^/:?#]+)", url or "", re.IGNORECASE)
    if not m:
        return "", ""
    rest = url[m.end():]
    pm = re.match(r":(\d+)", rest)
    return m.group(1).strip("[]"), (pm.group(1) if pm else "")


def _redact_text(text: str, base: str, host: str, port: str) -> str:
    pieces: list[str] = []
    for line in text.splitlines(keepends=True):
        nl = ""
        body = line
        if body.endswith("\r\n"):
            body, nl = body[:-2], "\r\n"
        elif body.endswith("\n"):
            body, nl = body[:-1], "\n"
        if body.lstrip().startswith("base_url:"):
            pieces.append(_HIDDEN + nl)
            continue

        def repl(m: re.Match[str], _host: str = host, _port: str = port) -> str:
            uhost, uport = _engine_endpoint(m.group(0))
            if (_port and uport == _port) or (_host and uhost.lower() == _host.lower()):
                return _HIDDEN
            return m.group(0)

        body = _ENGINE_URL_RE.sub(repl, body)
        if base:
            body = body.replace(base, _HIDDEN)
            bare = base.rstrip("/")
            if bare and bare != base:
                body = body.replace(bare, _HIDDEN)
        pieces.append(body + nl)
    return "".join(pieces)


def _redact_value(value: Any, base: str, host: str, port: str) -> Any:
    if isinstance(value, str):
        return _redact_text(value, base, host, port)
    if isinstance(value, dict):
        return {_redact_value(k, base, host, port) if isinstance(k, str) else k:
                _redact_value(v, base, host, port) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(v, base, host, port) for v in value]
    return value


def _chain_rows(origin: int) -> list[dict]:
    return db.rows("SELECT t.*, u.name AS created_by_name FROM tasks t LEFT JOIN users u"
                   " ON u.id=t.created_by WHERE t.id=? OR t.origin_id=? ORDER BY t.id",
                   (origin, origin))


def _final_steps(task_ids: list[int], steps: list[dict] | None = None) -> dict[tuple, dict]:
    """The last outcome of every step across the attempts (later attempts win)."""
    if steps is None:
        if not task_ids:
            return {}
        q = ",".join("?" * len(task_ids))
        steps = db.rows(f"SELECT * FROM task_steps WHERE task_id IN ({q}) ORDER BY task_id, seq",
                        task_ids)
    final: dict[tuple, dict] = {}
    for st in sorted(steps, key=lambda x: (x["task_id"], x["seq"])):
        final[_step_key(st)] = st
    return final


def _attempt(t: dict, n: int, steps: list[dict]) -> dict:
    causes = [c for c in (failure_cause(st) for st in steps if st["task_id"] == t["id"]) if c]
    return {"id": t["id"], "n": n, "status": t["status"], "total_steps": t["total_steps"],
            "done_steps": t["done_steps"], "failed_steps": t["failed_steps"],
            "skipped_steps": t["skipped_steps"], "created_at": t["created_at"],
            "started_at": t.get("started_at"), "finished_at": t.get("finished_at"),
            "created_by_name": t.get("created_by_name"),
            "cause": max(set(causes), key=causes.count) if causes else None}


def chain_summary(chain: list[dict], steps: list[dict] | None = None) -> dict:
    """attempts (original = n 0) and the combined result of the whole chain."""
    ids = [t["id"] for t in chain]
    if steps is None:
        q = ",".join("?" * len(ids))
        steps = db.rows(f"SELECT * FROM task_steps WHERE task_id IN ({q}) ORDER BY task_id, seq",
                        ids)
    origin = chain[0]
    attempts = [_attempt(t, i, steps) for i, t in enumerate(chain)]
    if len(chain) == 1:
        eff = {"status": origin["status"], "done": origin["done_steps"],
               "failed": origin["failed_steps"], "skipped": origin["skipped_steps"],
               "total": origin["total_steps"], "recovered": False, "retries": 0}
        return {"origin_id": origin["id"], "attempts": attempts, "effective": eff}
    final = _final_steps(ids, steps)
    done = sum(1 for st in final.values() if st["status"] == "done")
    failed = sum(1 for st in final.values() if _is_open(st))
    skipped = sum(1 for st in final.values() if st["status"] == "skipped" and not _is_open(st))
    pending = sum(1 for st in final.values() if st["status"] in ("queued", "running", "cancelled"))
    active = [t for t in chain if t["status"] in _ACTIVE]
    if active:
        status = "running" if any(t["status"] == "running" for t in active) else "queued"
    elif failed:
        status = "failed"
    elif pending:
        status = "cancelled"
    else:
        status = "done"
    eff = {"status": status, "done": done, "failed": failed, "skipped": skipped,
           "total": max(origin["total_steps"], len(final)),
           "recovered": status == "done" and any(t["failed_steps"] for t in chain),
           "retries": len(chain) - 1}
    return {"origin_id": origin["id"], "attempts": attempts, "effective": eff}


def task_groups(limit: int = 50) -> list[dict]:
    """Original tasks, newest activity first, each with its retries and combined result."""
    heads = db.rows("SELECT COALESCE(origin_id, id) AS root, MAX(id) AS last FROM tasks"
                    " GROUP BY root ORDER BY last DESC LIMIT ?", (max(1, min(limit, 200)),))
    if not heads:
        return []
    roots = [h["root"] for h in heads]
    q = ",".join("?" * len(roots))
    rows = db.rows(f"SELECT t.*, u.name AS created_by_name FROM tasks t LEFT JOIN users u"
                   f" ON u.id=t.created_by WHERE t.id IN ({q}) OR t.origin_id IN ({q})"
                   f" ORDER BY t.id", roots + roots)
    chains: dict[int, list[dict]] = {r: [] for r in roots}
    for t in rows:
        chains.setdefault(t["origin_id"] or t["id"], []).append(t)
    multi = [t["id"] for r in roots for t in chains.get(r, []) if len(chains.get(r, [])) > 1]
    steps: list[dict] = []
    if multi:
        qm = ",".join("?" * len(multi))
        steps = db.rows(f"SELECT id, task_id, seq, agent, tafsir, window, variant, status, result,"
                        f" exit_code, output_tail, last_error FROM task_steps"
                        f" WHERE task_id IN ({qm}) ORDER BY task_id, seq", multi)
    out = []
    for r in roots:
        chain = chains.get(r) or []
        if not chain or chain[0]["id"] != r:
            continue  # an orphan retry (its original is gone): nothing to group it under
        g = dict(chain[0])
        g["params"] = db.loads(g["params"], {})
        g["chain"] = chain_summary(chain, [s for s in steps if s["task_id"] in
                                           {t["id"] for t in chain}] if len(chain) > 1 else [])
        out.append(g)
    return out


def task_chain(task_id: int) -> dict | None:
    """The chain a task belongs to, plus, for the original's steps, where a later
    attempt finished them (fixed_in)."""
    t = db.row("SELECT id, origin_id FROM tasks WHERE id=?", (task_id,))
    if t is None:
        return None
    chain = _chain_rows(t["origin_id"] or t["id"])
    if not chain:
        return None
    summary = chain_summary(chain)
    summary["position"] = next((a["n"] for a in summary["attempts"] if a["id"] == task_id), 0)
    if len(chain) > 1:
        final = _final_steps([c["id"] for c in chain])
        summary["final"] = {f"{k[0]}|{k[1]}|{k[2]}|{k[3]}": {"status": v["status"],
                                                            "task_id": v["task_id"]}
                            for k, v in final.items()}
    return summary


def retry_failed(task_id: int, user: dict) -> int:
    """Attempt n+1 of the task's chain: only the steps whose last outcome is still open."""
    t = db.row("SELECT * FROM tasks WHERE id=?", (task_id,))
    if t is None:
        raise TaskError("task_not_found")
    origin_id = t["origin_id"] or t["id"]
    chain = _chain_rows(origin_id)
    if any(c["status"] in _ACTIVE for c in chain):
        raise TaskError("retry_running")
    final = _final_steps([c["id"] for c in chain])
    failed = [st for st in final.values() if _is_open(st)]
    if not failed:
        raise TaskError("nothing_to_retry")
    order = {"packet_check": 0, "classifier": 1, "method_specialist": 2, "verifier": 3,
             "chair": 4}
    failed.sort(key=lambda s: (order.get(s["agent"], 9), s["tafsir"], s["window"],
                               s.get("variant") or ""))  # one model at a time
    origin = chain[0]
    parent = chain[-1]["id"]
    n = len(chain)  # the original is attempt 0
    p = db.loads(origin["params"], {})
    p.update({"retry_of": parent, "origin_id": origin_id, "attempt": n})
    with db.connect() as con:
        cur = con.execute(
            "INSERT INTO tasks(kind,title_ar,params,status,created_by,created_at,total_steps,"
            "retry_of,origin_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (origin["kind"], f"إعادة {n} للمهمة #{origin_id}", db.dumps(p), "queued",
             user["id"], db.now(), len(failed), parent, origin_id),
        )
        new_id = int(cur.lastrowid)
        con.executemany(
            "INSERT INTO task_steps(task_id,seq,agent,tafsir,window,model,status,variant)"
            " VALUES (?,?,?,?,?,?,'queued',?)",
            [(new_id, i, s["agent"], s["tafsir"], s["window"], s["model"],
              s.get("variant") or "") for i, s in enumerate(failed)],
        )
    db.audit("task.retry", user_id=user["id"], target=str(new_id),
             detail={"from": parent, "origin": origin_id, "attempt": n, "steps": len(failed)})
    return new_id


def _finish_task(task_id: int, status: str, error: str | None = None) -> None:
    with db.connect() as con:
        con.execute("UPDATE task_steps SET status='cancelled' WHERE task_id=? AND status='queued'",
                    (task_id,))
        con.execute("UPDATE tasks SET status=?, finished_at=?, error=? WHERE id=?",
                    (status, db.now(), error, task_id))


def _step_command(step: dict) -> tuple[list[str], dict[str, str]]:
    llm = settings.get("llm")
    root = settings.get("general")["data_root"]
    if step["tafsir"] not in config.TAFSIRS or not pipeline.WINDOW_RE.match(step["window"]):
        raise TaskError("bad_step")
    if step["window"] not in pipeline.window_ids(step["tafsir"]):
        raise TaskError("window_missing")
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    variant = step.get("variant") or ""
    if variant and variant not in pipeline.VARIANTS:
        raise TaskError("bad_step")
    arm = ["--variant", variant] if variant else []
    if step["agent"] == "chair":
        m = pipeline.models()
        cmd = [llm["python_bin"], "src/committee_chair.py", "--base", f"{root}/{step['tafsir']}",
               "--proposer", m["classifier_slug"], "--reviewer", m["verifier_slug"],
               "--window", step["window"], "--proposer-tag", m["classifier"],
               "--reviewer-tag", m["verifier"]] + arm
        return cmd, env
    if step["agent"] == "method_specialist":
        if not variant:
            raise TaskError("bad_step")
        base = llm["base_url"].rstrip("/")
        cmd = [llm["python_bin"], "src/specialist.py", "--tafsir", step["tafsir"],
               "--base", f"{root}/{step['tafsir']}", "--window", step["window"],
               "--classifier", pipeline.models()["classifier_slug"], "--model", step["model"],
               "--base-url", base if llm["runtime"] == "hosted" else f"{base}/v1"] + arm
        if llm["runtime"] == "ollama-local":
            env["LLM_API_KEY"] = env.get("LLM_API_KEY") or "ollama"
        env["LLM_TIMEOUT_S"] = str(max(30, int(llm["step_timeout_s"]) - 15))
        return cmd, env
    cmd = [llm["python_bin"], "src/run_window.py", "--tafsir", step["tafsir"],
           "--base", f"{root}/{step['tafsir']}", "--window", step["window"]] + arm
    if step["agent"] == "packet_check":
        cmd.append("--dry-run")
    else:
        base = llm["base_url"].rstrip("/")
        api_base = base if llm["runtime"] == "hosted" else f"{base}/v1"
        cmd += ["--api", "--model", step["model"], "--base-url", api_base]
        # Ollama ignores the key value but the adapter requires a non-empty one.
        # A hosted key must already be in the server's environment; never stored here.
        if llm["runtime"] == "ollama-local":
            env["LLM_API_KEY"] = env.get("LLM_API_KEY") or "ollama"
        # one model reply may take most of the step (model load + generation)
        env["LLM_TIMEOUT_S"] = str(max(30, int(llm["step_timeout_s"]) - 15))
    return cmd, env


def _chair_inputs_missing(step: dict) -> list[str]:
    """Agents whose verified output the chair needs but that is not there yet."""
    m = pipeline.models()
    variant = step.get("variant") or None
    missing = []
    for agent, slug in (("classifier", m["classifier_slug"]), ("verifier", m["verifier_slug"])):
        slug = pipeline.variant_annotator(slug, variant)
        if not pipeline.verified_path(step["tafsir"], slug, step["window"]).is_file():
            missing.append(agent)
    return missing


def _classifier_missing(step: dict) -> bool:
    slug = pipeline.variant_annotator(pipeline.models()["classifier_slug"],
                                      step.get("variant") or None)
    return not pipeline.verified_path(step["tafsir"], slug, step["window"]).is_file()


def _run_step(task: dict, step: dict) -> None:
    params = db.loads(task["params"], {})
    started = db.now()
    db.execute("UPDATE task_steps SET status='running', started_at=? WHERE id=?",
               (started, step["id"]))
    if params.get("skip_done") and step["agent"] in ("classifier", "method_specialist",
                                                     "verifier", "chair"):
        variant = step.get("variant") or None
        if step["agent"] == "chair":
            done = pipeline.committee_is_current(step["tafsir"], step["window"], variant)
        elif step["agent"] == "method_specialist":
            done = pipeline.specialist_is_current(step["tafsir"], step["window"], variant)
        else:
            slug = pipeline.variant_annotator(pipeline.model_slug(step["model"]), variant)
            done = pipeline.verified_path(step["tafsir"], slug, step["window"]).is_file()
        if done:
            db.execute("UPDATE task_steps SET status='skipped', finished_at=?, duration_ms=0,"
                       " result=? WHERE id=?",
                       (db.now(), db.dumps({"reason": "already_verified"}), step["id"]))
            db.execute("UPDATE tasks SET skipped_steps=skipped_steps+1 WHERE id=?", (task["id"],))
            return
    if step["agent"] == "method_specialist" and _classifier_missing(step):
        # the classifier of this window and arm failed: nothing to review, so this is
        # not a second failure; «retry failed steps» runs it again after the classifier
        _record_step(task, step, started, 0, "skipped: no verified result yet from classifier",
                     {"reason": "agent_missing", "missing": ["classifier"]}, status="skipped")
        return
    if step["agent"] == "chair":
        missing = _chair_inputs_missing(step)
        if missing:
            # Not a chair failure: the chair has nothing to compare yet. Shown as
            # "skipped: no verifier result"; «retry failed steps» re-runs it.
            _record_step(task, step, started, 0,
                         "skipped: no verified result yet from " + " and ".join(missing),
                         {"reason": "agent_missing", "missing": missing}, status="skipped")
            return
    try:
        cmd, env = _step_command(step)
    except TaskError as e:
        _record_step(task, step, started, 2, f"refused: {e}", None)
        return
    timeout = settings.get("llm")["step_timeout_s"]
    try:
        proc = subprocess.Popen(cmd, cwd=config.work_root(), env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                errors="replace")
    except OSError as e:
        _record_step(task, step, started, 127, f"{type(e).__name__}: {e}", None)
        return
    _current.update(proc=proc, step_id=step["id"])
    output = ""
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                output, _ = proc.communicate(timeout=1)
                break
            except subprocess.TimeoutExpired:
                cancelled = db.scalar("SELECT cancel_requested FROM tasks WHERE id=?",
                                      (task["id"],))
                if cancelled or _stop.is_set() or time.monotonic() > deadline:
                    proc.kill()
                    output, _ = proc.communicate()
                    reason = ("timeout" if time.monotonic() > deadline else
                              "cancelled" if cancelled else "stopped")
                    output = (output or "") + f"\n[console] step {reason}"
                    if reason == "cancelled":
                        _record_step(task, step, started, -9, output, None, status="cancelled")
                    else:  # a console stop re-queues the step; a timeout may be retried
                        _record_step(task, step, started, -9, output, None,
                                     killed_externally=reason == "stopped")
                    return
    finally:
        _current.update(proc=None, step_id=None)
    result = None
    m = _VERIFIER_RE.search(output or "")
    cm = _CHAIR_RE.search(output or "")
    sm = _SPEC_RE.search(output or "")
    if sm and step["agent"] == "method_specialist":
        result = dict(zip(("moves", "confirm", "reject", "reframe", "abstain", "invalid"),
                          (int(x) for x in sm.groups())))
    elif m:
        result = {"moves": int(m.group(1)), "auto_candidate": int(m.group(2)),
                  "specialist": int(m.group(3)), "flags": int(m.group(4))}
    elif cm and step["agent"] == "chair":
        result = {"moves": int(cm.group(2)), "auto_candidate": int(cm.group(3)),
                  "specialist": int(cm.group(4))}
        com = pipeline.load_committee(step["tafsir"], step["window"], step.get("variant") or None)
        if com:
            result["reasons"] = (com.get("summary") or {}).get("by_abstention_reason")
    elif proc.returncode != 0:
        rc = _REASON_RE.search(output or "")
        if rc:
            result = {"reason_code": rc.group(1)}
    elif step["agent"] == "packet_check" and proc.returncode == 0:
        sm = re.search(r"spans: (\d+)", output or "")
        result = {"spans": int(sm.group(1)) if sm else None}
    um = _USAGE_RE.search(output or "")
    if um:  # tokens the model server reported for this step
        result = dict(result or {})
        result.update(zip(("model_calls", "tokens_in", "tokens_out", "max_prompt"),
                          (int(x) for x in um.groups())))
    # SIGTERM/SIGKILL from outside (systemd stopping the console): not the step's fault
    killed = proc.returncode in (-15, -9, -2)  # our own kills (timeout, cancel) return above
    _record_step(task, step, started, proc.returncode, output, result, killed_externally=killed)
    if step["agent"] == "chair" and proc.returncode == 0:
        try:  # the chair hands the window to a specialist straight away
            workflow.sweep(only=(step["tafsir"], step["window"]))
        except Exception:  # pragma: no cover - assignment never fails a step
            log.exception("assignment after chair step %s", step["id"])


_ENGINE: dict[str, Any] = {"at": 0.0, "up": True}


def _engine_up(force: bool = False) -> bool:
    """Is the local model server reachable? (cached 20 s; hosted runtimes count as up)."""
    if settings.get("llm")["runtime"] != "ollama-local":
        return True
    if force or time.time() - _ENGINE["at"] > 20:
        _ENGINE.update(at=time.time(), up=bool(pipeline.probe_llm().get("reachable")))
    return _ENGINE["up"]


def _record_step(task: dict, step: dict, started: float, code: int, output: str,
                 result: dict | None, status: str | None = None,
                 killed_externally: bool = False) -> None:
    status = status or ("done" if code == 0 else "failed")
    tail = "\n".join((output or "").strip().splitlines()[-25:])[-4000:]
    fin = db.now()
    if status == "failed":
        engine_up = None
        if step["agent"] in workflow.MODEL_AGENTS and workflow.ENGINE_DOWN_RE.search(output or ""):
            engine_up = _engine_up(force=True)
        plan = workflow.plan_failure(step, code, output, killed_externally=killed_externally,
                                     engine_up=engine_up)
        if plan["action"] != "final":
            last = next((ln for ln in reversed(tail.splitlines())
                         if ln.strip() and not _USAGE_RE.match(ln.strip())), "")
            db.execute(
                "UPDATE task_steps SET status='queued', started_at=NULL, finished_at=NULL,"
                " duration_ms=?, exit_code=?, result=?, output_tail=?, attempt=?, not_before=?,"
                " last_error=?, interruptions=interruptions+? WHERE id=?",
                (int((fin - started) * 1000), code,
                 db.dumps(result) if result is not None else None, tail, plan["attempt"],
                 plan["not_before"], f"{plan['reason']} — {last[:200]}",
                 1 if plan["action"] == "requeue" else 0, step["id"]))
            if plan["action"] == "wait" and not db.meta_get("engine_down_since"):
                db.meta_set("engine_down_since", fin)
            log.info("step %s %s: %s", step["id"], plan["action"], plan["reason"])
            return
    db.execute(
        "UPDATE task_steps SET status=?, finished_at=?, duration_ms=?, exit_code=?, result=?,"
        " output_tail=? WHERE id=?",
        (status, fin, int((fin - started) * 1000), code,
         db.dumps(result) if result is not None else None, tail, step["id"]),
    )
    col = {"done": "done_steps", "failed": "failed_steps", "skipped": "skipped_steps"}.get(status)
    if col:
        db.execute(f"UPDATE tasks SET {col}={col}+1 WHERE id=?", (task["id"],))


def _worker() -> None:
    while not _stop.is_set():
        task = db.row("SELECT * FROM tasks WHERE status IN ('running','queued')"
                      " ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, id LIMIT 1")
        if task is None:
            _stop.wait(1.0)
            continue
        if task["status"] == "queued":
            db.execute("UPDATE tasks SET status='running', started_at=? WHERE id=?",
                       (db.now(), task["id"]))
        step, wait_s = _next_step(task["id"])
        cancelled = db.scalar("SELECT cancel_requested FROM tasks WHERE id=?", (task["id"],))
        if cancelled:
            _finish_task(task["id"], "cancelled")
            continue
        if step is None:
            if wait_s:  # a retry or the model engine is not due yet
                _stop.wait(wait_s)
                continue
            t = db.row("SELECT * FROM tasks WHERE id=?", (task["id"],))
            _finish_task(task["id"], "failed" if t["failed_steps"] else "done")
            continue
        if step["agent"] in workflow.MODEL_AGENTS and not _engine_up():
            # the Mac is asleep or offline: wait for it without using up an attempt
            db.execute("UPDATE task_steps SET not_before=?, last_error=? WHERE id=?",
                       (db.now() + 60, "model engine offline — waiting", step["id"]))
            if not db.meta_get("engine_down_since"):
                db.meta_set("engine_down_since", db.now())
            continue
        if step["agent"] in workflow.MODEL_AGENTS and db.meta_get("engine_down_since"):
            db.meta_set("engine_down_since", None)
        try:
            _run_step(task, step)
        except Exception as e:  # keep the worker alive; record the failure honestly
            log.exception("step %s crashed", step["id"])
            _record_step(task, step, db.now(), 1, f"console error: {type(e).__name__}: {e}", None)


# a step waits for these agents of the same window and arm (retries may reorder steps)
PREREQ = {"method_specialist": ("classifier",),
          "chair": ("classifier", "method_specialist", "verifier")}


def _next_step(task_id: int) -> tuple[dict | None, float]:
    """The next due step of a task, or (None, seconds to wait) while retries are pending."""
    now = db.now()
    queued = db.rows("SELECT * FROM task_steps WHERE task_id=? AND status='queued' ORDER BY seq",
                     (task_id,))
    if not queued:
        return None, 0.0
    for s in queued:
        if s.get("not_before") and s["not_before"] > now:
            continue
        need = PREREQ.get(s["agent"], ())
        if any(q["id"] != s["id"] and q["agent"] in need and q["seq"] < s["seq"]
               and q["tafsir"] == s["tafsir"] and q["window"] == s["window"]
               and (q.get("variant") or "") == (s.get("variant") or "") for q in queued):
            continue
        return s, 0.0
    soonest = min((s["not_before"] for s in queued if s.get("not_before")), default=now + 5)
    return None, max(1.0, min(30.0, soonest - now))


def recover_interrupted() -> None:
    """Called on start: steps that were running when the server stopped run again
    (a restart is not the step's fault); after three restarts in a row they fail."""
    with db.connect() as con:
        con.execute("UPDATE task_steps SET status='queued', started_at=NULL, not_before=NULL,"
                    " interruptions=interruptions+1, last_error='interrupted by a console restart'"
                    " WHERE status='running' AND interruptions < 3")
        con.execute("UPDATE task_steps SET status='interrupted', finished_at=?"
                    " WHERE status='running'", (db.now(),))
        con.execute("UPDATE tasks SET failed_steps=(SELECT COUNT(*) FROM task_steps s"
                    " WHERE s.task_id=tasks.id AND s.status IN ('failed','interrupted'))"
                    " WHERE status='running'")


# ------------------------------------------------------------------ agents

AGENTS = [
    {"key": "classifier", "name_ar": "المصنّف", "color": "blue",
     "desc_ar": "يقترح المنهج والدور واليقين وحدود الشاهد بمعرّفات الأجزاء فقط."},
    {"key": "method_specialist", "name_ar": "أخصائيو المنهج", "color": "teal",
     "desc_ar": "الذراع B فقط: ستة أخصائيين بسياق صارم يراجعون حركات المصنّف؛ يمنعون ولا يعتمدون."},
    {"key": "verifier", "name_ar": "المدقّق", "color": "violet",
     "desc_ar": "نموذج من عائلة مختلفة يعيد التصنيف دون أن يرى وسوم المصنّف."},
    {"key": "checker", "name_ar": "الفاحص الحتمي", "color": "green",
     "desc_ar": "برنامج بلا ذكاء: يعيد بناء النص حرفاً بحرف ويرفض المعرّفات المجهولة."},
    {"key": "chair", "name_ar": "رئيس اللجنة", "color": "amber",
     "desc_ar": "src/committee_chair.py: يحسب التوافق (عتبة ٨٥): مرشّح للمراجعة أو امتناع برمز سبب."},
    {"key": "specialist", "name_ar": "المتخصص البشري", "color": "red",
     "desc_ar": "صاحب القرار: يعتمد أو يطلب تعديلاً أو يرفض. لا اعتماد آلي."},
]


def agents_state() -> dict:
    m = pipeline.models()
    day = local_now().date().isoformat()
    start, end = day_bounds(day)
    running = db.row("SELECT s.*, t.title_ar FROM task_steps s JOIN tasks t ON t.id=s.task_id"
                     " WHERE s.status='running' LIMIT 1")
    queued = db.scalar("SELECT COUNT(*) FROM task_steps WHERE status='queued'") or 0
    out = []
    for a in AGENTS:
        key = a["key"]
        info: dict[str, Any] = dict(a)
        if key in ("classifier", "verifier", "chair", "method_specialist"):
            if key == "chair":
                info["model"] = f"{m['classifier']} + {m['verifier']}"
            elif key == "method_specialist":
                info["model"] = m["classifier"]
            else:
                info["model"] = m[key]
                info["annotator"] = m[f"{key}_slug"]
            recent = db.rows("SELECT * FROM task_steps WHERE agent=? AND finished_at IS NOT NULL"
                             " ORDER BY finished_at DESC LIMIT 6", (key,))
            today = db.row(
                "SELECT COUNT(*) n, SUM(status='done') ok, SUM(status='failed') bad,"
                " AVG(CASE WHEN status='done' THEN duration_ms END) avg_ms"
                " FROM task_steps WHERE agent=? AND finished_at BETWEEN ? AND ?",
                (key, start, end))
            info["today"] = {k: (today or {}).get(k) or 0 for k in ("n", "ok", "bad", "avg_ms")}
            info["recent"] = [_event(s) for s in recent]
            info["status"] = "running" if running and running["agent"] == key else (
                "queued" if db.scalar("SELECT COUNT(*) FROM task_steps WHERE agent=? AND"
                                      " status='queued'", (key,)) else "idle")
            info["now"] = _event(running) if info["status"] == "running" else None
            info["next"] = db.scalar("SELECT COUNT(*) FROM task_steps WHERE agent=? AND"
                                     " status='queued'", (key,)) or 0
        elif key == "checker":
            today = db.row("SELECT COUNT(*) n, SUM(result IS NOT NULL) ok FROM task_steps"
                           " WHERE agent IN ('classifier','verifier') AND status='done'"
                           " AND finished_at BETWEEN ? AND ?", (start, end))
            info["today"] = {"n": (today or {}).get("n") or 0, "ok": (today or {}).get("ok") or 0}
            info["status"] = "running" if running and running["agent"] in (
                "classifier", "verifier") else "idle"
            info["recent"] = []
        else:
            d = db.row("SELECT COUNT(*) n, SUM(decision='approve') approve,"
                       " SUM(decision='needs_edit') needs_edit, SUM(decision='reject') reject"
                       " FROM decisions WHERE created_at BETWEEN ? AND ?", (start, end))
            info["today"] = {k: (d or {}).get(k) or 0 for k in
                             ("n", "approve", "needs_edit", "reject")}
            info["status"] = "human"
            info["recent"] = []
        out.append(info)
    return {"agents": out, "queued_steps": queued,
            "running": _event(running) if running else None}


MODEL_AGENTS = ("classifier", "method_specialist", "verifier")


def _stats(rows: list[dict]) -> dict:
    """Timing, failure and token facts over finished steps (not accuracy)."""
    done = [r for r in rows if r["status"] == "done"]
    failed = [r for r in rows if r["status"] in ("failed", "interrupted")]
    secs = [r["duration_ms"] / 1000 for r in done if r["duration_ms"] is not None]
    tin = tout = calls = maxp = 0
    tok_secs = 0.0
    for r in rows:
        res = db.loads(r.get("result"), {}) or {}
        if res.get("model_calls"):
            calls += int(res["model_calls"])
            tin += int(res.get("tokens_in") or 0)
            tout += int(res.get("tokens_out") or 0)
            maxp = max(maxp, int(res.get("max_prompt") or 0))
            if r["status"] == "done" and r["duration_ms"]:
                tok_secs += r["duration_ms"] / 1000
    decided = len(done) + len(failed)
    median = _pct(secs, 0.5)
    return {
        "n": len(rows), "ok": len(done), "failed": len(failed),
        "skipped": sum(1 for r in rows if r["status"] == "skipped"),
        "fail_pct": round(100 * len(failed) / decided) if decided else None,
        "median_s": round(median, 1) if median is not None else None,
        "p95_s": round(_pct(secs, 0.95), 1) if secs else None,
        "max_s": round(max(secs), 1) if secs else None,
        "busy_s": round(sum(secs)),
        "model_calls": calls, "tokens_in": tin, "tokens_out": tout, "max_prompt": maxp,
        "tokens_per_s": round(tout / tok_secs, 1) if tok_secs and tout else None,
    }


def _proc_usage(pid: int | None, started_wall: float | None) -> dict | None:
    """RSS and average CPU of the running step's process, read from /proc (Linux only)."""
    if not pid:
        return None
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8") as f:
            rss_kb = next((int(line.split()[1]) for line in f if line.startswith("VmRSS:")), None)
        with open(f"/proc/{pid}/stat", encoding="utf-8") as f:
            fields = f.read().rsplit(")", 1)[1].split()
        cpu_s = (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError, StopIteration):
        return None
    wall = max(1.0, db.now() - (started_wall or db.now()))
    return {"rss_mb": round(rss_kb / 1024, 1) if rss_kb else None,
            "cpu_pct": round(100 * cpu_s / wall, 1)}


_REVIEW_CACHE: dict[str, tuple[float, dict]] = {}


def _review_counts() -> dict:
    """Moves waiting for the human specialist (cached 30 s: it reads every window file)."""
    key = db.mode()
    hit = _REVIEW_CACHE.get(key)
    if hit and time.time() - hit[0] < 30:
        return hit[1]
    units = pipeline.review_units()
    decided = {(r["tafsir"], r["window"], r["annotator"]): r["n"] for r in db.rows(
        "SELECT tafsir, window, annotator, COUNT(DISTINCT move_id) n FROM decisions"
        " GROUP BY tafsir, window, annotator")}
    total = sum(u["moves"] for u in units)
    done = sum(min(u["moves"], decided.get((u["tafsir"], u["window"], u.get("annotator")), 0))
               for u in units)
    out = {"units": len(units), "moves": total, "decided": done, "waiting": max(0, total - done)}
    _REVIEW_CACHE[key] = (time.time(), out)
    return out


def _loaded(model: str | None) -> dict | None:
    """This model's entry in the model server's memory (GET /api/ps), if loaded."""
    if not model:
        return None
    ps = pipeline.ollama_ps()
    for x in ps.get("models") or []:
        if x.get("name") == model:
            return x
    return {"name": model, "loaded": False} if ps.get("available") else None


def agent_detail(key: str, with_output: bool = False) -> dict:
    """Everything the mission-control hover card shows for one agent, from real steps.

    Timing, token and routing counts — not accuracy. ``with_output`` adds the last
    output line of the latest failure (operators only).
    """
    keys = {a["key"] for a in AGENTS}
    if key not in keys:
        raise TaskError("agent_unknown")
    m = pipeline.models()
    now = db.now()
    start, end = day_bounds(local_now().date().isoformat())
    week = now - 7 * 86400
    base: dict[str, Any] = {"key": key, "server_time": now,
                            "caption_ar": "أعداد توقيت وتوجيه ورموز وليست دقة"}
    if key in MODEL_AGENTS or key == "chair":
        agents: tuple[str, ...] = (key,)
        base["model"] = (m["classifier"] if key in ("classifier", "method_specialist") else
                         m["verifier"] if key == "verifier" else "")
    elif key == "checker":  # runs inside every classifier and verifier step
        agents = ("classifier", "verifier")
    else:
        agents = ()
    if base.get("model"):
        base["loaded"] = _loaded(base["model"])
    if agents:
        ph = ",".join("?" * len(agents))
        rows_week = db.rows(f"SELECT * FROM task_steps WHERE agent IN ({ph}) AND finished_at >= ?",
                            (*agents, week))
        rows_week.sort(key=lambda r: r["finished_at"] or 0)
        rows_today = [r for r in rows_week if start <= (r["finished_at"] or 0) < end]
        base["today"] = _stats(rows_today)
        base["week"] = _stats(rows_week)
        agg: dict[str, int] = {}
        reasons: dict[str, int] = {}
        arms: dict[str, int] = {}
        for r in rows_today:
            res = db.loads(r.get("result"), {}) or {}
            for k in ("moves", "auto_candidate", "specialist", "flags", "confirm", "reject",
                      "reframe", "abstain", "invalid"):
                if res.get(k) is not None:
                    agg[k] = agg.get(k, 0) + int(res[k] or 0)
            for k, v in (res.get("reasons") or {}).items():
                if v:
                    reasons[k] = reasons.get(k, 0) + int(v)
            if res.get("reason_code"):
                reasons[res["reason_code"]] = reasons.get(res["reason_code"], 0) + 1
            if r["status"] != "skipped":
                arm = "B" if r.get("variant") else "A"
                arms[arm] = arms.get(arm, 0) + 1
        base["outcomes_today"] = agg
        base["reasons_today"] = reasons
        base["arms_today"] = arms
        last_fail = next((r for r in reversed(rows_week)
                          if r["status"] in ("failed", "interrupted")), None)
        if last_fail:
            res = db.loads(last_fail.get("result"), {}) or {}
            fail = {"at": last_fail["finished_at"], "tafsir": last_fail["tafsir"],
                    "window": last_fail["window"], "agent": last_fail["agent"],
                    "code": res.get("reason_code") or last_fail["status"]}
            if with_output:
                tail = [ln for ln in (last_fail.get("output_tail") or "").strip().splitlines()
                        if ln.strip() and not _USAGE_RE.match(ln.strip())]
                fail["line"] = (tail[-1] if tail else "")[:160]
            base["last_failure"] = fail
        finished = [r for r in rows_week if r["status"] != "skipped"]
        base["spark"] = [{"s": round((r["duration_ms"] or 0) / 1000, 1), "st": r["status"],
                          "arm": "B" if r.get("variant") else "A", "at": r["finished_at"],
                          "w": r["window"], "t": r["tafsir"]} for r in finished[-24:]]
        base["recent"] = [{**(_event(r) or {}), "variant": r.get("variant") or ""}
                          for r in reversed(rows_week[-6:])]
        waiting = db.scalar(f"SELECT COUNT(*) FROM task_steps WHERE agent IN ({ph}) AND"
                            " status='queued'", agents) or 0
        med = base["today"]["median_s"] or base["week"]["median_s"]
        base["queue"] = {"waiting": waiting,
                         "eta_s": round(waiting * med) if (waiting and med) else None}
    running = db.row("SELECT s.*, t.title_ar, t.total_steps, t.done_steps, t.failed_steps,"
                     " t.skipped_steps FROM task_steps s JOIN tasks t ON t.id=s.task_id"
                     " WHERE s.status='running' LIMIT 1")
    if running and running["agent"] in agents:
        proc = _current.get("proc") if _current.get("step_id") == running["id"] else None
        pid = getattr(proc, "pid", None)
        base["now"] = {**(_event(running) or {}), "variant": running.get("variant") or "",
                       "elapsed_s": round(now - (running["started_at"] or now)),
                       "pid": pid, "proc": _proc_usage(pid, running["started_at"]),
                       "task_done": (running["done_steps"] or 0) + (running["skipped_steps"] or 0),
                       "task_failed": running["failed_steps"] or 0,
                       "task_total": running["total_steps"] or 0,
                       "timeout_s": settings.get("llm")["step_timeout_s"]}
    if key == "specialist":
        rows = db.rows("SELECT decision, teach, created_at FROM decisions WHERE created_at >= ?",
                       (week,))

        def count(rs: list[dict]) -> dict:
            out = {"n": len(rs), "approve": 0, "needs_edit": 0, "reject": 0, "lessons": 0}
            for d in rs:
                out[d["decision"]] = out.get(d["decision"], 0) + 1
                if (db.loads(d.get("teach"), {}) or {}).get("teach"):
                    out["lessons"] += 1
            return out
        base["today"] = count([d for d in rows if start <= d["created_at"] < end])
        base["week"] = count(rows)
        base["review"] = _review_counts()
        base["people"] = workflow.team_load() if db.mode() != "demo" else []
        last = db.row("SELECT created_at FROM decisions ORDER BY created_at DESC LIMIT 1")
        base["last_decision_at"] = last["created_at"] if last else None
    return base


def model_layer() -> dict:
    """The brain orb's card: what the model server holds now and today's model traffic."""
    m = pipeline.models()
    now = db.now()
    start, end = day_bounds(local_now().date().isoformat())
    rows = db.rows("SELECT agent, model, status, duration_ms, finished_at, result FROM task_steps"
                   " WHERE agent IN ('classifier','method_specialist','verifier')"
                   " AND finished_at BETWEEN ? AND ?", (start, end))
    per: dict[str, dict] = {}
    for r in rows:
        name = r["model"] or (m["classifier"] if r["agent"] != "verifier" else m["verifier"])
        p = per.setdefault(name, {"steps": 0, "calls": 0, "tokens_in": 0, "tokens_out": 0,
                                  "max_prompt": 0, "busy_s": 0.0})
        res = db.loads(r.get("result"), {}) or {}
        if r["status"] != "skipped":
            p["steps"] += 1
            p["busy_s"] += (r["duration_ms"] or 0) / 1000
        p["calls"] += int(res.get("model_calls") or 0)
        p["tokens_in"] += int(res.get("tokens_in") or 0)
        p["tokens_out"] += int(res.get("tokens_out") or 0)
        p["max_prompt"] = max(p["max_prompt"], int(res.get("max_prompt") or 0))
    last5 = [r for r in rows if (r["finished_at"] or 0) >= now - 300 and r["status"] != "skipped"]
    running = db.row("SELECT agent, tafsir, window, started_at FROM task_steps"
                     " WHERE status='running' LIMIT 1")
    for p in per.values():
        p["busy_s"] = round(p["busy_s"])
    return {"server_time": now, "ps": pipeline.ollama_ps(), "per_model": per,
            "today": {k: sum(p[k] for p in per.values())
                      for k in ("steps", "calls", "tokens_in", "tokens_out")},
            "last5": {"steps": len(last5), "calls": sum(
                int((db.loads(r.get("result"), {}) or {}).get("model_calls") or 0) for r in last5)},
            "running": running if running and running["agent"] in MODEL_AGENTS else None,
            "classifier_model": m["classifier"], "verifier_model": m["verifier"]}


def _event(s: dict | None) -> dict | None:
    if not s:
        return None
    return {"id": s["id"], "task_id": s["task_id"], "agent": s["agent"], "tafsir": s["tafsir"],
            "window": s["window"], "model": s.get("model"), "status": s["status"],
            "started_at": s.get("started_at"), "finished_at": s.get("finished_at"),
            "duration_ms": s.get("duration_ms"), "result": db.loads(s.get("result")),
            "title_ar": s.get("title_ar")}


# ------------------------------------------------------------------ performance

def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    i = min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))
    return v[i]


def perf_summary(start: float | None = None, end: float | None = None) -> dict:
    """Latency, failures and throughput per agent/model from recorded steps.

    Counts are routing and timing facts, not accuracy.
    """
    q = ("SELECT agent, model, tafsir, window, status, duration_ms, result FROM task_steps"
         " WHERE agent IN ('classifier','verifier','chair') AND finished_at IS NOT NULL")
    params: list = []
    if start is not None:
        q += " AND finished_at BETWEEN ? AND ?"
        params += [start, end]
    rows = db.rows(q, params)
    chars = {}
    for t in config.TAFSIRS:
        for w in pipeline.windows(t):
            chars[(t, w["window"])] = w["chars"]
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        if r["status"] == "skipped":
            continue
        groups.setdefault((r["agent"], r["model"] or ""), []).append(r)
    agents = []
    m = pipeline.models()
    prog = pipeline.progress(as_of=end)["totals"]
    for (agent, model), rs in sorted(groups.items()):
        ok = [r for r in rs if r["status"] == "done"]
        secs = [r["duration_ms"] / 1000 for r in ok if r["duration_ms"] is not None]
        tot_chars = sum(chars.get((r["tafsir"], r["window"]), 0) for r in ok)
        reasons: dict[str, int] = {}
        moves = auto = 0
        for r in rs:
            res = db.loads(r["result"], {}) or {}
            if res.get("reason_code"):
                reasons[res["reason_code"]] = reasons.get(res["reason_code"], 0) + 1
            moves += int(res.get("moves") or 0)
            auto += int(res.get("auto_candidate") or 0)
        median = _pct(secs, 0.5)
        done_windows = prog["classifier"] if agent == "classifier" else (
            prog["verifier"] if agent == "verifier" else prog["committee"])
        remaining = max(0, prog["windows"] - done_windows)
        is_current = (agent == "chair") or model in (m["classifier"], m["verifier"])
        agents.append({
            "agent": agent, "model": model if agent != "chair" else "", "n": len(rs),
            "ok": len(ok), "failed": len(rs) - len(ok),
            "median_s": round(median, 1) if median is not None else None,
            "p95_s": round(_pct(secs, 0.95), 1) if secs else None,
            "max_s": round(max(secs), 1) if secs else None,
            "chars_per_s": round(tot_chars / sum(secs)) if secs and sum(secs) else None,
            "moves_per_window": round(moves / len(ok), 1) if ok else None,
            "auto_candidate": auto, "moves": moves, "failure_codes": reasons,
            "remaining_windows": remaining if is_current else None,
            "eta_min": round(remaining * median / 60) if (is_current and median) else None,
        })
    return {"agents": agents, "caption_ar": "أعداد توجيه وتوقيت وليست دقة"}


# ------------------------------------------------------------------ reports

REASON_AR = {
    "written_abstain": "امتناع مكتوب", "force_specialist": "إحالة الفاحص",
    "agent_disagree": "اختلاف الوكيلين", "unclear_bounds": "حدود غير متقاطعة",
    "weak_evidence": "دليل غير كافٍ", "agent_missing": "لم يعمل المدقّق بعد",
    "specialist_block": "منع الأخصائي الآلي",
    "specialist_missing": "لا حكم من الأخصائي الآلي",
}


def build_report(day: str, as_of: float | None = None) -> dict:
    start, end = day_bounds(day)
    steps = db.rows("SELECT * FROM task_steps WHERE finished_at BETWEEN ? AND ?", (start, end))
    ok = [s for s in steps if s["status"] == "done"]
    failed = [s for s in steps if s["status"] in ("failed", "interrupted")]
    by_agent: dict[str, dict] = {}
    routes = {"moves": 0, "auto_candidate": 0, "specialist": 0, "flags": 0}
    committee = {"windows": 0, "moves": 0, "auto_candidate": 0, "specialist": 0, "reasons": {}}
    for s in steps:
        a = by_agent.setdefault(s["agent"], {"done": 0, "failed": 0, "skipped": 0,
                                             "models": set(), "ms": []})
        if s["status"] == "done":
            a["done"] += 1
            if s["duration_ms"] is not None:
                a["ms"].append(s["duration_ms"])
        elif s["status"] in ("failed", "interrupted"):
            a["failed"] += 1
        elif s["status"] == "skipped":
            a["skipped"] += 1
        if s.get("model"):
            a["models"].add(s["model"])
        r = db.loads(s.get("result"), {}) or {}
        if s["agent"] == "classifier" and s["status"] == "done":
            for k in routes:
                routes[k] += int(r.get(k) or 0)
        if s["agent"] == "chair" and s["status"] == "done":
            committee["windows"] += 1
            for k in ("moves", "auto_candidate", "specialist"):
                committee[k] += int(r.get(k) or 0)
            for k, v in (r.get("reasons") or {}).items():
                committee["reasons"][k] = committee["reasons"].get(k, 0) + int(v or 0)
    agents = {k: {"done": v["done"], "failed": v["failed"], "skipped": v["skipped"],
                  "models": sorted(v["models"]),
                  "avg_s": round(sum(v["ms"]) / len(v["ms"]) / 1000, 1) if v["ms"] else None}
              for k, v in by_agent.items()}
    windows_by_tafsir: dict[str, int] = {}
    for s in ok:
        if s["agent"] == "classifier":
            windows_by_tafsir[s["tafsir"]] = windows_by_tafsir.get(s["tafsir"], 0) + 1
    tasks = db.rows("SELECT id,title_ar,status,total_steps,done_steps,failed_steps,"
                    "skipped_steps,created_at,finished_at FROM tasks"
                    " WHERE created_at BETWEEN ? AND ? OR finished_at BETWEEN ? AND ?"
                    " ORDER BY id", (start, end, start, end))
    dec = db.row("SELECT COUNT(*) n, SUM(decision='approve') approve,"
                 " SUM(decision='needs_edit') needs_edit, SUM(decision='reject') reject"
                 " FROM decisions WHERE created_at BETWEEN ? AND ?", (start, end)) or {}
    prog = pipeline.progress(as_of=as_of)
    gates = pipeline.gates(as_of)
    nxt = []
    if not gates["phase0_merged"]:
        nxt.append("إغلاق فجوات الإسناد السبع (المرحلة ٠) ودمجها قبل أي وسم جماعي.")
    if prog["totals"]["classifier"] == 0:
        nxt.append(f"تشغيل اللجنة على العيّنة (آية النور {settings.get('general')['sample_ayah']}) بالتفاسير الأربعة.")
    elif not gates["sample_reviewed"]:
        nxt.append("مراجعة العيّنة من المتخصص قبل فتح الوسم الجماعي.")
    if failed:
        nxt.append(f"إعادة {len(failed)} خطوة فاشلة بعد قراءة سبب الفشل.")
    if prog["totals"]["both"] < prog["totals"]["classifier"]:
        nxt.append("تشغيل المدقّق على النوافذ التي صنّفها المصنّف فقط.")
    return {
        "day": day, "timezone": settings.get("general")["timezone"],
        "generated_at": db.now(),
        "steps": {"total": len(steps), "done": len(ok), "failed": len(failed),
                  "skipped": sum(1 for s in steps if s["status"] == "skipped")},
        "agents": agents,
        "windows_by_tafsir": windows_by_tafsir,
        "routes": routes, "routes_caption_ar": "أعداد توجيه وليست دقة",
        "committee": committee,
        "perf": perf_summary(start, end),
        "tasks": tasks,
        "decisions": {k: dec.get(k) or 0 for k in ("n", "approve", "needs_edit", "reject")},
        "failures": [{"task_id": s["task_id"], "agent": s["agent"], "tafsir": s["tafsir"],
                      "window": s["window"], "model": s["model"], "exit_code": s["exit_code"],
                      "last_line": ((s.get("output_tail") or "").strip().splitlines() or [""])[-1][:200]}
                     for s in failed[:20]],
        "progress": prog["totals"],
        "models": prog["models"],
        "gates": {"phase0_merged": gates["phase0_merged"],
                  "sample_reviewed": gates["sample_reviewed"]},
        "next_ar": nxt,
        "chair": workflow.chair_section(start, end, as_of),
    }


def save_report(day: str, user_id: int | None) -> dict:
    content = build_report(day)
    db.execute(
        "INSERT INTO reports(day,generated_at,generated_by,content) VALUES (?,?,?,?)"
        " ON CONFLICT(day) DO UPDATE SET generated_at=excluded.generated_at,"
        " generated_by=excluded.generated_by, content=excluded.content",
        (day, content["generated_at"], user_id, db.dumps(content)),
    )
    db.audit("report.generate", user_id=user_id, target=day)
    return content


def report_markdown(c: dict) -> str:
    names = config.TAFSIR_NAMES_AR
    agent_ar = {a["key"]: a["name_ar"] for a in AGENTS}
    agent_ar["packet_check"] = "فحص الحزم"
    lines = [f"# التقرير اليومي — {c['day']}", "",
             f"الخطوات: {c['steps']['total']} · نجحت {c['steps']['done']} · فشلت "
             f"{c['steps']['failed']} · تُخطّيت {c['steps']['skipped']}", ""]
    lines.append("## الوكلاء")
    for k, v in c["agents"].items():
        lines.append(f"- {agent_ar.get(k, k)}: نجح {v['done']} · فشل {v['failed']} · "
                     f"تخطٍّ {v['skipped']} · النماذج: {', '.join(v['models']) or '—'}"
                     + (f" · متوسط {v['avg_s']} ث" if v["avg_s"] else ""))
    lines += ["", "## النوافذ المصنّفة اليوم"]
    for t, n in c["windows_by_tafsir"].items():
        lines.append(f"- {names.get(t, t)}: {n}")
    if not c["windows_by_tafsir"]:
        lines.append("- لا شيء")
    r = c["routes"]
    lines += ["", f"## التوجيه ({c['routes_caption_ar']})",
              f"- حركات: {r['moves']} · مرشّح للمراجعة: {r['auto_candidate']} · "
              f"بانتظار المتخصص: {r['specialist']} · أعلام: {r['flags']}"]
    cm = c.get("committee") or {}
    if cm.get("windows"):
        reasons = " · ".join(f"{REASON_AR.get(k, k)} {v}" for k, v in cm["reasons"].items() if v)
        lines += ["", "## قرار رئيس اللجنة",
                  f"- نوافذ: {cm['windows']} · حركات: {cm['moves']} · مرشّح للمراجعة: "
                  f"{cm['auto_candidate']} · بانتظار المتخصص: {cm['specialist']}",
                  f"- أسباب الامتناع: {reasons or '—'}"]
    pf = c.get("perf") or {}
    if pf.get("agents"):
        lines += ["", "## أداء الوكلاء"]
        for a in pf["agents"]:
            lines.append(f"- {agent_ar.get(a['agent'], a['agent'])} ({a['model'] or '—'}): "
                         f"{a['ok']}/{a['n']} نجحت · وسيط {a['median_s']} ث · "
                         f"أبطأ ٩٥٪ {a['p95_s']} ث · {a['chars_per_s']} حرف/ث")
    d = c["decisions"]
    lines += ["", "## قرارات المتخصص",
              f"- المجموع {d['n']} · اعتماد {d['approve']} · يحتاج تعديلاً {d['needs_edit']}"
              f" · رفض {d['reject']}"]
    p = c["progress"]
    lines += ["", "## التقدّم التراكمي",
              f"- نوافذ صنّفها المصنّف: {p['classifier']} من {p['windows']}",
              f"- نوافذ عمل عليها الوكيلان: {p['both']} من {p['windows']}"]
    if c["failures"]:
        lines += ["", "## الإخفاقات"]
        for f in c["failures"]:
            lines.append(f"- #{f['task_id']} {agent_ar.get(f['agent'], f['agent'])} · "
                         f"{names.get(f['tafsir'], f['tafsir'])} {f['window']} · "
                         f"{f['model'] or ''} · {f['last_line']}")
    ch = c.get("chair") or {}
    if ch.get("specialists"):
        lines += ["", "## المتخصصون"]
        for sp in ch["specialists"]:
            lines.append(f"- {sp['name']}: {sp['open_moves']} حركة مفتوحة في {sp['open_windows']}"
                         f" نافذة · أقدمها {sp['oldest_days']:.0f} يوم · قرارات اليوم"
                         f" {sp['decided_today']}")
    if ch.get("suggestions_ar"):
        lines += ["", "## مقترحات رئيس اللجنة"] + [f"- {x}" for x in ch["suggestions_ar"]]
    lines += ["", "## الخطوة التالية"] + [f"- {x}" for x in c["next_ar"] or ["—"]]
    lines += ["", f"النماذج: المصنّف {c['models']['classifier']} · المدقّق "
              f"{c['models']['verifier']}"]
    return "\n".join(lines) + "\n"


def mail_report(day: str, user_id: int | None) -> dict:
    rec = db.row("SELECT * FROM reports WHERE day=?", (day,))
    content = db.loads(rec["content"]) if rec else save_report(day, user_id)
    roles = settings.get("reports")["mail_roles"]
    if not roles:
        return {"sent": 0, "failed": 0}
    users = workflow.users_with_roles(roles)
    mail = mailtpl.report(content, report_markdown(content))
    sent = failed = 0
    for u in users:
        try:
            mailer.send_mail(u["email"], mail)
            sent += 1
        except mailer.MailError:
            failed += 1
    db.execute("UPDATE reports SET mailed_at=? WHERE day=?", (db.now(), day))
    db.audit("report.mail", user_id=user_id, target=day, detail={"sent": sent, "failed": failed})
    return {"sent": sent, "failed": failed}


def scheduler_tick(state: dict | None = None) -> dict:
    """One pass of the background clock: daily report, reminders, assignment sweep,
    failure and engine alerts. Each part is independent; one failing never stops the rest."""
    state = state if state is not None else {}
    did: dict[str, Any] = {}
    now = local_now()
    day = now.date().isoformat()
    try:
        cfg = settings.get("reports")
        if cfg["auto_daily"] and now.strftime("%H:%M") >= cfg["daily_time"]:
            rec = db.row("SELECT mailed_at FROM reports WHERE day=?", (day,))
            if rec is None or rec["mailed_at"] is None:
                save_report(day, None)
                did["report"] = mail_report(day, None)
    except Exception:  # pragma: no cover - never kill the scheduler
        log.exception("daily report")
    try:
        wf = settings.get("workflow")
        if wf["reminders"] and now.strftime("%H:%M") >= wf["reminder_time"] \
                and db.meta_get("reminders_day") != day:
            db.meta_set("reminders_day", day)
            did["reminders"] = workflow.send_reminders()
    except Exception:  # pragma: no cover
        log.exception("reminders")
    try:
        if time.time() - state.get("swept", 0) > 300:
            state["swept"] = time.time()
            did["sweep"] = workflow.sweep()
    except Exception:  # pragma: no cover
        log.exception("assignment sweep")
    try:
        did["alerts"] = workflow.failure_alerts()
        if db.meta_get("engine_down_since"):
            waiting = db.scalar("SELECT COUNT(*) FROM task_steps WHERE status='queued' AND agent IN"
                                " ('classifier','method_specialist','verifier')") or 0
            if waiting and not _engine_up(force=True):
                did["engine"] = workflow.engine_alert(waiting)
            elif _engine_up():
                db.meta_set("engine_down_since", None)
    except Exception:  # pragma: no cover
        log.exception("alerts")
    return did


def _scheduler() -> None:
    state: dict = {}
    while not _stop.is_set():
        scheduler_tick(state)
        _stop.wait(30)


def start() -> None:
    if _threads:
        return
    _stop.clear()
    recover_interrupted()
    for target, name in ((_worker, "mirqah-worker"), (_scheduler, "mirqah-reports")):
        th = threading.Thread(target=target, name=name, daemon=True)
        th.start()
        _threads.append(th)


def stop() -> None:
    _stop.set()
    proc = _current.get("proc")
    if proc is not None:
        proc.kill()
    for th in _threads:
        th.join(timeout=5)
    _threads.clear()
