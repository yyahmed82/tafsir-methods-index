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

from . import config, db, mailer, mailtpl, pipeline, settings

log = logging.getLogger("mirqah.console")

KINDS = {
    "committee": ("classifier", "verifier", "chair"),
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
        for arm in TASK_VARIANTS[variant]:
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


def retry_failed(task_id: int, user: dict) -> int:
    t = db.row("SELECT * FROM tasks WHERE id=?", (task_id,))
    if t is None:
        raise TaskError("task_not_found")
    failed = db.rows("SELECT * FROM task_steps WHERE task_id=? AND (status IN"
                     " ('failed','interrupted') OR (status='skipped' AND agent='chair'"
                     " AND result LIKE '%\"agent_missing\"%')) ORDER BY seq", (task_id,))
    if not failed:
        raise TaskError("nothing_to_retry")
    order = {"packet_check": 0, "classifier": 1, "verifier": 2, "chair": 3}
    failed.sort(key=lambda s: (order.get(s["agent"], 9), s["seq"]))  # one model at a time
    p = db.loads(t["params"], {})
    p["retry_of"] = task_id
    with db.connect() as con:
        cur = con.execute(
            "INSERT INTO tasks(kind,title_ar,params,status,created_by,created_at,total_steps)"
            " VALUES (?,?,?,?,?,?,?)",
            (t["kind"], f"إعادة الفاشل من المهمة #{task_id}", db.dumps(p), "queued",
             user["id"], db.now(), len(failed)),
        )
        new_id = int(cur.lastrowid)
        con.executemany(
            "INSERT INTO task_steps(task_id,seq,agent,tafsir,window,model,status,variant)"
            " VALUES (?,?,?,?,?,?,'queued',?)",
            [(new_id, i, s["agent"], s["tafsir"], s["window"], s["model"],
              s.get("variant") or "") for i, s in enumerate(failed)],
        )
    db.audit("task.retry", user_id=user["id"], target=str(new_id), detail={"from": task_id})
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


def _run_step(task: dict, step: dict) -> None:
    params = db.loads(task["params"], {})
    started = db.now()
    db.execute("UPDATE task_steps SET status='running', started_at=? WHERE id=?",
               (started, step["id"]))
    if params.get("skip_done") and step["agent"] in ("classifier", "verifier", "chair"):
        variant = step.get("variant") or None
        if step["agent"] == "chair":
            done = pipeline.committee_is_current(step["tafsir"], step["window"], variant)
        else:
            slug = pipeline.variant_annotator(pipeline.model_slug(step["model"]), variant)
            done = pipeline.verified_path(step["tafsir"], slug, step["window"]).is_file()
        if done:
            db.execute("UPDATE task_steps SET status='skipped', finished_at=?, duration_ms=0,"
                       " result=? WHERE id=?",
                       (db.now(), db.dumps({"reason": "already_verified"}), step["id"]))
            db.execute("UPDATE tasks SET skipped_steps=skipped_steps+1 WHERE id=?", (task["id"],))
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
                    reason = "timeout" if time.monotonic() > deadline else "cancelled"
                    output = (output or "") + f"\n[console] step {reason}"
                    _record_step(task, step, started, -9, output, None,
                                 status="cancelled" if reason == "cancelled" else "failed")
                    return
    finally:
        _current.update(proc=None, step_id=None)
    result = None
    m = _VERIFIER_RE.search(output or "")
    cm = _CHAIR_RE.search(output or "")
    if m:
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
    _record_step(task, step, started, proc.returncode, output, result)


def _record_step(task: dict, step: dict, started: float, code: int, output: str,
                 result: dict | None, status: str | None = None) -> None:
    status = status or ("done" if code == 0 else "failed")
    tail = "\n".join((output or "").strip().splitlines()[-25:])[-4000:]
    fin = db.now()
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
        step = db.row("SELECT * FROM task_steps WHERE task_id=? AND status='queued'"
                      " ORDER BY seq LIMIT 1", (task["id"],))
        cancelled = db.scalar("SELECT cancel_requested FROM tasks WHERE id=?", (task["id"],))
        if cancelled:
            _finish_task(task["id"], "cancelled")
            continue
        if step is None:
            t = db.row("SELECT * FROM tasks WHERE id=?", (task["id"],))
            _finish_task(task["id"], "failed" if t["failed_steps"] else "done")
            continue
        try:
            _run_step(task, step)
        except Exception as e:  # keep the worker alive; record the failure honestly
            log.exception("step %s crashed", step["id"])
            _record_step(task, step, db.now(), 1, f"console error: {type(e).__name__}: {e}", None)


def recover_interrupted() -> None:
    """Called on start: steps that were running when the server stopped."""
    with db.connect() as con:
        con.execute("UPDATE task_steps SET status='interrupted', finished_at=?"
                    " WHERE status='running'", (db.now(),))
        con.execute("UPDATE tasks SET failed_steps=(SELECT COUNT(*) FROM task_steps s"
                    " WHERE s.task_id=tasks.id AND s.status IN ('failed','interrupted'))"
                    " WHERE status='running'")


# ------------------------------------------------------------------ agents

AGENTS = [
    {"key": "classifier", "name_ar": "المصنّف", "color": "blue",
     "desc_ar": "يقترح المنهج والدور واليقين وحدود الشاهد بمعرّفات الأجزاء فقط."},
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
        if key in ("classifier", "verifier", "chair"):
            if key == "chair":
                info["model"] = f"{m['classifier']} + {m['verifier']}"
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
        nxt.append("تشغيل اللجنة على العيّنة (آية النور ٢٤:٣٥) بالتفاسير الأربعة.")
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
    q = ",".join("?" * len(roles))
    users = db.rows(f"SELECT u.email FROM users u JOIN roles r ON r.id=u.role_id"
                    f" WHERE u.active=1 AND r.key IN ({q})", roles)
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


def _scheduler() -> None:
    while not _stop.is_set():
        try:
            cfg = settings.get("reports")
            now = local_now()
            if cfg["auto_daily"] and now.strftime("%H:%M") >= cfg["daily_time"]:
                day = now.date().isoformat()
                rec = db.row("SELECT mailed_at FROM reports WHERE day=?", (day,))
                if rec is None or rec["mailed_at"] is None:
                    save_report(day, None)
                    mail_report(day, None)
        except Exception:  # pragma: no cover - never kill the scheduler
            log.exception("daily report scheduler")
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
