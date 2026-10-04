"""Read-only view of the repo pipeline: windows, moves, verified files, progress.

Nothing here writes under ``data/``. Writing happens only in ``runner.py`` and
only by calling ``src/run_window.py`` (the pinned pipeline).
"""

from __future__ import annotations

import json
import re
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import config, settings

if str(config.REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(config.REPO_ROOT / "src"))

try:  # single source of truth for annotator folder names
    from classify_api import model_slug  # type: ignore  # noqa: E402
except Exception:  # pragma: no cover - fallback keeps the console usable
    def model_slug(model: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", (model or "model").strip()).strip("_").lower()
        return slug or "model"

WINDOW_RE = re.compile(r"^\d{1,3}_\d{1,3}(?:_p\d{2})?$")
_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_LOCK = threading.Lock()


def data_root() -> Path:
    return (config.REPO_ROOT / settings.get("general")["data_root"]).resolve()


def base_dir(tafsir: str) -> Path:
    if tafsir not in config.TAFSIRS:
        raise ValueError(f"unknown tafsir {tafsir!r}")
    return data_root() / tafsir


def _read_json(path: Path) -> Any:
    return json.loads(path.read_bytes().decode("utf-8"))


def windows(tafsir: str) -> list[dict]:
    """[{window, ayah, ayah_number, span_count}] sorted by ayah then part."""
    d = base_dir(tafsir) / "windows"
    if not d.is_dir():
        return []
    key = f"win:{d}"
    mtime = d.stat().st_mtime
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and hit[0] == mtime:
            return hit[1]
    out = []
    for p in d.glob("*.json"):
        if not WINDOW_RE.match(p.stem):
            continue
        w = _read_json(p)
        out.append({
            "window": p.stem,
            "ayah": w.get("ayah"),
            "ayah_number": int(w.get("ayah_number") or p.stem.split("_")[1]),
            "span_count": int(w.get("span_count") or len(w.get("spans") or [])),
        })
    out.sort(key=lambda x: (x["ayah_number"], x["window"]))
    with _CACHE_LOCK:
        _CACHE[key] = (mtime, out)
    return out


def window_ids(tafsir: str) -> set[str]:
    return {w["window"] for w in windows(tafsir)}


def verified_path(tafsir: str, annotator: str, window: str) -> Path:
    return base_dir(tafsir) / "verified" / annotator / f"{window}.json"


def moves_path(tafsir: str, annotator: str, window: str) -> Path:
    return base_dir(tafsir) / "moves" / annotator / f"{window}.json"


def load_verified(tafsir: str, annotator: str, window: str) -> dict | None:
    p = verified_path(tafsir, annotator, window)
    return _read_json(p) if p.is_file() else None


def models() -> dict[str, str]:
    llm = settings.get("llm")
    return {
        "classifier": llm["classifier_model"],
        "verifier": llm["verifier_model"],
        "classifier_slug": model_slug(llm["classifier_model"]),
        "verifier_slug": model_slug(llm["verifier_model"]),
    }


def _summaries(tafsir: str, annotator: str) -> dict[str, dict]:
    d = base_dir(tafsir) / "verified" / annotator
    out: dict[str, dict] = {}
    if d.is_dir():
        for p in d.glob("*.json"):
            try:
                out[p.stem] = _read_json(p).get("summary") or {}
            except (OSError, ValueError):
                out[p.stem] = {"error": "unreadable"}
    return out


def progress() -> dict:
    """Coverage per tafsir for the configured classifier / verifier models."""
    m = models()
    per_tafsir = []
    totals = {"windows": 0, "classifier": 0, "verifier": 0, "both": 0,
              "auto_candidate": 0, "specialist": 0, "moves": 0, "flags": 0}
    for t in config.TAFSIRS:
        wins = windows(t)
        ids = {w["window"] for w in wins}
        c = {k: v for k, v in _summaries(t, m["classifier_slug"]).items() if k in ids}
        v = {k: v for k, v in _summaries(t, m["verifier_slug"]).items() if k in ids}
        auto = sum(int(s.get("auto_candidate") or 0) for s in c.values())
        spec = sum(int(s.get("specialist") or 0) for s in c.values())
        mv = sum(int(s.get("move_count") or 0) for s in c.values())
        fl = sum(int(s.get("flag_count") or 0) for s in c.values())
        row = {
            "tafsir": t, "name_ar": config.TAFSIR_NAMES_AR[t], "windows": len(ids),
            "ayat": len({w["ayah"] for w in wins}),
            "classifier": len(c), "verifier": len(v), "both": len(set(c) & set(v)),
            "auto_candidate": auto, "specialist": spec, "moves": mv, "flags": fl,
        }
        per_tafsir.append(row)
        for k in totals:
            totals[k] += row[k] if k != "windows" else len(ids)
    return {"models": m, "tafsirs": per_tafsir, "totals": totals,
            "caption_ar": "أعداد توجيه وليست دقة"}


def ayah_matrix() -> dict:
    """Status per ayah × tafsir: none | partial | classifier | both."""
    m = models()
    cols = []
    ayat: dict[int, dict] = {}
    for t in config.TAFSIRS:
        cols.append({"tafsir": t, "name_ar": config.TAFSIR_NAMES_AR[t]})
        c = set(_summaries(t, m["classifier_slug"]))
        v = set(_summaries(t, m["verifier_slug"]))
        groups: dict[int, list[str]] = {}
        for w in windows(t):
            groups.setdefault(w["ayah_number"], []).append(w["window"])
        for n, ws in groups.items():
            nc = sum(1 for w in ws if w in c)
            nb = sum(1 for w in ws if w in c and w in v)
            if nb == len(ws):
                st = "both"
            elif nc == len(ws):
                st = "classifier"
            elif nc or nb:
                st = "partial"
            else:
                st = "none"
            ayat.setdefault(n, {"ayah_number": n, "cells": {}})["cells"][t] = {
                "status": st, "windows": len(ws), "classified": nc, "both": nb}
    return {"columns": cols, "rows": [ayat[k] for k in sorted(ayat)]}


def resolve_scope(scope: str, ayat: str, tafsirs: list[str]) -> list[tuple[str, str]]:
    """Return [(tafsir, window)] for a scope: sample | ayat | surah."""
    gen = settings.get("general")
    tafsirs = [t for t in tafsirs if t in config.TAFSIRS] or list(config.TAFSIRS)
    wanted: set[int] | None
    if scope == "sample":
        wanted = {int(gen["sample_ayah"].split(":")[1])}
    elif scope == "ayat":
        wanted = parse_ayat(ayat)
        if not wanted:
            raise ValueError("ayat_empty")
    elif scope == "surah":
        wanted = None
    else:
        raise ValueError("scope_unknown")
    out = []
    for t in tafsirs:
        for w in windows(t):
            if wanted is None or w["ayah_number"] in wanted:
                out.append((t, w["window"]))
    return out


def parse_ayat(text: str) -> set[int]:
    """'1-5, 35, 40' → {1,2,3,4,5,35,40}; ignores anything else."""
    out: set[int] = set()
    for part in re.split(r"[,\s،]+", text or ""):
        if not part:
            continue
        m = re.fullmatch(r"(\d{1,3})\s*[-–]\s*(\d{1,3})", part)
        if m:
            a, b = sorted((int(m.group(1)), int(m.group(2))))
            if b - a <= 300:
                out.update(range(a, b + 1))
        elif part.isdigit():
            out.add(int(part))
    return {n for n in out if 1 <= n <= 300}


# ------------------------------------------------------------ chair preview

def _overlap(a: list[str], b: list[str]) -> bool:
    return bool(set(a or []) & set(b or []))


def chair_preview(tafsir: str, window: str) -> dict | None:
    """Read-only committee decision per classifier move (docs/COMMITTEE_PLAN.md §ج).

    Candidate only if: both routes auto_candidate, same primary, overlapping
    spans, classifier score ≥ 85, no flags on either side. Otherwise one
    reason code, first that applies. Writes nothing.
    """
    m = models()
    cv = load_verified(tafsir, m["classifier_slug"], window)
    vv = load_verified(tafsir, m["verifier_slug"], window)
    if cv is None:
        return None
    out = []
    for mv in cv.get("moves") or []:
        match = None
        if vv:
            for other in vv.get("moves") or []:
                if _overlap(mv.get("span_ids"), other.get("span_ids")):
                    match = other
                    break
        score = int((mv.get("score") or {}).get("total") or 0)
        reason = None
        if mv.get("certainty") == "insufficient" or not mv.get("primary"):
            reason = "written_abstain"
        elif mv.get("primary") in config.FORCE_SPECIALIST:
            reason = "force_specialist"
        elif vv is None:
            reason = "agent_missing"
        elif match is None:
            reason = "unclear_bounds"
        elif match.get("primary") != mv.get("primary"):
            reason = "agent_disagree"
        elif (mv.get("route") != "auto_candidate" or match.get("route") != "auto_candidate"
              or score < config.COMMITTEE_THRESHOLD or mv.get("flags") or match.get("flags")):
            reason = "weak_evidence"
        out.append({
            "move_id": mv.get("move_id"),
            "reviewer_move_id": match.get("move_id") if match else None,
            "primary": mv.get("primary"),
            "primary_reviewer": match.get("primary") if match else None,
            "score": score,
            "route_classifier": mv.get("route"),
            "route_reviewer": match.get("route") if match else None,
            "committee_route": "auto_candidate" if reason is None else "specialist",
            "reason": reason,
        })
    return {
        "tafsir": tafsir, "window": window, "has_reviewer": vv is not None,
        "moves": out,
        "candidates": sum(1 for x in out if x["committee_route"] == "auto_candidate"),
        "specialist": sum(1 for x in out if x["committee_route"] == "specialist"),
        "note_ar": "معاينة للقراءة فقط — لا تكتب ملفات ولا تعني اعتماداً",
    }


def review_units(tafsir: str | None = None) -> list[dict]:
    """Windows that have verified output from the configured classifier."""
    m = models()
    out = []
    for t in config.TAFSIRS:
        if tafsir and t != tafsir:
            continue
        sums = _summaries(t, m["classifier_slug"])
        meta = {w["window"]: w for w in windows(t)}
        for wid, s in sums.items():
            if wid not in meta:
                continue
            out.append({"tafsir": t, "name_ar": config.TAFSIR_NAMES_AR[t], "window": wid,
                        "ayah": meta[wid]["ayah"], "ayah_number": meta[wid]["ayah_number"],
                        "moves": int(s.get("move_count") or 0),
                        "auto_candidate": int(s.get("auto_candidate") or 0),
                        "specialist": int(s.get("specialist") or 0),
                        "flags": int(s.get("flag_count") or 0),
                        "annotator": m["classifier_slug"]})
    out.sort(key=lambda x: (x["ayah_number"], x["tafsir"], x["window"]))
    return out


# ------------------------------------------------------------------ ollama

def _get_json(url: str, timeout: float = 4.0) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (configured URL)
        return json.loads(r.read().decode("utf-8"))


def probe_llm() -> dict:
    llm = settings.get("llm")
    base = llm["base_url"].rstrip("/")
    out: dict[str, Any] = {"base_url": base, "runtime": llm["runtime"], "reachable": False,
                           "models": [], "version": None, "error": None,
                           "classifier_model": llm["classifier_model"],
                           "verifier_model": llm["verifier_model"]}
    if llm["runtime"] != "ollama-local":
        out["error"] = "hosted_runtime_not_probed"
        return out
    try:
        tags = _get_json(f"{base}/api/tags")
        out["reachable"] = True
        out["models"] = sorted(
            [{"name": x.get("name"), "size": x.get("size"),
              "family": (x.get("details") or {}).get("family"),
              "parameter_size": (x.get("details") or {}).get("parameter_size"),
              "quantization": (x.get("details") or {}).get("quantization_level")}
             for x in tags.get("models") or []],
            key=lambda x: x["name"] or "")
        try:
            out["version"] = _get_json(f"{base}/api/version").get("version")
        except (urllib.error.URLError, OSError, ValueError):
            pass
    except (urllib.error.URLError, OSError, ValueError) as e:
        out["error"] = f"{type(e).__name__}: {getattr(e, 'reason', e)}"[:200]
    names = {x["name"] for x in out["models"]}
    out["classifier_installed"] = llm["classifier_model"] in names
    out["verifier_installed"] = llm["verifier_model"] in names
    return out
