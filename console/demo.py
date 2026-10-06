"""Demo mode: a simulated year of committee work, for showing the console at scale.

Everything lives in its own database (``var/demo.db``); the live database, the
repo's ``data/`` and the pipeline are never touched. The simulation uses the real
window ids and ayah numbers of the configured surah so the progress grid looks
like the real one, but:

* no tafsir text is stored or shown — the review screen says so;
* every tag, score, route, decision and timing is generated (fixed random seed),
  so the numbers are a rehearsal, not results. The UI shows a banner on every page;
* the people are invented personas marked "(تجريبي)", never team members;
* demo mode is read-only: the API refuses writes while a viewer is in it.

``tick()`` keeps one simulated task moving in real time so the dashboard shows an
agent at work.
"""

from __future__ import annotations

import datetime as dt
import random
import threading
import time
import zlib
from typing import Any

from . import config, db, pipeline, settings

PEOPLE = [
    (1, "demo.admin@mirqah.invalid", "مشرف النظام (تجريبي)", "super_admin"),
    (2, "demo.sara@mirqah.invalid", "سارة القحطاني (تجريبي)", "committee_operator"),
    (3, "demo.fahad@mirqah.invalid", "فهد العتيبي (تجريبي)", "committee_operator"),
    (4, "demo.abdullah@mirqah.invalid", "د. عبدالله الشهري (تجريبي)", "specialist"),
    (5, "demo.noura@mirqah.invalid", "د. نورة الحربي (تجريبي)", "specialist"),
    (6, "demo.reem@mirqah.invalid", "ريم الزهراني (تجريبي)", "viewer"),
]
OPERATORS, SPECIALISTS, ADMIN = (2, 3), (4, 5), 1

METHODS = [("M_SAHABA", 20), ("M_TABIIN", 18), ("M_LUGHA", 16), ("M_RAY", 12), ("M_QURAN", 10),
           ("M_SUNNAH", 10), ("M_NUZUL", 5), ("M_QIRAAT", 4), ("M_SIRA", 3), ("M_ISRAILIYYAT", 2)]
CERTAINTY = [("explicit", 35), ("strong", 35), ("weak", 20), ("insufficient", 10)]
REASONS = ("written_abstain", "force_specialist", "agent_disagree", "unclear_bounds", "weak_evidence")
REASON_AR = {
    "written_abstain": "امتناع بسبب مكتوب من المصنّف.",
    "force_specialist": "إحالة الفاحص — منهج يُحال دائماً إلى المتخصص.",
    "agent_disagree": "اختلف الوكيلان في المنهج الأساسي.",
    "unclear_bounds": "حدود الشاهد غير متقاطعة بين الوكيلين.",
    "weak_evidence": "الدليل غير كافٍ للترشيح (درجة أقل من ٨٥ أو يقين ضعيف).",
}
NOTES = [
    "حدود الشاهد أوسع من الجملة المقصودة؛ تُقصر على الأجزاء الوسطى.",
    "المنهج الأقرب لغوي لا أثري؛ يُعاد للمصنّف.",
    "الآية الواردة داخل الحديث ليست تفسيراً للقرآن بالقرآن (القاعدة ١).",
    "نسبة القول إلى التابعي غير ظاهرة في الموضع المحدد.",
    "يقين المصنّف أعلى مما يسنده الدليل.",
    "الوحدة تجمع منهجين؛ تُقسم إلى وحدتين.",
]
FAIL = [("BAD_JSON", 40), ("UNKNOWN_SPAN_ID", 25), ("TIMEOUT", 20), ("CONNECTION_REFUSED", 15)]
FORCE = {"M_ISRAILIYYAT", "M_NUZUL", "M_QIRAAT", "M_RAY"}
WORKDAYS = (6, 0, 1, 2, 3)  # Sun–Thu (Python: Mon=0)

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"tick": 0.0, "avail": None}


# ------------------------------------------------------------------ status & mode

def available() -> bool:
    """True once a simulation has been generated."""
    try:
        path = db.demo_path()
    except RuntimeError:
        return False
    if not path.is_file():
        return False
    key = (path.stat().st_mtime, path.stat().st_size)
    hit = _STATE.get("avail")
    if hit and hit[0] == key:
        return hit[1]
    try:
        with db.use("demo"):
            ok = bool(db.scalar("SELECT value FROM demo_meta WHERE key='seeded_at'"))
    except Exception:  # noqa: BLE001 - half-written or foreign file
        ok = False
    _STATE["avail"] = (key, ok)
    return ok


def mode_for(request, user: dict) -> str:
    """live | demo for this request: the viewer's choice (cookie), guests follow Settings."""
    if not available():
        return "live"
    chosen = request.cookies.get(config.MODE_COOKIE)
    if chosen in ("live", "demo"):
        return chosen
    if user.get("is_guest"):
        return settings.get("demo")["guest_mode"]
    return "live"


def meta() -> dict:
    with db.use("demo"):
        return {r["key"]: db.loads(r["value"], r["value"]) for r in db.rows("SELECT * FROM demo_meta")}


def status() -> dict:
    if not available():
        return {"available": False}
    m = meta()
    with db.use("demo"):
        counts = {t: db.scalar(f"SELECT COUNT(*) FROM {t}") for t in
                  ("tasks", "task_steps", "decisions", "reports", "audit", "demo_units")}
    return {"available": True, "seeded_at": m.get("seeded_at"), "start": m.get("start"),
            "end": m.get("end"), "months": m.get("months"), "counts": counts}


def clear() -> None:
    path = db.demo_path()
    with _LOCK:
        for p in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
            try:
                p.unlink()
            except FileNotFoundError:
                pass
    _STATE["avail"] = None


# ------------------------------------------------------------------ synthetic units

def _pick(rng: random.Random, weighted: list[tuple[str, int]]) -> str:
    return rng.choices([k for k, _ in weighted], weights=[w for _, w in weighted])[0]


def unit_moves(tafsir: str, window: str, span_count: int) -> list[dict]:
    """Deterministic simulated committee rows for one window (no text)."""
    rng = random.Random(zlib.crc32(f"{tafsir}/{window}".encode()))
    n = max(3, min(14, round(span_count / 5) + rng.randint(-1, 2)))
    span_count = max(span_count, n * 2)
    cuts = sorted(rng.sample(range(1, span_count), n - 1)) if n > 1 else []
    bounds = list(zip([0] + cuts, cuts + [span_count]))
    out = []
    for i, (a, b) in enumerate(bounds, 1):
        primary = _pick(rng, METHODS)
        certainty = _pick(rng, CERTAINTY)
        lo, hi = {"explicit": (86, 98), "strong": (76, 93), "weak": (55, 82),
                  "insufficient": (30, 60)}[certainty]
        score = rng.randint(lo, hi)
        agree = rng.random() < 0.78
        reviewer = primary if agree else _pick(rng, [m for m in METHODS if m[0] != primary])
        r_score = max(30, min(98, score + rng.randint(-9, 6)))
        flags = ["mixed_or_overlap_spans"] if rng.random() < 0.06 else []
        if certainty == "insufficient":
            reason = "written_abstain"
        elif primary in FORCE:
            reason = "force_specialist"
        elif not agree:
            reason = "agent_disagree"
        elif flags:
            reason = "unclear_bounds"
        elif score < config.COMMITTEE_THRESHOLD or certainty == "weak":
            reason = "weak_evidence"
        else:
            reason = None
        route = "auto_candidate" if reason is None else "specialist"
        mid = f"m{i:02d}"
        out.append({
            "key": f"P-{mid}", "move_id": mid,
            "span_ids": [f"s{k + 1:03d}" for k in range(a, b)],
            "primary": primary, "secondary": [], "certainty": certainty,
            "score": {"total": score}, "route": route, "flags": flags, "text": None,
            "rationale_ar": None, "reason_code": None,
            "committee": {
                "proposer_move_id": mid, "reviewer_move_id": mid if rng.random() < 0.95 else None,
                "primary_proposer": primary, "primary_reviewer": reviewer,
                "score_proposer": score, "score_reviewer": r_score,
                "route_proposer": "auto_candidate" if score >= 85 and certainty in ("explicit", "strong") else "specialist",
                "route_reviewer": "auto_candidate" if r_score >= 85 else "specialist",
                "committee_route": route, "outcome": "candidate" if route == "auto_candidate" else "abstain",
                "abstention_reasons": [reason] if reason else [],
                "abstention_ar": REASON_AR.get(reason, "") if reason else "",
            },
            "committee_abstention_ar": REASON_AR.get(reason, "") if reason else "",
        })
    return out


def _summary(moves: list[dict]) -> dict:
    reasons = {k: 0 for k in REASONS}
    for m in moves:
        for r in m["committee"]["abstention_reasons"]:
            reasons[r] += 1
    auto = sum(1 for m in moves if m["route"] == "auto_candidate")
    return {"move_count": len(moves), "auto_candidate": auto, "specialist": len(moves) - auto,
            "flag_count": sum(1 for m in moves if m["flags"]), "by_abstention_reason": reasons,
            "caption": "محاكاة — أعداد توجيه وليست دقة"}


# ------------------------------------------------------------------ reads used in demo mode

def gates(as_of: float | None = None) -> dict:
    m = meta()
    t = as_of or time.time()
    return {"phase0_merged": t >= float(m.get("phase0_at") or 9e18),
            "phase0_note": "(محاكاة)", "sample_reviewed": t >= float(m.get("sample_reviewed_at") or 9e18),
            "sample_max_windows": 12}


def _units(as_of: float | None = None) -> list[dict]:
    rows = db.rows("SELECT * FROM demo_units ORDER BY ayah_number, tafsir, window")
    t = as_of or time.time()
    for r in rows:
        for k in ("classifier_at", "verifier_at", "committee_at"):
            if r[k] is not None and r[k] > t:
                r[k] = None
    return rows


def progress(as_of: float | None = None) -> dict:
    m = pipeline.models()
    units = _units(as_of)
    per = []
    keys = ("windows", "classifier", "verifier", "both", "auto_candidate", "specialist", "moves",
            "flags", "committee", "committee_candidates", "committee_specialist")
    totals = {k: 0 for k in keys}
    for t in config.TAFSIRS:
        us = [u for u in units if u["tafsir"] == t]
        done = [u for u in us if u["committee_at"]]
        cl = [u for u in us if u["classifier_at"]]
        row = {"tafsir": t, "name_ar": config.TAFSIR_NAMES_AR[t], "windows": len(us),
               "ayat": len({u["ayah"] for u in us}),
               "classifier": len(cl), "verifier": sum(1 for u in us if u["verifier_at"]),
               "both": sum(1 for u in us if u["classifier_at"] and u["verifier_at"]),
               "auto_candidate": sum(u["auto_candidate"] for u in cl),
               "specialist": sum(u["specialist"] for u in cl),
               "moves": sum(u["moves"] for u in cl), "flags": sum(u["flags"] for u in cl),
               "committee": len(done),
               "committee_candidates": sum(u["auto_candidate"] for u in done),
               "committee_specialist": sum(u["specialist"] for u in done)}
        per.append(row)
        for k in keys:
            totals[k] += row[k]
    return {"models": m, "tafsirs": per, "totals": totals,
            "caption_ar": "محاكاة — أعداد توجيه وليست دقة", "simulated": True}


def ayah_matrix() -> dict:
    units = _units()
    cols = [{"tafsir": t, "name_ar": config.TAFSIR_NAMES_AR[t]} for t in config.TAFSIRS]
    ayat: dict[int, dict] = {}
    for t in config.TAFSIRS:
        groups: dict[int, list[dict]] = {}
        for u in units:
            if u["tafsir"] == t:
                groups.setdefault(u["ayah_number"], []).append(u)
        for n, us in groups.items():
            nc = sum(1 for u in us if u["classifier_at"])
            nb = sum(1 for u in us if u["classifier_at"] and u["verifier_at"])
            ncm = sum(1 for u in us if u["committee_at"])
            st = ("committee" if ncm == len(us) else "both" if nb == len(us) else
                  "classifier" if nc == len(us) else "partial" if nc or nb else "none")
            ayat.setdefault(n, {"ayah_number": n, "cells": {}})["cells"][t] = {
                "status": st, "windows": len(us), "classified": nc, "both": nb, "committee": ncm}
    return {"columns": cols, "rows": [ayat[k] for k in sorted(ayat)], "simulated": True}


def review_units(tafsir: str | None = None) -> list[dict]:
    out = []
    for u in _units():
        if not u["committee_at"] or (tafsir and u["tafsir"] != tafsir):
            continue
        out.append({"tafsir": u["tafsir"], "name_ar": config.TAFSIR_NAMES_AR[u["tafsir"]],
                    "window": u["window"], "ayah": u["ayah"], "ayah_number": u["ayah_number"],
                    "moves": u["moves"], "auto_candidate": u["auto_candidate"],
                    "specialist": u["specialist"], "flags": None,
                    "reasons": db.loads(u["reasons"], {}), "committee": True,
                    "annotator": "committee"})
    return out


def review_window(tafsir: str, window: str) -> dict | None:
    u = db.row("SELECT * FROM demo_units WHERE tafsir=? AND window=?", (tafsir, window))
    if u is None or not u["committee_at"]:
        return None
    moves = unit_moves(tafsir, window, u["span_count"])
    dec = db.rows("SELECT d.*, u.name AS user_name FROM decisions d JOIN users u ON u.id=d.user_id"
                  " WHERE tafsir=? AND window=? AND annotator='committee' ORDER BY d.id",
                  (tafsir, window))
    latest = {d["move_id"]: d for d in dec}
    for mv in moves:
        mv["decision"] = latest.get(mv["key"])
    m = pipeline.models()
    return {"tafsir": tafsir, "name_ar": config.TAFSIR_NAMES_AR[tafsir], "window": window,
            "ayah": u["ayah"], "annotator": "committee", "source_file": None,
            "source_sha256": None, "packet_sha256": None, "summary": _summary(moves),
            "models": {"proposer": {"tag": m["classifier"]}, "reviewer": {"tag": m["verifier"]}},
            "is_committee": True, "moves": moves, "chair": None, "history": dec,
            "simulated": True}


def probe() -> dict:
    llm = settings.get("llm")
    names = sorted({llm["classifier_model"], llm["verifier_model"], "qwen2.5:7b"})
    return {"base_url": "simulated", "runtime": llm["runtime"], "reachable": True,
            "simulated": True, "error": None, "version": "simulated",
            "models": [{"name": n, "size": None, "family": None, "parameter_size": None,
                        "quantization": None} for n in names],
            "classifier_model": llm["classifier_model"], "verifier_model": llm["verifier_model"],
            "classifier_installed": True, "verifier_installed": True}


def ollama_ps() -> dict:
    """Simulated GET /api/ps: both committee models held in memory for five minutes."""
    llm = settings.get("llm")
    now = time.time()
    sizes = {llm["classifier_model"]: 9.7e9, llm["verifier_model"]: 8.9e9}
    return {"available": True, "error": None, "simulated": True, "at": now,
            "models": [{"name": n, "size": int(b), "size_vram": int(b), "context_length": 16384,
                        "expires_at": now + 240, "parameter_size": None, "quantization": None}
                       for n, b in sizes.items()]}


def sim_usage(chars: int, moves: int) -> dict:
    """Plausible token counts for a simulated model step (deterministic, no RNG draw)."""
    tin = int(chars / 2.4) + 2600
    return {"model_calls": 1, "tokens_in": tin, "tokens_out": 90 * max(1, moves) + 60,
            "max_prompt": tin}


# ------------------------------------------------------------------ the simulated year

class _Sim:
    def __init__(self, months: int, now: float, seed: int):
        self.rng = random.Random(seed)
        self.now = now
        self.tz = _tz()
        end_day = dt.datetime.fromtimestamp(now, self.tz).date()
        self.start_day = end_day - dt.timedelta(days=int(round(months * 30.44)))
        self.days = [self.start_day + dt.timedelta(days=i)
                     for i in range((end_day - self.start_day).days + 1)]
        self.models = pipeline.models()
        self.steps: list[tuple] = []
        self.tasks: list[tuple] = []
        self.audit: list[tuple] = []
        self.decisions: list[tuple] = []
        self.task_id = 0
        self.step_id = 0
        self.units: dict[tuple[str, str], dict] = {}
        self.moves: dict[tuple[str, str], list[dict]] = {}
        self.pending_failed: list[tuple] = []      # (task_id, agent, tafsir, window, model)
        self.review_queue: list[tuple] = []        # (ready_at, tafsir, window, key, route)
        self.revisit: list[tuple] = []             # (due_at, tafsir, window, key, route)
        self.decided: set[tuple] = set()

    # time helpers
    def at(self, day: dt.date, hour: float) -> float:
        h = int(hour)
        m = int((hour - h) * 60)
        return dt.datetime.combine(day, dt.time(h, m), tzinfo=self.tz).timestamp()

    def frac(self, day: dt.date) -> float:
        return (day - self.start_day).days / max(1, len(self.days) - 1)

    def log(self, at: float, user: int | None, action: str, target: str | None = None,
            detail: Any = None, ip: str | None = None) -> None:
        if at <= self.now:
            self.audit.append((at, user, action, target, db.dumps(detail) if detail is not None else None,
                               ip))

    def ip(self, user: int) -> str:
        return f"37.104.{20 + user}.{10 + (user * 37) % 200}"

    # one task: steps run one after another from `start`
    def run_task(self, kind: str, title: str, by: int, start: float, pairs: list[tuple[str, str]],
                 agents: tuple[str, ...], model_cls: str, fail_rate: float, scope: str,
                 ayat: str = "", retry_of: int | None = None, outage_at: float | None = None) -> float:
        self.task_id += 1
        tid = self.task_id
        t = start
        done = failed = 0
        rows = []
        seq = 0
        for tafsir, window in pairs:
            u = self.units[(tafsir, window)]
            for agent in agents:
                model = (model_cls if agent == "classifier" else
                         self.models["verifier"] if agent == "verifier" else None)
                if agent == "packet_check":
                    dur = self.rng.uniform(0.6, 2.2)
                elif agent == "chair":
                    dur = self.rng.uniform(0.8, 2.6)
                else:
                    rate = (95 if "7b" in (model or "") else 55) if agent == "classifier" else 68
                    dur = (u["chars"] / rate + 8) * self.rng.uniform(0.8, 1.25)
                ok = True
                code = None
                if agent in ("classifier", "verifier"):
                    if outage_at and t >= outage_at:
                        ok, code, dur = False, "CONNECTION_REFUSED", self.rng.uniform(0.2, 0.8)
                    elif self.rng.random() < fail_rate:
                        ok, code = False, _pick(self.rng, FAIL)
                        if code == "TIMEOUT":
                            dur = 600
                elif agent == "chair":
                    prev_bad = any(r[2] in ("classifier", "verifier") and r[3] == tafsir and r[4] == window
                                   and r[7] == "failed" for r in rows)
                    if prev_bad:
                        ok, code = False, "AGENT_MISSING"
                fin = t + dur
                if fin > self.now:
                    break
                summ = _summary(self.moves[(tafsir, window)])
                if ok and agent in ("classifier", "verifier"):
                    result = {"moves": summ["move_count"], "auto_candidate": summ["auto_candidate"],
                              "specialist": summ["specialist"], "flags": summ["flag_count"],
                              **sim_usage(u["chars"], summ["move_count"])}
                    u[f"{agent}_at"] = u[f"{agent}_at"] or fin
                    tail = (f"verifier: moves={summ['move_count']} auto={summ['auto_candidate']} "
                            f"specialist={summ['specialist']} flags={summ['flag_count']}")
                elif ok and agent == "chair":
                    result = {"moves": summ["move_count"], "auto_candidate": summ["auto_candidate"],
                              "specialist": summ["specialist"],
                              "reasons": summ["by_abstention_reason"]}
                    first = u["committee_at"] is None
                    u["committee_at"] = u["committee_at"] or fin
                    if first:
                        for mv in self.moves[(tafsir, window)]:
                            self.review_queue.append((fin, tafsir, window, mv["key"], mv["route"]))
                    tail = (f"processed 1 window(s), {summ['move_count']} move(s): "
                            f"{summ['auto_candidate']} auto_candidate, {summ['specialist']} specialist")
                elif ok:
                    result = {"spans": u["span_count"]}
                    tail = f"spans: {u['span_count']} (dry run, no model)"
                else:
                    result = {"reason_code": code}
                    tail = f'{{"reason_code": "{code}"}}  (simulated failure)'
                    self.pending_failed.append((tid, agent, tafsir, window, model))
                self.step_id += 1
                rows.append((self.step_id, tid, agent, tafsir, window, model,
                             seq, "done" if ok else "failed", t, fin, int(dur * 1000),
                             0 if ok else 1, db.dumps(result), tail))
                seq += 1
                done += ok
                failed += not ok
                t = fin + self.rng.uniform(0.5, 3)
        if not rows:
            self.task_id -= 1
            return start
        for r in rows:
            self.steps.append((r[0], r[1], r[6], r[2], r[3], r[4], r[5], r[7], r[8], r[9], r[10],
                               r[11], r[12], r[13]))
        params = {"kind": kind, "scope": scope, "ayat": ayat, "tafsirs": sorted({p[0] for p in pairs}),
                  "skip_done": False, "bulk": scope == "ayat" and len(pairs) > 12,
                  "models": {"classifier": model_cls, "verifier": self.models["verifier"]},
                  "simulated": True}
        if retry_of:
            params["retry_of"] = retry_of
        self.tasks.append((tid, kind, title, db.dumps(params), "failed" if failed else "done", by,
                           start - 2, start, t, len(rows), done, failed, 0))
        self.log(start - 2, by, "task.retry" if retry_of else "task.create", str(tid),
                 {"kind": kind, "scope": scope, "ayat": ayat, "steps": len(rows)}, self.ip(by))
        return t

    def ayat_label(self, pairs: list[tuple[str, str]]) -> str:
        nums = sorted({self.units[p]["ayah_number"] for p in pairs})
        return f"{nums[0]}-{nums[-1]}" if len(nums) > 1 else str(nums[0])

    def specialist_session(self, day: dt.date, who: int) -> None:
        start = self.at(day, self.rng.uniform(9.5, 20))
        if start > self.now:
            return
        k = self.rng.randint(2, 7)
        t = start
        picked = 0
        due = [r for r in self.revisit if r[0] <= t]
        for r in due[: max(1, k // 4)]:
            self.revisit.remove(r)
            self._decide(t, who, r[1], r[2], r[3], r[4], second=True)
            t += self.rng.uniform(60, 240)
            picked += 1
        while picked < k and self.review_queue and self.review_queue[0][0] <= t:
            _ready, tafsir, window, key, route = self.review_queue.pop(0)
            if (tafsir, window, key) in self.decided:
                continue
            self._decide(t, who, tafsir, window, key, route)
            t += self.rng.uniform(60, 300)
            picked += 1
            if t > self.now:
                break
        if picked:
            self.log(start - 30, who, "auth.login", None, None, self.ip(who))

    def _decide(self, t: float, who: int, tafsir: str, window: str, key: str, route: str,
                second: bool = False) -> None:
        if t > self.now:
            return
        r = self.rng.random()
        if second:
            d = "approve" if r < 0.72 else "reject" if r < 0.84 else "needs_edit"
        elif route == "auto_candidate":
            d = "approve" if r < 0.82 else "needs_edit" if r < 0.95 else "reject"
        else:
            d = "approve" if r < 0.55 else "needs_edit" if r < 0.85 else "reject"
        note = "" if d == "approve" else self.rng.choice(NOTES)
        self.decisions.append((tafsir, window, "committee", key, d, 1, note, who, t))
        self.decided.add((tafsir, window, key))
        self.log(t, who, "review.decision", f"{tafsir}/{window}/{key}",
                 {"decision": d, "annotator": "committee"}, self.ip(who))
        if d == "needs_edit" and not second:
            self.revisit.append((t + self.rng.uniform(7, 21) * 86400, tafsir, window, key, route))


def _tz():
    name = settings.get("general")["timezone"]
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:  # pragma: no cover
        return dt.timezone(dt.timedelta(hours=3))


def seed(months: int = 12, now: float | None = None, rng_seed: int = 2026) -> dict:
    """(Re)build the simulation: ``months`` of activity ending ``now``."""
    months = max(3, min(18, int(months)))
    now = now or time.time()
    clear()
    db.init_demo()
    with db.use("live"):
        sim = _Sim(months, now, rng_seed)
        wins = {t: pipeline.windows(t) for t in config.TAFSIRS}
        sample = int(settings.get("general")["sample_ayah"].split(":")[1])
    for t, ws in wins.items():
        for w in ws:
            sim.units[(t, w["window"])] = {"tafsir": t, "window": w["window"], "ayah": w["ayah"],
                                           "ayah_number": w["ayah_number"], "span_count": w["span_count"],
                                           "chars": max(400, w["chars"]), "classifier_at": None,
                                           "verifier_at": None, "committee_at": None}
            sim.moves[(t, w["window"])] = unit_moves(t, w["window"], w["span_count"])
    if not sim.units:
        raise RuntimeError("no windows under data/ — nothing to simulate")
    rng = sim.rng
    days = sim.days
    first = days[0]
    t0 = sim.at(first, 10)
    # people and setup
    for pid, email, name, role in PEOPLE:
        sim.log(t0 + pid * 300, ADMIN if pid != ADMIN else None, "user.create", email, {"role": role})
    for i, sec in enumerate(("general", "llm", "smtp", "security", "reports")):
        sim.log(t0 + 3600 + i * 120, ADMIN, "settings.update", sec, {"changed": ["(simulated)"]})
    order = sorted(config.TAFSIRS, key=lambda t: len(wins[t]))  # shortest tafsir first
    bulk_queue = [(t, w["window"]) for t in order for w in wins[t]
                  if w["ayah_number"] != sample]
    sample_pairs = [(t, w["window"]) for t in config.TAFSIRS for w in wins[t] if w["ayah_number"] == sample]
    rerun_queue: list[tuple[str, str]] = []
    phase0_at = sample_reviewed_at = None
    outage_days = set(rng.sample(range(len(days)), k=min(4, len(days) // 60 or 1)))
    for i, day in enumerate(days):
        f = sim.frac(day)
        work = day.weekday() in WORKDAYS
        op = rng.choice(OPERATORS)
        if f < 0.05:
            if work and rng.random() < 0.6:
                pairs = rng.sample(sorted(sim.units), k=min(12, len(sim.units)))
                sim.run_task("dryrun", "فحص الحزم دون نموذج — عيّنة عشوائية · {} نافذة".format(len(pairs)),
                             op, sim.at(day, rng.uniform(10, 18)), pairs, ("packet_check",),
                             sim.models["classifier"], 0, "ayat")
        elif f < 0.13:
            if phase0_at is None:
                phase0_at = sim.at(day, 11)
                sim.log(phase0_at, ADMIN, "settings.update", "gates", {"changed": ["phase0_merged"]})
            if work and (rng.random() < 0.55 or not any(u["committee_at"] for u in sim.units.values())):
                model = "qwen2.5:7b" if f < 0.09 else sim.models["classifier"]
                start = sim.at(day, rng.uniform(9, 19))
                sim.run_task("committee", f"تشغيل اللجنة (المصنّف ثم المدقّق ثم الرئيس) — العيّنة · "
                             f"{len(sample_pairs)} نافذة", op, start, sample_pairs,
                             ("classifier", "verifier", "chair"), model,
                             0.12 if "7b" in model else 0.04, "sample")
        else:
            if sample_reviewed_at is None:
                sample_reviewed_at = sim.at(day, 9)
                sim.log(sample_reviewed_at, ADMIN, "settings.update", "gates",
                        {"changed": ["sample_reviewed"]})
            if work and f < 0.55 and bulk_queue:
                for _ in range(rng.choice((1, 1, 2))):
                    if not bulk_queue:
                        break
                    taf = bulk_queue[0][0]
                    k = rng.randint(3, 8)
                    pairs = [p for p in bulk_queue if p[0] == taf][:k]
                    for p in pairs:
                        bulk_queue.remove(p)
                    outage = sim.at(day, rng.uniform(12, 22)) if i in outage_days else None
                    sim.run_task("committee", f"تشغيل اللجنة (المصنّف ثم المدقّق ثم الرئيس) — آيات "
                                 f"({sim.ayat_label(pairs)}) · {len(pairs)} نافذة", op,
                                 sim.at(day, rng.uniform(8.5, 21)), pairs,
                                 ("classifier", "verifier", "chair"), sim.models["classifier"], 0.035,
                                 "ayat", sim.ayat_label(pairs), outage_at=outage)
            elif work and 0.58 <= f < 0.70:
                if not rerun_queue:
                    rerun_queue = [p for p in sorted(sim.units, key=lambda p: (p[0], sim.units[p]["ayah_number"]))
                                   if sim.units[p]["committee_at"]]
                pairs = rerun_queue[:rng.randint(4, 9)]
                del rerun_queue[:len(pairs)]
                if pairs:
                    sim.run_task("verifier", f"إعادة المدقّق بعد تحديث تعليماته (v3) — آيات "
                                 f"({sim.ayat_label(pairs)}) · {len(pairs)} نافذة", op,
                                 sim.at(day, rng.uniform(9, 20)), pairs, ("verifier", "chair"),
                                 sim.models["classifier"], 0.02, "ayat", sim.ayat_label(pairs))
            elif work and f >= 0.70 and rng.random() < 0.4:
                done_units = sorted(p for p in sim.units if sim.units[p]["committee_at"])
                pairs = rng.sample(done_units, k=min(rng.randint(2, 5), len(done_units)))
                sim.run_task("committee", f"تحقق دوري: المصنّف ثم المدقّق ثم الرئيس — آيات "
                             f"({sim.ayat_label(pairs)}) · {len(pairs)} نافذة", op,
                             sim.at(day, rng.uniform(9, 20)), pairs, ("classifier", "verifier", "chair"),
                             sim.models["classifier"], 0.03, "ayat", sim.ayat_label(pairs))
            elif work and rng.random() < 0.18:
                pairs = rng.sample(sorted(p for p in sim.units if sim.units[p]["committee_at"]) or sample_pairs,
                                   k=min(3, len(sim.units)))
                sim.run_task("chair", f"رئيس اللجنة على المخرجات الموجودة — فحص دوري · {len(pairs)} نافذة",
                             op, sim.at(day, rng.uniform(9, 20)), pairs, ("chair",),
                             sim.models["classifier"], 0, "ayat")
        # failed steps are retried on the next working day
        if work and sim.pending_failed and rng.random() < 0.8:
            failed, sim.pending_failed = sim.pending_failed[:], []
            by_task: dict[int, list] = {}
            for x in failed:
                by_task.setdefault(x[0], []).append(x)
            for tid, items in list(by_task.items())[:3]:
                pairs = sorted({(x[2], x[3]) for x in items})
                agents = tuple(a for a in ("classifier", "verifier", "chair")
                               if any(x[1] == a for x in items) or a == "chair")
                sim.run_task("committee", f"إعادة الفاشل من المهمة #{tid}", op,
                             sim.at(day, rng.uniform(9, 12)), pairs, agents, sim.models["classifier"],
                             0.03, "ayat", retry_of=tid)
        if work:
            for who in SPECIALISTS:
                if rng.random() < 0.8:
                    sim.specialist_session(day, who)
            sim.log(sim.at(day, rng.uniform(8, 9.5)), op, "auth.login", None, None, sim.ip(op))
        if i % 45 == 20:
            sim.log(sim.at(day, 12), ADMIN, "llm.test", None, {"ok": True})
    # write everything
    with db.use("demo"):
        with db.connect() as con:
            con.executemany("INSERT INTO users(id,email,name,role_key,active,created_at) VALUES (?,?,?,?,1,?)",
                            [(p[0], p[1], p[2], p[3], t0) for p in PEOPLE])
            con.executemany("INSERT INTO tasks(id,kind,title_ar,params,status,created_by,created_at,"
                            "started_at,finished_at,total_steps,done_steps,failed_steps,skipped_steps)"
                            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", sim.tasks)
            db.backfill_task_chain(con)  # retries grouped under their original task
            con.executemany("INSERT INTO task_steps(id,task_id,seq,agent,tafsir,window,model,status,"
                            "started_at,finished_at,duration_ms,exit_code,result,output_tail)"
                            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", sim.steps)
            con.executemany("INSERT INTO decisions(tafsir,window,annotator,move_id,decision,"
                            "compared_with_source,note,user_id,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                            sorted(sim.decisions, key=lambda r: r[8]))
            units = []
            for (t, w), u in sim.units.items():
                s = _summary(sim.moves[(t, w)])
                units.append((t, w, u["ayah"], u["ayah_number"], u["span_count"], u["chars"],
                              s["move_count"], s["auto_candidate"], s["specialist"], s["flag_count"],
                              db.dumps(s["by_abstention_reason"]), u["classifier_at"], u["verifier_at"],
                              u["committee_at"]))
            con.executemany("INSERT INTO demo_units VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", units)
            m = {"seeded_at": now, "start": sim.at(days[0], 0), "end": now, "months": months,
                 "phase0_at": phase0_at or 9e18, "sample_reviewed_at": sample_reviewed_at or 9e18,
                 "seed": rng_seed}
            con.executemany("INSERT INTO demo_meta(key,value) VALUES (?,?)",
                            [(k, db.dumps(v)) for k, v in m.items()])
        # daily reports (built from the simulated rows, as of each day's end)
        from . import runner
        reports = []
        for day in days[:-1]:
            iso = day.isoformat()
            end = sim.at(day, 23.5)
            content = runner.build_report(iso, as_of=end)
            content["generated_at"] = end
            content["simulated"] = True
            reports.append((iso, end, None, db.dumps(content), end + 60))
            sim.log(end, None, "report.generate", iso)
            sim.log(end + 60, None, "report.mail", iso, {"sent": 3, "failed": 0})
        with db.connect() as con:
            con.executemany("INSERT INTO reports(day,generated_at,generated_by,content,mailed_at)"
                            " VALUES (?,?,?,?,?)", reports)
            con.executemany("INSERT INTO audit(at,user_id,action,target,detail,ip) VALUES (?,?,?,?,?,?)",
                            sorted(sim.audit, key=lambda r: r[0]))
    _STATE["avail"] = None
    return status()


# ------------------------------------------------------------------ live heartbeat

def tick() -> None:
    """Advance one simulated task in real time (called on demo-mode reads)."""
    now = time.time()
    if now - _STATE["tick"] < 2.5 or not available():
        return
    with _LOCK:
        _STATE["tick"] = now
        with db.use("demo"):
            _tick(now)


def _tick(now: float) -> None:
    rng = random.Random(int(now // 3))
    task = db.row("SELECT * FROM tasks WHERE status='running' ORDER BY id DESC LIMIT 1")
    if task is None:
        last = db.scalar("SELECT MAX(finished_at) FROM tasks") or 0
        if now - last < 20:
            return
        units = db.rows("SELECT * FROM demo_units WHERE committee_at IS NOT NULL ORDER BY tafsir, ayah_number")
        if not units:
            return
        n = int(db.scalar("SELECT value FROM demo_meta WHERE key='live_cursor'") or 0)
        pairs = [units[(n + k) % len(units)] for k in range(2)]
        db.execute("INSERT INTO demo_meta(key,value) VALUES ('live_cursor',?) ON CONFLICT(key)"
                   " DO UPDATE SET value=excluded.value", (str(n + 2),))
        m = pipeline.models()
        params = {"kind": "committee", "scope": "ayat", "ayat": "", "skip_done": False, "bulk": False,
                  "tafsirs": sorted({u["tafsir"] for u in pairs}), "simulated": True, "live": True,
                  "models": {"classifier": m["classifier"], "verifier": m["verifier"]}}
        title = "تحقق دوري: المصنّف ثم المدقّق ثم الرئيس · {} نافذة (محاكاة حيّة)".format(len(pairs))
        with db.connect() as con:
            cur = con.execute("INSERT INTO tasks(kind,title_ar,params,status,created_by,created_at,"
                              "started_at,total_steps) VALUES (?,?,?,?,?,?,?,?)",
                              ("committee", title, db.dumps(params), "running", rng.choice(OPERATORS),
                               now, now, len(pairs) * 3))
            tid = int(cur.lastrowid)
            seq = 0
            for u in pairs:
                for agent in ("classifier", "verifier", "chair"):
                    model = m["classifier"] if agent == "classifier" else m["verifier"] if agent == "verifier" else None
                    con.execute("INSERT INTO task_steps(task_id,seq,agent,tafsir,window,model,status,started_at)"
                                " VALUES (?,?,?,?,?,?,?,?)", (tid, seq, agent, u["tafsir"], u["window"], model,
                                                             "running" if seq == 0 else "queued",
                                                             now if seq == 0 else None))
                    seq += 1
        return
    step = db.row("SELECT * FROM task_steps WHERE task_id=? AND status='running' ORDER BY seq LIMIT 1",
                  (task["id"],))
    if step is None:
        nxt = db.row("SELECT * FROM task_steps WHERE task_id=? AND status='queued' ORDER BY seq LIMIT 1",
                     (task["id"],))
        if nxt is None:
            db.execute("UPDATE tasks SET status='done', finished_at=? WHERE id=?", (now, task["id"]))
        else:
            db.execute("UPDATE task_steps SET status='running', started_at=? WHERE id=?", (now, nxt["id"]))
        return
    srng = random.Random(step["id"])
    need = {"classifier": srng.uniform(35, 70), "verifier": srng.uniform(25, 55)}.get(step["agent"], 3)
    if now - (step["started_at"] or now) < need:
        return
    u = db.row("SELECT * FROM demo_units WHERE tafsir=? AND window=?", (step["tafsir"], step["window"]))
    s = _summary(unit_moves(step["tafsir"], step["window"], u["span_count"])) if u else _summary([])
    if step["agent"] == "chair":
        result = {"moves": s["move_count"], "auto_candidate": s["auto_candidate"],
                  "specialist": s["specialist"], "reasons": s["by_abstention_reason"]}
    else:
        result = {"moves": s["move_count"], "auto_candidate": s["auto_candidate"],
                  "specialist": s["specialist"], "flags": s["flag_count"],
                  **sim_usage(u["chars"] if u else 4000, s["move_count"])}
    with db.connect() as con:
        con.execute("UPDATE task_steps SET status='done', finished_at=?, duration_ms=?, exit_code=0,"
                    " result=?, output_tail=? WHERE id=?",
                    (now, int((now - step["started_at"]) * 1000), db.dumps(result),
                     "(simulated live step)", step["id"]))
        con.execute("UPDATE tasks SET done_steps=done_steps+1 WHERE id=?", (task["id"],))
        nxt = con.execute("SELECT id FROM task_steps WHERE task_id=? AND status='queued' ORDER BY seq LIMIT 1",
                          (task["id"],)).fetchone()
        if nxt:
            con.execute("UPDATE task_steps SET status='running', started_at=? WHERE id=?", (now, nxt[0]))
        else:
            con.execute("UPDATE tasks SET status='done', finished_at=? WHERE id=?", (now, task["id"]))
