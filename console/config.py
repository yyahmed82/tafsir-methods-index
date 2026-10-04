"""Paths and constants shared by the console modules."""

from __future__ import annotations

import os
from pathlib import Path

CONSOLE_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(os.environ.get("MIRQAH_REPO_ROOT") or CONSOLE_DIR.parent).resolve()
VAR_DIR = Path(os.environ.get("MIRQAH_VAR_DIR") or (CONSOLE_DIR / "var")).resolve()
STATIC_DIR = CONSOLE_DIR / "static"
I18N_DIR = STATIC_DIR / "i18n"

SESSION_COOKIE = "mirqah_session"
CSRF_HEADER = "x-mirqah"  # custom header required on every state-changing request

TAFSIRS = ("al_tabari", "ibn_kathir", "al_baghawi", "al_saadi")
TAFSIR_NAMES_AR = {
    "al_tabari": "الطبري",
    "ibn_kathir": "ابن كثير",
    "al_baghawi": "البغوي",
    "al_saadi": "السعدي",
}

PERMISSIONS = (
    "view_dashboard",
    "view_tasks",
    "run_tasks",
    "manage_tasks",
    "run_bulk",
    "view_reports",
    "generate_reports",
    "review_units",
    "view_audit",
    "manage_users",
    "manage_roles",
    "manage_settings",
    "manage_languages",
)

# Methods that the verifier always routes to the specialist (src/v2_verify.py
# FORCE_SPECIALIST_METHODS + M_RAY). Used only by the read-only chair preview.
FORCE_SPECIALIST = {"M_ISRAILIYYAT", "M_NUZUL", "M_QIRAAT", "M_RAY"}
COMMITTEE_THRESHOLD = 85


def ensure_dirs() -> None:
    VAR_DIR.mkdir(parents=True, exist_ok=True)
    (VAR_DIR / "outbox").mkdir(parents=True, exist_ok=True)
