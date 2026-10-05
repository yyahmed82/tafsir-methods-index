"""The committee chair's human side.

* Assignment — every window the chair has decided (both blind versions X and Y
  together) goes to one human specialist: the one with the fewest open moves.
  Only that specialist decides it; operators and super admins can reassign.
* Reminders — each morning (Settings → Workflow) every specialist with open
  windows gets one e-mail listing them, until they are decided.
* Chair report — the evening daily report carries the specialists' backlog and
  the chair's suggestions for Committee operators and Super admins.
* Retries and alerts — a failed step is retried automatically (5 min, then
  30 min by default); a restart or an offline model engine never uses up an
  attempt. A step that still fails is e-mailed to operators and super admins,
  batched so a bad hour sends one message, not fifty.

Counts here are routing and timing facts, never accuracy, and nothing here
approves anything: only a specialist's decision does.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from . import config, db, mailer, mailtpl, pipeline, settings

log = logging.getLogger("mirqah.console")

DAY = 86400


# ------------------------------------------------------------------ people

def users_with_roles(keys: list[str] | tuple[str, ...]) -> list[dict]:
    """Active users holding any of these roles (guests excluded), oldest first."""
    keys = [k for k in keys if k]
    if not keys:
        return []
    ph = ",".join("?" * len(keys))
    if db.mode() == "demo":  # simulated people carry one role_key each
        return db.rows(f"SELECT id, name, email, '' AS lang FROM users WHERE active=1"
                       f" AND role_key IN ({ph}) ORDER BY id", keys)
    return db.rows(
        f"SELECT DISTINCT u.id, u.name, u.email, u.lang FROM users u"
        f" JOIN {db.USER_ROLES} ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id"
        f" WHERE u.active=1 AND u.email<>? AND r.key IN ({ph}) ORDER BY u.id",
        (config.GUEST_EMAIL, *keys))


def specialists() -> list[dict]:
    return users_with_roles([config.DECIDER_ROLE])


# ------------------------------------------------------------------ what waits for a human

def window_backlog(tafsir: str | None = None) -> dict[tuple[str, str], dict]:
    """Per window the chair has decided: moves, decided moves and what is still open."""
    decided = {(r["tafsir"], r["window"], r["annotator"]): r["n"] for r in db.rows(
        "SELECT tafsir, window, annotator, COUNT(DISTINCT move_id) AS n FROM decisions"
        " GROUP BY tafsir, window, annotator")}
    out: dict[tuple[str, str], dict] = {}
    for u in pipeline.review_units(tafsir):
        if not u.get("committee"):
            continue  # only what the chair has decided goes to a specialist
        key = (u["tafsir"], u["window"])
        b = out.setdefault(key, {"tafsir": u["tafsir"], "window": u["window"],
                                 "name_ar": u.get("name_ar") or config.TAFSIR_NAMES_AR.get(
                                     u["tafsir"], u["tafsir"]),
                                 "ayah": u.get("ayah"), "ayah_number": u.get("ayah_number"),
                                 "moves": 0, "decided": 0, "units": 0, "arms": []})
        n = int(u.get("moves") or 0)
        d = min(n, int(decided.get((u["tafsir"], u["window"], u.get("annotator")), 0)))
        b["moves"] += n
        b["decided"] += d
        b["units"] += 1
        if u.get("arm"):
            b["arms"].append(u["arm"])
    for b in out.values():
        b["open"] = max(0, b["moves"] - b["decided"])
    return out


def assignment(tafsir: str, window: str) -> dict | None:
    a = db.row("SELECT a.*, u.name AS user_name, u.email AS user_email FROM assignments a"
               " LEFT JOIN users u ON u.id=a.user_id WHERE a.tafsir=? AND a.window=?",
               (tafsir, window))
    return a


def assignments_map() -> dict[tuple[str, str], dict]:
    return {(a["tafsir"], a["window"]): a for a in db.rows(
        "SELECT a.*, u.name AS user_name FROM assignments a LEFT JOIN users u ON u.id=a.user_id")}


def _load(backlog: dict, amap: dict) -> dict[int, int]:
    """Open moves currently on each person's desk."""
    load: dict[int, int] = {}
    for key, a in amap.items():
        if a["status"] == "open":
            load[a["user_id"]] = load.get(a["user_id"], 0) + (backlog.get(key) or {}).get("open", 0)
    return load


def _pick(people: list[dict], load: dict[int, int]) -> dict | None:
    if not people:
        return None
    return min(people, key=lambda p: (load.get(p["id"], 0), p["id"]))


def _write(tafsir: str, window: str, user_id: int, by: int | None, reopen: bool = False) -> None:
    db.execute(
        "INSERT INTO assignments(tafsir, window, user_id, assigned_at, assigned_by, status)"
        " VALUES (?,?,?,?,?,'open') ON CONFLICT(tafsir, window) DO UPDATE SET"
        " user_id=excluded.user_id, assigned_at=excluded.assigned_at,"
        " assigned_by=excluded.assigned_by, status='open', done_at=NULL, last_reminder_at=NULL",
        (tafsir, window, user_id, db.now(), by))
    db.audit("review.assign", user_id=by, target=f"{tafsir}/{window}",
             detail={"to": user_id, "by": "user" if by else "chair", "reopen": reopen})


def sweep(only: tuple[str, str] | None = None) -> dict:
    """Give every waiting window to a specialist and close the finished ones.

    Called after each chair step (``only`` = that window), every few minutes by the
    scheduler, and after decisions. A window whose specialist lost the role (or
    the account) moves to the least-loaded specialist.
    """
    out = {"assigned": 0, "closed": 0, "reopened": 0, "unassigned": 0}
    if db.mode() == "demo":
        return out
    cfg = settings.get("workflow")
    backlog = window_backlog()
    amap = assignments_map()
    people = specialists()
    ids = {p["id"] for p in people}
    load = _load(backlog, amap)
    for key, b in sorted(backlog.items(), key=lambda kv: (kv[1].get("ayah_number") or 0, kv[0])):
        if only and key != only:
            continue
        a = amap.get(key)
        if b["open"] == 0:
            if a and a["status"] == "open":
                db.execute("UPDATE assignments SET status='done', done_at=? WHERE tafsir=? AND"
                           " window=?", (db.now(), *key))
                out["closed"] += 1
            continue
        if a and a["status"] == "open" and a["user_id"] in ids:
            continue
        if not cfg["auto_assign"] and not (a and a["status"] == "done"):
            out["unassigned"] += 0 if a else 1
            continue
        reopen = bool(a and a["status"] == "done")
        if reopen and a["user_id"] in ids:  # new moves in a window they already finished
            who = {"id": a["user_id"]}
        else:
            who = _pick(people, load)
        if who is None:
            out["unassigned"] += 1
            continue
        _write(key[0], key[1], who["id"], None, reopen=reopen)
        load[who["id"]] = load.get(who["id"], 0) + b["open"]
        out["reopened" if reopen else "assigned"] += 1
    return out


def close_if_done(tafsir: str, window: str) -> bool:
    """After a decision: mark the window done once every move in it is decided."""
    b = window_backlog(tafsir).get((tafsir, window))
    if b is None or b["open"]:
        return False
    db.execute("UPDATE assignments SET status='done', done_at=? WHERE tafsir=? AND window=?"
               " AND status='open'", (db.now(), tafsir, window))
    return True


def reassign(tafsir: str, window: str, user_id: int, by: int) -> dict:
    if user_id not in {p["id"] for p in specialists()}:
        raise ValueError("not_a_specialist")
    _write(tafsir, window, user_id, by)
    return assignment(tafsir, window) or {}


def claim(tafsir: str, window: str, user_id: int) -> None:
    """A specialist decides a window nobody holds yet: it becomes theirs."""
    if assignment(tafsir, window) is None:
        _write(tafsir, window, user_id, user_id)


def desk(user_id: int | None = None) -> list[dict]:
    """Assigned windows with their open counts (one person, or everyone)."""
    backlog = window_backlog()
    q = ("SELECT a.*, u.name AS user_name, u.email AS user_email FROM assignments a"
         " LEFT JOIN users u ON u.id=a.user_id")
    rows = db.rows(q + (" WHERE a.user_id=?" if user_id else "") + " ORDER BY a.assigned_at",
                   (user_id,) if user_id else ())
    now = db.now()
    out = []
    for a in rows:
        b = backlog.get((a["tafsir"], a["window"])) or {}
        out.append({**a, "name_ar": b.get("name_ar") or config.TAFSIR_NAMES_AR.get(a["tafsir"]),
                    "ayah": b.get("ayah"), "moves": b.get("moves", 0),
                    "decided": b.get("decided", 0), "open": b.get("open", 0),
                    "arms": b.get("arms", []),
                    "age_days": round((now - a["assigned_at"]) / DAY, 1)})
    return out


def team_load() -> list[dict]:
    """Per specialist: open windows and moves, oldest open item, decisions today."""
    from . import runner  # local import: runner imports workflow
    start, end = runner.day_bounds(runner.local_now().date().isoformat())
    rows = desk()
    today = {r["user_id"]: r["n"] for r in db.rows(
        "SELECT user_id, COUNT(*) AS n FROM decisions WHERE created_at BETWEEN ? AND ?"
        " GROUP BY user_id", (start, end))}
    out = []
    for p in specialists():
        mine = [r for r in rows if r["user_id"] == p["id"] and r["status"] == "open"
                and r["open"] > 0]
        out.append({"id": p["id"], "name": p["name"], "email": p["email"],
                    "open_windows": len(mine), "open_moves": sum(r["open"] for r in mine),
                    "oldest_days": max((r["age_days"] for r in mine), default=0),
                    "decided_today": today.get(p["id"], 0)})
    return out


# ------------------------------------------------------------------ reminders

def send_reminders() -> dict:
    """One e-mail per specialist listing the windows still waiting for them."""
    by_user: dict[int, list[dict]] = {}
    for r in desk():
        if r["status"] == "open" and r["open"] > 0:
            by_user.setdefault(r["user_id"], []).append(r)
    people = {p["id"]: p for p in specialists()}
    sent = failed = 0
    now = db.now()
    for uid, items in by_user.items():
        p = people.get(uid)
        if p is None:
            continue
        last = max((r.get("last_reminder_at") or 0 for r in items), default=0)
        if last and now - last < REMIND_COOLDOWN_S:
            continue  # reminded by hand within the hour: no second e-mail
        try:
            mailer.send_mail(p["email"], mailtpl.review_reminder(p["name"], items))
            sent += 1
            db.execute(f"UPDATE assignments SET last_reminder_at=? WHERE user_id=? AND"
                       f" status='open'", (db.now(), uid))
        except mailer.MailError as e:
            log.warning("reminder to %s failed: %s", p["email"], e)
            failed += 1
    db.audit("review.remind", detail={"sent": sent, "failed": failed})
    return {"sent": sent, "failed": failed}


REMIND_COOLDOWN_S = 3600  # one reminder an hour per person, manual or scheduled


def remind_user(user_id: int, by: dict) -> dict:
    """Remind one specialist now: one e-mail with the windows still waiting for them.
    Refused within an hour of the last reminder (the 09:00 one counts)."""
    p = next((x for x in specialists() if x["id"] == user_id), None)
    if p is None:
        raise ValueError("not_a_specialist")
    items = [r for r in desk(user_id) if r["status"] == "open" and r["open"] > 0]
    if not items:
        raise ValueError("nothing_open")
    last = db.scalar("SELECT MAX(last_reminder_at) FROM assignments WHERE user_id=?"
                     " AND status='open'", (user_id,))
    now = db.now()
    if last and now - last < REMIND_COOLDOWN_S:
        raise ValueError("remind_cooldown")
    try:
        mailer.send_mail(p["email"], mailtpl.review_reminder(p["name"], items))
    except mailer.MailError as e:
        log.warning("reminder to %s failed: %s", p["email"], e)
        raise ValueError("mail_failed") from e
    db.execute("UPDATE assignments SET last_reminder_at=? WHERE user_id=? AND status='open'",
               (now, user_id))
    db.audit("review.remind_one", user_id=by["id"], target=str(user_id),
             detail={"windows": len(items), "moves": sum(r["open"] for r in items)})
    return {"sent": True, "at": now, "next_at": now + REMIND_COOLDOWN_S,
            "windows": len(items), "name": p["name"]}


# ------------------------------------------------------------------ chair report

def chair_section(day_start: float, day_end: float, as_of: float | None = None) -> dict:
    """What the daily report adds for operators and super admins: people, backlog,
    publishing, and the chair's suggestions (plain rules, Arabic)."""
    if db.mode() == "demo":
        return {"specialists": [], "suggestions_ar": [], "unassigned": 0}
    cfg = settings.get("workflow")
    team = team_load()
    backlog = window_backlog()
    amap = assignments_map()
    unassigned = [k for k, b in backlog.items() if b["open"] and
                  (k not in amap or amap[k]["status"] != "open")]
    failed = db.rows("SELECT agent, tafsir, window, output_tail, last_error FROM task_steps"
                     " WHERE status IN ('failed','interrupted') AND finished_at BETWEEN ? AND ?",
                     (day_start, day_end))
    retrying = db.scalar("SELECT COUNT(*) FROM task_steps WHERE status='queued' AND attempt>1") or 0
    dec = db.row("SELECT SUM(decision='needs_edit') ne, COUNT(*) n FROM decisions"
                 " WHERE created_at BETWEEN ? AND ?", (day_start, day_end)) or {}
    lessons = sum(1 for r in db.rows("SELECT teach FROM decisions WHERE created_at BETWEEN ? AND ?",
                                     (day_start, day_end))
                  if (db.loads(r["teach"], {}) or {}).get("teach"))
    from . import publish  # local import: publish reads decisions through pipeline
    pub = publish.status()
    s: list[str] = []
    n_spec = len(team)
    if n_spec < cfg["min_specialists"]:
        s.append(f"عدد المتخصصين {n_spec} من {cfg['min_specialists']} المطلوبين: أضف دور «المتخصص»"
                 " لمستخدمين آخرين (المستخدمون ← تعديل) — يمكن للمستخدم أن يحمل أكثر من دور.")
    if unassigned:
        s.append(f"{len(unassigned)} نافذة بلا متخصص مسند: أضف متخصصًا أو فعّل الإسناد التلقائي.")
    for p in team:
        if p["open_windows"] and p["oldest_days"] >= 2:
            s.append(f"{p['name']}: {p['open_moves']} حركة في {p['open_windows']} نافذة، أقدمها منذ"
                     f" {p['oldest_days']:.0f} يوم — ذكّره أو أعد إسناد بعضها.")
    if n_spec >= 2:
        loads = sorted(team, key=lambda p: p["open_moves"])
        lo, hi = loads[0], loads[-1]
        if hi["open_moves"] >= 10 and hi["open_moves"] > 2 * max(1, lo["open_moves"]):
            s.append(f"العمل غير متوازن: {hi['name']} عليه {hi['open_moves']} حركة و{lo['name']}"
                     f" {lo['open_moves']} — انقل بعض النوافذ من صفحة المراجعة.")
    if failed:
        tails = " ".join((f.get("output_tail") or "") + " " + (f.get("last_error") or "")
                         for f in failed)
        s.append(f"{len(failed)} خطوة فشلت اليوم بعد إعادة المحاولة: افتح المهمة واقرأ السبب ثم"
                 " «إعادة الخطوات الفاشلة».")
        if re.search(r"repeating itself|repeated itself", tails):
            s.append("نموذج دار في حلقة على نافذة واحدة على الأقل: راجع حزمتها أو قسّمها.")
        if "timed out" in tails:
            s.append("انتهت مهلة بعض الخطوات: تحقق من الماك (الذاكرة، num_ctx) أو ارفع المهلة.")
    if retrying:
        s.append(f"{retrying} خطوة بانتظار إعادة تلقائية.")
    ctx = _context_pressure(day_start, day_end)
    if ctx:
        s.append(f"أطول طلب اليوم {ctx['max_prompt']} رمزًا من سياق {ctx['context']}: ارفع num_ctx"
                 " على الماك حتى لا تُقتطع الحزم.")
    if dec.get("ne"):
        s.append(f"{dec['ne']} حركة «تحتاج تعديلاً»: حدّث قواعد المنهج ثم أعد تشغيل نوافذها.")
    if lessons:
        s.append(f"أُضيف {lessons} درسًا لبنك الأمثلة اليوم: شغّل «بملف المفسر» على آيات جديدة لقياس"
                 " الأثر.")
    if pub.get("pending"):
        s.append(f"{pub['pending']} وحدة معتمدة لم تُنشر بعد: راجعها وانشرها من صفحة النشر.")
    return {"specialists": team, "unassigned": len(unassigned),
            "open_windows": sum(1 for b in backlog.values() if b["open"]),
            "open_moves": sum(b["open"] for b in backlog.values()),
            "publish": pub, "suggestions_ar": s}


def _context_pressure(start: float, end: float) -> dict | None:
    rows = db.rows("SELECT model, result FROM task_steps WHERE finished_at BETWEEN ? AND ?"
                   " AND agent IN ('classifier','method_specialist','verifier')", (start, end))
    worst = None
    for r in rows:
        res = db.loads(r.get("result"), {}) or {}
        mp = int(res.get("max_prompt") or 0)
        if mp and (worst is None or mp > worst[0]):
            worst = (mp, r.get("model"))
    if not worst:
        return None
    ps = pipeline.ollama_ps()
    ctx = next((m.get("context_length") for m in ps.get("models") or []
                if m.get("name") == worst[1]), None)
    if ctx and worst[0] >= 0.98 * ctx:
        return {"max_prompt": worst[0], "context": ctx, "model": worst[1]}
    return None


# ------------------------------------------------------------------ retries

ENGINE_DOWN_RE = re.compile(r"network error|connection refused|no route to host|"
                            r"name or service not known|temporary failure in name resolution|"
                            r"remote end closed connection", re.I)
MODEL_AGENTS = ("classifier", "method_specialist", "verifier")


def plan_failure(step: dict, code: int, output: str, *, killed_externally: bool,
                 engine_up: bool | None) -> dict:
    """What happens to a step that just failed.

    action: requeue  — killed by a restart: run again now, no attempt used (≤3 times)
            wait     — the model engine is offline: try again in a minute, no attempt used
            retry    — run again later (attempt + 1)
            final    — give up; it is counted as failed and e-mailed
    """
    cfg = settings.get("workflow")
    now = db.now()
    if killed_externally and int(step.get("interruptions") or 0) < 3:
        return {"action": "requeue", "not_before": now, "attempt": step.get("attempt") or 1,
                "reason": "interrupted by a console restart"}
    if not cfg["auto_retry"]:
        return {"action": "final"}
    if (step.get("agent") in MODEL_AGENTS and engine_up is False
            and ENGINE_DOWN_RE.search(output or "")):
        return {"action": "wait", "not_before": now + 60, "attempt": step.get("attempt") or 1,
                "reason": "model engine offline — waiting"}
    attempt = int(step.get("attempt") or 1)
    if attempt <= cfg["retry_max"]:
        delay = cfg["retry_first_min"] if attempt == 1 else cfg["retry_second_min"]
        return {"action": "retry", "not_before": now + 60 * delay, "attempt": attempt + 1,
                "reason": f"automatic retry {attempt}/{cfg['retry_max']} in {delay} min"}
    return {"action": "final"}


# ------------------------------------------------------------------ alerts

ALERT_BATCH_S = 600
ENGINE_ALERT_S = 3600


def failure_alerts(force: bool = False) -> dict | None:
    """E-mail final failures (batched: at most one message every 10 minutes)."""
    cfg = settings.get("workflow")
    if not cfg["failure_alerts"]:
        return None
    since = db.meta_get("alerts_since")
    if since is None:  # never alert history from before the feature existed
        db.meta_set("alerts_since", db.now())
        return None
    now = db.now()
    last = float(db.meta_get("alert_last_at", 0) or 0)
    if not force and now - last < ALERT_BATCH_S:
        return None
    rows = db.rows("SELECT s.*, t.title_ar FROM task_steps s JOIN tasks t ON t.id=s.task_id"
                   " WHERE s.status IN ('failed','interrupted') AND s.alerted_at IS NULL"
                   " AND s.finished_at >= ? AND s.finished_at <= ? ORDER BY s.finished_at",
                   (since, now - 20))
    if not rows:
        return None
    people = users_with_roles(cfg["alert_roles"])
    mail = mailtpl.failure_alert(rows)
    sent = failed = 0
    for p in people:
        try:
            mailer.send_mail(p["email"], mail)
            sent += 1
        except mailer.MailError:
            failed += 1
    ids = [r["id"] for r in rows]
    db.execute(f"UPDATE task_steps SET alerted_at=? WHERE id IN ({','.join('?' * len(ids))})",
               (now, *ids))
    db.meta_set("alert_last_at", now)
    db.audit("alert.failures", detail={"steps": len(rows), "sent": sent, "failed": failed})
    return {"steps": len(rows), "sent": sent, "failed": failed}


def engine_alert(waiting: int) -> dict | None:
    """The model engine is offline while steps wait for it (at most once an hour)."""
    cfg = settings.get("workflow")
    if not cfg["failure_alerts"]:
        return None
    now = db.now()
    if now - float(db.meta_get("engine_alert_at", 0) or 0) < ENGINE_ALERT_S:
        return None
    people = users_with_roles(cfg["alert_roles"])
    mail = mailtpl.engine_alert(waiting, settings.get("llm")["base_url"])
    sent = 0
    for p in people:
        try:
            mailer.send_mail(p["email"], mail)
            sent += 1
        except mailer.MailError:
            pass
    db.meta_set("engine_alert_at", now)
    db.audit("alert.engine_offline", detail={"waiting": waiting, "sent": sent})
    return {"sent": sent, "waiting": waiting}


def status() -> dict[str, Any]:
    """For the dashboard and settings page."""
    team = team_load() if db.mode() != "demo" else []
    cfg = settings.get("workflow")
    return {"specialists": team, "min_specialists": cfg["min_specialists"],
            "enough_specialists": len(team) >= cfg["min_specialists"],
            "retrying": db.scalar("SELECT COUNT(*) FROM task_steps WHERE status='queued'"
                                  " AND attempt>1") or 0,
            "reminders_day": db.meta_get("reminders_day"),
            "alert_last_at": db.meta_get("alert_last_at"),
            "server_time": time.time()}
