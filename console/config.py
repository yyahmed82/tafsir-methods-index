"""Paths and constants shared by the console modules."""

from __future__ import annotations

import os
from pathlib import Path

CONSOLE_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(os.environ.get("MIRQAH_REPO_ROOT") or CONSOLE_DIR.parent).resolve()
# Where agent runs read data/ and write moves/, verified/, committee/. On the server the
# release folder is read-only, so MIRQAH_WORK_ROOT points at a writable copy that
# mirqah-deploy keeps in step with each release (outputs are never deleted by a deploy).
_WORK = os.environ.get("MIRQAH_WORK_ROOT") or ""
VAR_DIR = Path(os.environ.get("MIRQAH_VAR_DIR") or (CONSOLE_DIR / "var")).resolve()
STATIC_DIR = CONSOLE_DIR / "static"
I18N_DIR = STATIC_DIR / "i18n"

SESSION_COOKIE = "mirqah_session"
MODE_COOKIE = "mirqah_mode"            # live | demo (per browser)
VIEW_AS_HEADER = "x-mirqah-view-as"    # super admins only; read-only while set
CSRF_HEADER = "x-mirqah"  # custom header required on every state-changing request

# ---- production switches (set in the server's environment file, never in git)
# MIRQAH_ENV=production    never show mock codes on screen; HTTPS-only cookies
# MIRQAH_PROXY=cloudflare  the console sits behind Cloudflare Tunnel on 127.0.0.1:
#                          take the visitor's IP from CF-Connecting-IP
# MIRQAH_ALLOWED_HOSTS     comma list of public host names (localhost always allowed)
ENV = (os.environ.get("MIRQAH_ENV") or "development").strip().lower()
PRODUCTION = ENV == "production"
PROXY = (os.environ.get("MIRQAH_PROXY") or "").strip().lower()
TRUST_CF_IP = PROXY == "cloudflare"
SECURE_COOKIES = PRODUCTION or TRUST_CF_IP or os.environ.get("MIRQAH_SECURE_COOKIES") == "1"
ALLOWED_HOSTS = tuple(h.strip().lower() for h in
                      (os.environ.get("MIRQAH_ALLOWED_HOSTS") or "").split(",") if h.strip())
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")

# Judges/guests: a read-only session without e-mail (Settings → Security, off by default).
GUEST_EMAIL = "guest@mirqah.invalid"
GUEST_PERMISSIONS = ("view_dashboard", "view_tasks", "view_reports")
GUEST_SESSION_HOURS = 4

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
    "publish_units",
    "view_audit",
    "manage_users",
    "manage_roles",
    "manage_settings",
    "manage_languages",
)

# Methods that the verifier always routes to the specialist (src/v2_verify.py
# FORCE_SPECIALIST_METHODS + M_RAY). Used only by the read-only chair preview.
FORCE_SPECIALIST = {"M_ISRAILIYYAT", "M_NUZUL", "M_QIRAAT", "M_RAY"}

# Only users holding this role decide (approve / needs edit / reject) — whatever other
# roles or permissions they have. A super admin who also reviews gets it as a second role.
DECIDER_ROLE = "specialist"
# Role order used to pick a user's primary role (shown first) from several.
ROLE_ORDER = ("super_admin", "committee_operator", "specialist", "viewer")
COMMITTEE_THRESHOLD = 85


def work_root() -> Path:
    """REPO_ROOT, or the writable run workspace when one is configured and present."""
    if _WORK:
        p = Path(_WORK)
        if (p / "data").is_dir():
            return p.resolve()
    return REPO_ROOT


def ensure_dirs() -> None:
    VAR_DIR.mkdir(parents=True, exist_ok=True)
    (VAR_DIR / "outbox").mkdir(parents=True, exist_ok=True)
