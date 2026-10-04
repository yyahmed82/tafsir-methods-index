"""How reviewers teach the agents.

A reviewer's decision may carry a lesson: the error type (closed list), the
correct method, and «علّم الوكلاء بهذا». Lessons marked «teach» become the
teaching-examples bank of that tafsir (<base>/gold/examples.json, references
only). The next profile-arm run (arm B) puts the nearest examples into the
packet. Nothing here approves anything or writes tafsir text.
"""

from __future__ import annotations

import logging
from typing import Any

from . import config, db, pipeline

import ab_report  # noqa: E402  (src/ is on sys.path via pipeline)
import gold_bank  # noqa: E402
import v2_profiles  # noqa: E402

log = logging.getLogger("mirqah.console")

METHODS = gold_bank.METHODS


def error_types() -> dict[str, str]:
    return dict(gold_bank.ERROR_TYPES_AR)


def _latest_decisions(tafsir: str | None = None) -> list[dict]:
    sql = ("SELECT * FROM decisions" + (" WHERE tafsir=?" if tafsir else "") + " ORDER BY id")
    latest: dict[tuple, dict] = {}
    for d in db.rows(sql, (tafsir,) if tafsir else ()):
        d["teach"] = db.loads(d.get("teach"), {}) or {}
        latest[(d["tafsir"], d["window"], d["annotator"], d["move_id"])] = d
    return list(latest.values())


def _move_for(d: dict) -> tuple[dict | None, str | None]:
    """The reviewed move (verified payload row) and the window's ayah."""
    annotator = d["annotator"]
    _slug, variant = v2_profiles.split_annotator(annotator)
    v = pipeline.load_verified(d["tafsir"], annotator, d["window"])
    if v is None:
        return None, None
    com = (pipeline.load_committee(d["tafsir"], d["window"], variant)
           if annotator.startswith("committee") else None)
    for key, mv, _c in pipeline.unit_rows(v, com):
        if key == d["move_id"]:
            return mv, v.get("ayah")
    return None, v.get("ayah")


def rebuild_bank(tafsir: str) -> int:
    """Rewrite <base>/gold/examples.json from the latest «teach» decisions."""
    if db.mode() == "demo" or tafsir not in config.TAFSIRS:
        return 0
    examples = []
    for d in _latest_decisions(tafsir):
        lesson = d["teach"]
        if not lesson.get("teach"):
            continue
        mv, ayah = _move_for(d)
        if not mv or not mv.get("span_ids"):
            continue
        try:
            examples.append(gold_bank.make_example(
                window=d["window"], ayah=ayah or "", span_ids=mv["span_ids"],
                decision=d["decision"], proposed_primary=mv.get("primary"),
                correct_primary=lesson.get("correct_primary"),
                error_type=lesson.get("error_type"), decided_at=d["created_at"],
                decision_id=d["id"]))
        except ValueError as e:  # a bad stored value never blocks the review
            log.warning("teaching example skipped (%s): %s", d["id"], e)
    try:
        gold_bank.write_bank(pipeline.base_dir(tafsir), tafsir, examples)
    except OSError as e:
        log.warning("teaching bank not written for %s: %s", tafsir, e)
    return len(examples)


def overview(reveal_arms: bool = False) -> dict[str, Any]:
    """Profiles, lessons and (for operators) A/B counts for the learning page."""
    decisions = _latest_decisions()
    errors: dict[str, int] = {}
    lessons = 0
    per_tafsir_dec: dict[str, dict[str, int]] = {}
    for d in decisions:
        t = d["teach"]
        per = per_tafsir_dec.setdefault(d["tafsir"], {"approve": 0, "needs_edit": 0, "reject": 0,
                                                       "lessons": 0})
        per[d["decision"]] = per.get(d["decision"], 0) + 1
        if t.get("error_type"):
            errors[t["error_type"]] = errors.get(t["error_type"], 0) + 1
        if t.get("teach"):
            lessons += 1
            per["lessons"] += 1
    tafsirs = []
    for key in config.TAFSIRS:
        row: dict[str, Any] = {"tafsir": key, "name_ar": config.TAFSIR_NAMES_AR[key],
                               "decisions": per_tafsir_dec.get(key, {})}
        try:
            prof = v2_profiles.load_profile(key)
            row["profile"] = {k: prof.get(k) for k in (
                "version", "status", "status_ar", "source_ar", "card_ar", "golden_rules_ar")}
        except (OSError, ValueError) as e:
            row["profile"] = None
            row["profile_error"] = str(e)
        bank = []
        if db.mode() != "demo":
            try:
                bank = gold_bank.load_bank(pipeline.base_dir(key))
            except (OSError, ValueError):
                bank = []
        by_family: dict[str, int] = {}
        for e in bank:
            by_family[e["family"]] = by_family.get(e["family"], 0) + 1
        row["bank"] = {"count": len(bank), "by_family": by_family,
                       "corrections": sum(1 for e in bank if e["decision"] != "approve")}
        if reveal_arms and db.mode() != "demo":
            try:
                row["ab"] = ab_report.compare_base(pipeline.base_dir(key), key)
            except (OSError, ValueError) as e:
                row["ab"] = {"error": str(e)}
        tafsirs.append(row)
    return {"tafsirs": tafsirs, "lessons": lessons, "decisions": len(decisions),
            "errors": sorted(({"code": k, "label_ar": gold_bank.ERROR_TYPES_AR.get(k, k),
                               "count": v} for k, v in errors.items()),
                             key=lambda x: -x["count"]),
            "error_types": error_types(), "reveals_arms": reveal_arms,
            "caption_ar": ab_report.CAPTION_AR}
