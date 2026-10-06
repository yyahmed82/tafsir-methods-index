"""Publishing: the last step, done by super admins in the console (no git merge).

A publication is a versioned snapshot of every unit a specialist approved, re-checked
against the pinned source text, written to ``VAR_DIR/published/v<N>.json``. One
version is live; the public site reads it from ``/public/v1/published.json``.
Rolling back is making an older version live again. Nothing here approves anything
and nothing writes under data/.

Public snapshots never carry reviewer names or e-mails: who approved and who
published stays in the console (history and audit log).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import config, db, pipeline, settings

KIND = "mirqah-published"
SCHEMA_VERSION = 1


def snap_dir() -> Path:
    d = config.VAR_DIR / "published"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ------------------------------------------------------------------ candidate

def _latest_decisions() -> list[dict]:
    latest: dict[tuple, dict] = {}
    for d in db.rows("SELECT * FROM decisions ORDER BY id"):
        latest[(d["tafsir"], d["window"], d["annotator"], d["move_id"])] = d
    return list(latest.values())


def _variant_of(annotator: str) -> str | None:
    return annotator.split("__", 1)[1] if "__" in annotator else None


def _source(tafsir: str, rel: str | None) -> tuple[str | None, str | None]:
    """(text, sha256) of the pinned source file, read from the run workspace."""
    if not rel:
        return None, None
    p = (config.work_root() / rel).resolve()
    roots = (pipeline.data_root(), (config.work_root() / "data").resolve())
    if not any(p.is_relative_to(r) for r in roots) or not p.is_file():
        return None, None
    raw = p.read_bytes()
    return raw.decode("utf-8"), hashlib.sha256(raw).hexdigest()


def candidate() -> dict[str, Any]:
    """Every unit whose latest decision is approve and was compared with the source."""
    units: list[dict] = []
    failed: list[dict] = []
    sources: dict[str, tuple[str | None, str | None]] = {}
    payloads: dict[tuple, tuple] = {}
    for d in _latest_decisions():
        if d["decision"] != "approve" or not d.get("compared_with_source"):
            continue
        key = (d["tafsir"], d["annotator"], d["window"])
        if key not in payloads:
            v = pipeline.load_verified(d["tafsir"], d["annotator"], d["window"])
            com = (pipeline.load_committee(d["tafsir"], d["window"], _variant_of(d["annotator"]))
                   if d["annotator"].startswith("committee") else None)
            payloads[key] = (v, {k: mv for k, mv, _c in pipeline.unit_rows(v, com)} if v else {})
        v, rows = payloads[key]
        uid = f"{d['tafsir']}/{d['window']}/{d['move_id']}"
        mv = rows.get(d["move_id"])
        if v is None or mv is None:
            failed.append({"id": uid, "reason": "unit_missing"})
            continue
        rel = v.get("source_file")
        if rel not in sources:
            sources[rel] = _source(d["tafsir"], rel)
        text, sha = sources[rel]
        start, end = mv.get("start"), mv.get("end")
        if text is None:
            failed.append({"id": uid, "reason": "source_missing"})
            continue
        if sha != v.get("source_sha256"):
            failed.append({"id": uid, "reason": "source_changed"})
            continue
        if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end:
            failed.append({"id": uid, "reason": "bad_bounds"})
            continue
        if not pipeline.span_text_ok(text, pipeline.load_window(d["tafsir"], d["window"]),
                                     mv.get("span_ids") or [], mv.get("text")):
            failed.append({"id": uid, "reason": "text_mismatch"})
            continue
        units.append({
            "id": uid, "tafsir": d["tafsir"],
            "tafsir_name_ar": config.TAFSIR_NAMES_AR.get(d["tafsir"], d["tafsir"]),
            "window": d["window"], "ayah": v.get("ayah"), "move": d["move_id"],
            "primary": mv.get("primary"), "secondary": mv.get("secondary") or [],
            "certainty": mv.get("certainty"), "content_tags": mv.get("content_tags") or [],
            "span_ids": mv.get("span_ids") or [],
            "evidence_span_ids": mv.get("evidence_span_ids") or [],
            "references": mv.get("references") or {},
            "start": start, "end": end, "text": mv.get("text"), "slice": text[start:end],
            "source_file": rel, "source_sha256": sha,
            "approved_at": d["created_at"], "decision_id": d["id"],
            "_annotator": d["annotator"],  # console-only, stripped from the public file
        })
    # the same span set with the same method approved in both blind versions → one unit
    seen: dict[tuple, dict] = {}
    duplicates = 0
    for u in sorted(units, key=lambda u: u["approved_at"]):
        k = (u["tafsir"], u["window"], u["primary"], tuple(sorted(u["span_ids"])))
        if k in seen:
            duplicates += 1
            continue
        seen[k] = u
    kept = sorted(seen.values(), key=lambda u: (u["tafsir"], u["window"], u["start"], u["id"]))
    overlaps = []
    by_window: dict[tuple, list[dict]] = {}
    for u in kept:
        by_window.setdefault((u["tafsir"], u["window"]), []).append(u)
    for (t, w), us in by_window.items():
        for i, a in enumerate(us):
            for b in us[i + 1:]:
                if a["primary"] != b["primary"] and set(a["span_ids"]) & set(b["span_ids"]):
                    overlaps.append({"tafsir": t, "window": w, "a": a["id"], "b": b["id"],
                                     "a_primary": a["primary"], "b_primary": b["primary"]})
    return {"units": kept, "failed": failed, "duplicates": duplicates, "overlaps": overlaps,
            "windows": _windows_for(kept, sources)}


def _windows_for(units: list[dict], sources: dict) -> list[dict]:
    """The pinned passage of every window that carries an approved unit, so the public
    reader can show each approved unit inside the mufassir's own text. The text is the
    source slice (never a model's output); the verse is taken from the head of the
    commentary when the mufassir quotes it."""
    out: list[dict] = []
    seen: set[tuple] = set()
    for u in units:
        key = (u["tafsir"], u["window"])
        if key in seen:
            continue
        seen.add(key)
        w = pipeline.load_window(u["tafsir"], u["window"]) or {}
        text, sha = sources.get(u.get("source_file"), (None, None))
        start, end = int(w.get("window_start") or 0), int(w.get("window_end") or 0)
        if text is None or sha != u.get("source_sha256") or not 0 <= start < end <= len(text):
            continue
        ayah = str(w.get("ayah") or u.get("ayah") or "")
        surah = int(w.get("surah") or (ayah.split(":")[0] if ":" in ayah else 0) or 0)
        n = int(w.get("ayah_number") or (ayah.split(":")[1] if ":" in ayah else 0) or 0)
        parts = pipeline.window_parts(u["tafsir"], n) if n else []
        out.append({
            "tafsir": u["tafsir"], "tafsir_name_ar": u["tafsir_name_ar"], "window": u["window"],
            "ayah": ayah, "surah": surah, "surah_name_ar": pipeline.surah_name(surah),
            "ayah_number": n, "part": (parts.index(u["window"]) + 1) if u["window"] in parts else 1,
            "parts": len(parts) or 1, "ayah_text": pipeline.ayah_text(u["tafsir"], n) if n else None,
            "source_file": u.get("source_file"), "source_sha256": sha,
            "window_start": start, "window_end": end, "text": text[start:end],
        })
    out.sort(key=lambda w: (w["tafsir"], w["ayah_number"], w["part"]))
    return out


def _method_names() -> dict[str, str]:
    try:
        from . import learning
        return learning.method_names()
    except Exception:  # pragma: no cover - names are a convenience for the reader
        return {}


def _counts(units: list[dict]) -> dict:
    by_t: dict[str, int] = {}
    by_m: dict[str, int] = {}
    for u in units:
        by_t[u["tafsir"]] = by_t.get(u["tafsir"], 0) + 1
        by_m[str(u["primary"])] = by_m.get(str(u["primary"]), 0) + 1
    return {"units": len(units), "by_tafsir": by_t, "by_method": by_m,
            "windows": len({(u["tafsir"], u["window"]) for u in units})}


def _public(units: list[dict]) -> list[dict]:
    return [{k: v for k, v in u.items() if not k.startswith("_") and k != "decision_id"}
            for u in units]


# ------------------------------------------------------------------ versions

def _row(r: dict | None) -> dict | None:
    if r is None:
        return None
    r = dict(r)
    r["live"] = bool(r["live"])
    r["summary"] = db.loads(r.get("summary"), {}) or {}
    return r


def live() -> dict | None:
    return _row(db.row("SELECT p.*, u.name AS created_by_name FROM publications p LEFT JOIN"
                       " users u ON u.id=p.created_by WHERE p.live=1"))


def history(limit: int = 30) -> list[dict]:
    return [_row(r) for r in db.rows(
        "SELECT p.*, u.name AS created_by_name, m.name AS made_live_by_name FROM publications p"
        " LEFT JOIN users u ON u.id=p.created_by LEFT JOIN users m ON m.id=p.made_live_by"
        " ORDER BY p.version DESC LIMIT ?", (limit,))]


def load(version: int) -> dict | None:
    r = db.row("SELECT path FROM publications WHERE version=?", (version,))
    if r is None:
        return None
    p = snap_dir() / Path(r["path"]).name
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def live_bytes() -> tuple[bytes, dict] | None:
    meta = live()
    if meta is None:
        return None
    p = snap_dir() / Path(meta["path"]).name
    if not p.is_file():
        return None
    return p.read_bytes(), meta


def preview() -> dict:
    """What publishing now would change on mirqah.app, and the checks behind it."""
    cand = candidate()
    cur = live()
    cur_units = {u["id"]: u for u in ((load(cur["version"]) or {}).get("units") or [])} if cur else {}
    new_units = {u["id"]: u for u in _public(cand["units"])}
    fields = ("primary", "certainty", "start", "end", "text", "secondary")
    added = [u for k, u in new_units.items() if k not in cur_units]
    removed = [u for k, u in cur_units.items() if k not in new_units]
    changed = [new_units[k] for k in new_units.keys() & cur_units.keys()
               if any(new_units[k].get(f) != cur_units[k].get(f) for f in fields)]
    backlog_windows = 0
    try:
        from . import workflow
        backlog_windows = sum(1 for b in workflow.window_backlog().values() if b["open"])
    except Exception:  # pragma: no cover - informative only
        pass
    return {"live": cur, "counts": _counts(cand["units"]),
            "added": added, "removed": removed, "changed": changed,
            "failed": cand["failed"], "duplicates": cand["duplicates"],
            "overlaps": cand["overlaps"], "windows_waiting": backlog_windows,
            "changes": len(added) + len(removed) + len(changed),
            "public_url": public_url()}


def public_url() -> str:
    base = (settings.get("general").get("console_url") or "").rstrip("/")
    return f"{base}/public/v1/published.json" if base else "/public/v1/published.json"


def publish(user: dict, note: str = "") -> dict:
    cand = candidate()
    pv = preview()
    if pv["live"] is not None and pv["changes"] == 0:
        raise ValueError("nothing_to_publish")
    if not cand["units"] and pv["live"] is None:
        raise ValueError("nothing_to_publish")
    version = int(db.scalar("SELECT COALESCE(MAX(version), 0) FROM publications") or 0) + 1
    gen = settings.get("general")
    counts = _counts(cand["units"])
    body = {"kind": KIND, "schema": SCHEMA_VERSION, "version": version,
            "published_at": db.now(), "project": gen["project_name"], "team": gen["team_name"],
            "note": note.strip()[:500], "counts": counts,
            "notice_ar": "وحدات اعتمدها متخصص بشري وروجعت مقابل النص المثبّت؛ أعداد وليست دقة.",
            "units": _public(cand["units"]), "windows": cand["windows"],
            "methods_ar": _method_names()}
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    sha = hashlib.sha256(raw).hexdigest()
    name = f"v{version:04d}.json"
    tmp = snap_dir() / (name + ".tmp")
    tmp.write_bytes(raw)
    tmp.replace(snap_dir() / name)
    summary = {"counts": counts, "added": len(pv["added"]), "removed": len(pv["removed"]),
               "changed": len(pv["changed"]), "failed": len(cand["failed"])}
    with db.connect() as con:
        con.execute("UPDATE publications SET live=0")
        con.execute("INSERT INTO publications(version, created_at, created_by, note, units, sha256,"
                    " path, live, made_live_at, made_live_by, summary) VALUES (?,?,?,?,?,?,?,1,?,?,?)",
                    (version, body["published_at"], user["id"], body["note"], counts["units"], sha,
                     name, body["published_at"], user["id"], db.dumps(summary)))
    db.audit("publish.version", user_id=user["id"], target=f"v{version}",
             detail={**summary, "sha256": sha})
    return live() or {}


def make_live(version: int, user: dict) -> dict:
    r = db.row("SELECT * FROM publications WHERE version=?", (version,))
    if r is None or not (snap_dir() / Path(r["path"]).name).is_file():
        raise ValueError("version_not_found")
    with db.connect() as con:
        con.execute("UPDATE publications SET live=0")
        con.execute("UPDATE publications SET live=1, made_live_at=?, made_live_by=? WHERE version=?",
                    (db.now(), user["id"], version))
    db.audit("publish.make_live", user_id=user["id"], target=f"v{version}")
    return live() or {}


def status() -> dict:
    """Small summary for the chair report and the dashboard."""
    if db.mode() == "demo":
        return {"live": None, "pending": 0}
    try:
        pv = preview()
    except Exception:  # pragma: no cover - never break a report over publishing
        return {"live": None, "pending": 0}
    cur = pv["live"]
    return {"live": {"version": cur["version"], "units": cur["units"],
                     "made_live_at": cur["made_live_at"]} if cur else None,
            "pending": pv["changes"], "approved": pv["counts"]["units"],
            "failed": len(pv["failed"])}
