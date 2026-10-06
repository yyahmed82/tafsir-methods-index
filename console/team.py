"""Team & agents performance: the history behind the work, not the live state
(mission control is live). Who decided what and how fast, milestones, and how the
agents worked. Every number is a count of routing, timing or decisions — not accuracy.

Who sees what: committee operators and super admins see every specialist; a specialist
sees their own numbers and the team totals; anyone else sees the team totals. Anyone
holding the Specialist role reviews blind, so the baseline / profile comparison is only
shown to people who may see which version is which."""

from __future__ import annotations

import datetime as dt
from typing import Any

from . import auth, db, pipeline, runner, settings, workflow

RANGES = (7, 30, 90, 365)
PERSON_COUNTS = (50, 100, 250, 500, 1000)
TEAM_COUNTS = (100, 250, 500, 1000, 2500, 5000)
AGENTS = ("classifier", "method_specialist", "verifier", "chair")
DECISIONS = ("approve", "needs_edit", "reject")
DAY = 86400


def scope_for(user: dict) -> str:
    """'all' for operators and super admins, 'self' for a specialist, else 'team'."""
    if "manage_tasks" in user["permissions"]:
        return "all"
    if auth.can_decide(user):
        return "self"
    return "team"


def _day_of(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, runner.tz()).date().isoformat()


def _median(xs: list[float]) -> float | None:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    mid = len(xs) // 2
    return xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2


def _taught(teach: Any) -> bool:
    t = db.loads(teach, {}) if isinstance(teach, str) else (teach or {})
    return bool(isinstance(t, dict) and t.get("teach"))


# ------------------------------------------------------------------ people

def _people(scope: str, me: dict) -> list[dict]:
    """The specialists to list: current ones plus anyone who decided (left the role)."""
    if scope == "team":
        return []
    current = {p["id"]: p for p in workflow.specialists()}
    if scope == "self":
        return [{"id": me["id"], "name": me["name"], "email": me.get("email"), "current": True}]
    for r in db.rows("SELECT DISTINCT d.user_id AS id, u.name, u.email FROM decisions d"
                     " LEFT JOIN users u ON u.id=d.user_id"):
        current.setdefault(r["id"], {**r, "former": True})
    return [{**p, "current": not p.get("former")} for p in
            sorted(current.values(), key=lambda p: p["id"])]


def _decision_rows(start: float, end: float) -> list[dict]:
    return db.rows("SELECT id, tafsir, window, annotator, move_id, decision, user_id, created_at,"
                   " teach FROM decisions WHERE created_at BETWEEN ? AND ? ORDER BY created_at",
                   (start, end))


def _milestones(people: list[dict], scope: str, start: float, end: float) -> list[dict]:
    """Achievements on the timeline: per person (first review, 50/100/… decisions, first
    lesson, desk cleared) and for the team (decision counts, published versions)."""
    out: list[dict] = []
    ids = {p["id"] for p in people}
    names = {p["id"]: p["name"] for p in people}
    allrows = db.rows("SELECT user_id, created_at, teach FROM decisions ORDER BY created_at, id")
    seen: dict[int, int] = {}
    taught: set[int] = set()
    team_n = 0
    for r in allrows:
        uid = r["user_id"]
        seen[uid] = seen.get(uid, 0) + 1
        team_n += 1
        at = r["created_at"]
        inside = start <= at <= end
        if inside and uid in ids:
            n = seen[uid]
            if n == 1:
                out.append({"at": at, "kind": "first_review", "user_id": uid, "who": names[uid]})
            elif n in PERSON_COUNTS:
                out.append({"at": at, "kind": "decisions_n", "n": n, "user_id": uid,
                            "who": names[uid]})
            if uid not in taught and _taught(r["teach"]):
                out.append({"at": at, "kind": "first_lesson", "user_id": uid, "who": names[uid]})
        if uid not in taught and _taught(r["teach"]):
            taught.add(uid)
        if inside and team_n in TEAM_COUNTS:
            out.append({"at": at, "kind": "team_decisions_n", "n": team_n})
    # desk cleared: an assignment closed while that person had nothing else open
    asg = db.rows("SELECT user_id, assigned_at, done_at FROM assignments")
    cleared_days: set[tuple[int, str]] = set()
    for a in asg:
        if not a["done_at"] or not (start <= a["done_at"] <= end) or a["user_id"] not in ids:
            continue
        busy = any(b is not a and b["user_id"] == a["user_id"] and b["assigned_at"] <= a["done_at"]
                   and (b["done_at"] is None or b["done_at"] > a["done_at"]) for b in asg)
        key = (a["user_id"], _day_of(a["done_at"]))
        if not busy and key not in cleared_days:
            cleared_days.add(key)
            out.append({"at": a["done_at"], "kind": "desk_cleared", "user_id": a["user_id"],
                        "who": names[a["user_id"]]})
    if db.mode() != "demo":
        for p in db.rows("SELECT version, units, created_at FROM publications"
                         " WHERE created_at BETWEEN ? AND ? ORDER BY version", (start, end)):
            out.append({"at": p["created_at"], "kind": "published", "version": p["version"],
                        "units": p["units"]})
    out.sort(key=lambda m: m["at"])
    return out


# ------------------------------------------------------------------ agents

def _agent_rows(start: float, end: float) -> list[dict]:
    q = ",".join("?" * len(AGENTS))
    return db.rows(f"SELECT agent, model, status, duration_ms, attempt, interruptions,"
                   f" exit_code, output_tail, last_error, finished_at, variant, result"
                   f" FROM task_steps WHERE finished_at BETWEEN ? AND ? AND agent IN ({q})",
                   (start, end, *AGENTS))


def _routing(rows: list[dict], reveal_arms: bool) -> dict:
    """What humans decided on moves the chair suggested vs moves it referred to them,
    and (operators only) baseline vs profile. Routing guidance, not accuracy."""
    latest: dict[tuple, dict] = {}
    for r in rows:
        latest[(r["tafsir"], r["window"], r["annotator"], r["move_id"])] = r
    routes: dict[tuple, dict[str, str]] = {}
    out = {"suggested": dict.fromkeys(DECISIONS, 0), "referred": dict.fromkeys(DECISIONS, 0)}
    arms = {"baseline": dict.fromkeys(DECISIONS, 0), "profile": dict.fromkeys(DECISIONS, 0)}
    for (t, w, ann, mid), r in latest.items():
        k = (t, w, ann)
        if k not in routes:
            try:
                routes[k] = pipeline.move_routes(t, w, ann)
            except Exception:  # an unreadable or moved file never breaks the page
                routes[k] = {}
        route = routes[k].get(mid)
        dec = r["decision"] if r["decision"] in DECISIONS else None
        if dec is None:
            continue
        if route:
            out["suggested" if route == "auto_candidate" else "referred"][dec] += 1
        arms["profile" if ann.endswith("__profile") else "baseline"][dec] += 1
    if reveal_arms and arms["profile"] != dict.fromkeys(DECISIONS, 0):
        out["arms"] = arms
    return out


def _agents(start: float, end: float, days: list[str]) -> dict:
    rows = _agent_rows(start, end)
    by_agent: dict[str, list[dict]] = {}
    for r in rows:
        by_agent.setdefault(r["agent"], []).append(r)
    table = []
    for a in AGENTS:
        rs = by_agent.get(a) or []
        if not rs:
            continue
        s = runner._stats(rs)  # timing, failure and token facts, not accuracy
        s["agent"] = a
        s["models"] = sorted({r["model"] for r in rs if r["model"]})
        s["retried_ok"] = sum(1 for r in rs if r["status"] == "done"
                              and ((r.get("attempt") or 1) > 1 or (r.get("interruptions") or 0)))
        causes: dict[str, int] = {}
        for r in rs:
            c = runner.failure_cause(r)
            if c:
                causes[c] = causes.get(c, 0) + 1
        s["causes"] = causes
        table.append(s)
    daily = {d: {"day": d, "by_agent": dict.fromkeys(AGENTS, 0), "failed": 0} for d in days}
    for r in rows:
        d = daily.get(_day_of(r["finished_at"]))
        if d is None:
            continue
        if r["status"] == "done":
            d["by_agent"][r["agent"]] += 1
        elif r["status"] in ("failed", "interrupted"):
            d["failed"] += 1
    done = sum(x["ok"] for x in table)
    failed = sum(x["failed"] for x in table)
    cls = next((x for x in table if x["agent"] == "classifier"), None)
    return {
        "totals": {"done": done, "failed": failed,
                   "fail_pct": round(100 * failed / (done + failed)) if done + failed else None,
                   "retried_ok": sum(x["retried_ok"] for x in table),
                   "tokens_in": sum(x["tokens_in"] for x in table),
                   "tokens_out": sum(x["tokens_out"] for x in table),
                   "classifier_median_s": cls["median_s"] if cls else None},
        "table": table, "daily": [daily[d] for d in days],
    }


# ------------------------------------------------------------------ the page

def summary(user: dict, days: int = 30, reveal_arms: bool = False) -> dict:
    days = days if days in RANGES else 30
    today = runner.local_now().date()
    day_list = [(today - dt.timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    start = runner.day_bounds(day_list[0])[0]
    end = runner.day_bounds(day_list[-1])[1]
    scope = scope_for(user)
    people = _people(scope, user)
    ids = {p["id"] for p in people}
    rows = _decision_rows(start, end)
    tstart, tend = runner.day_bounds(today.isoformat())
    live = db.mode() != "demo"
    load = {p["id"]: p for p in workflow.team_load()} if live else {}
    waiting = [r for r in workflow.desk() if r["status"] == "open" and r["open"] > 0] if live else []
    asg = db.rows("SELECT user_id, assigned_at, done_at, status, last_reminder_at FROM assignments")
    now = db.now()
    out_people = []
    for p in people:
        mine = [r for r in rows if r["user_id"] == p["id"]]
        cleared = [a["done_at"] - a["assigned_at"] for a in asg if a["user_id"] == p["id"]
                   and a["done_at"] and start <= a["done_at"] <= end]
        lp = load.get(p["id"]) or {}
        last_rem = max((a["last_reminder_at"] or 0 for a in asg if a["user_id"] == p["id"]
                        and a["status"] == "open"), default=0) or None
        last_dec = db.scalar("SELECT MAX(created_at) FROM decisions WHERE user_id=?", (p["id"],))
        med = _median(cleared)
        open_since = [r["assigned_at"] for r in waiting if r["user_id"] == p["id"]]
        out_people.append({
            "id": p["id"], "name": p["name"], "current": p.get("current", True),
            "decided": len(mine), "decided_today": sum(1 for r in mine if r["created_at"] >= tstart),
            **{k: sum(1 for r in mine if r["decision"] == k) for k in DECISIONS},
            "lessons": sum(1 for r in mine if _taught(r["teach"])),
            "open_windows": lp.get("open_windows", 0), "open_moves": lp.get("open_moves", 0),
            "oldest_days": lp.get("oldest_days", 0),
            "oldest_h": round((now - min(open_since)) / 3600, 2) if open_since else None,
            "median_clear_h": round(med / 3600, 1) if med is not None else None,
            "windows_cleared": len(cleared),
            "last_decision_at": last_dec, "last_reminder_at": last_rem,
            "remind_after": (last_rem + workflow.REMIND_COOLDOWN_S) if last_rem
            and now - last_rem < workflow.REMIND_COOLDOWN_S else None,
        })
    # team totals (always: everyone may see how the committee as a whole is doing)
    team_rows = rows
    all_cleared = [a["done_at"] - a["assigned_at"] for a in asg
                   if a["done_at"] and start <= a["done_at"] <= end]
    med_all = _median(all_cleared)
    tl = list(load.values())
    team = {
        "decided": len(team_rows),
        **{k: sum(1 for r in team_rows if r["decision"] == k) for k in DECISIONS},
        "lessons": sum(1 for r in team_rows if _taught(r["teach"])),
        "open_windows": sum(x["open_windows"] for x in tl),
        "open_moves": sum(x["open_moves"] for x in tl),
        "oldest_days": max((x["oldest_days"] for x in tl), default=0),
        "oldest_h": round((now - min(r["assigned_at"] for r in waiting)) / 3600, 2)
        if waiting else None,
        "median_clear_h": round(med_all / 3600, 1) if med_all is not None else None,
        "specialists": len(workflow.specialists()),
        "min_specialists": settings.get("workflow")["min_specialists"],
        "active": len({r["user_id"] for r in team_rows}),
    }
    daily = {d: {"day": d, "by_person": {}, **dict.fromkeys(DECISIONS, 0), "total": 0}
             for d in day_list}
    for r in team_rows:
        d = daily.get(_day_of(r["created_at"]))
        if d is None:
            continue
        if scope == "self" and r["user_id"] != user["id"]:
            continue
        d["total"] += 1
        if r["decision"] in DECISIONS:
            d[r["decision"]] += 1
        if r["user_id"] in ids:
            k = str(r["user_id"])
            d["by_person"][k] = d["by_person"].get(k, 0) + 1
    return {
        "range": {"days": days, "start": start, "end": end, "from": day_list[0],
                  "to": day_list[-1], "options": list(RANGES)},
        "scope": scope, "simulated": db.mode() == "demo",
        "team": team, "people": out_people,
        "daily": [daily[d] for d in day_list],
        "milestones": _milestones(people, scope, start, end),
        "routing": _routing(team_rows if scope != "self" else
                            [r for r in team_rows if r["user_id"] == user["id"]], reveal_arms),
        "agents": _agents(start, end, day_list),
        "remind_cooldown_s": workflow.REMIND_COOLDOWN_S,
    }
