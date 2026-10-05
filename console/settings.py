"""Settings with defaults, validation and seed data (roles, languages)."""

from __future__ import annotations

import copy
import os
import re
import sys
from typing import Any

from . import config, db

SECRET_KEYS = {("smtp", "password")}

DEFAULTS: dict[str, dict[str, Any]] = {
    "general": {
        "project_name": "فهرس مناهج التفسير",
        "team_name": "مِرْقاة",
        "timezone": "Asia/Riyadh",
        "surah": 24,
        "data_root": "data/nur",
        "sample_ayah": "24:35",
        "console_url": "",
    },
    "llm": {
        "runtime": "ollama-local",
        "base_url": "http://127.0.0.1:11434",
        "classifier_model": "qwen2.5:14b",
        "verifier_model": "gemma3:12b",
        "step_timeout_s": 600,
        "python_bin": "",
    },
    "smtp": {
        "mode": "mock",
        "host": "",
        "port": 587,
        "security": "starttls",
        "username": "",
        "password": "",
        "from_email": "",
        "from_name": "مِرْقاة",
    },
    "security": {
        "otp_length": 6,
        "otp_ttl_min": 10,
        "otp_max_attempts": 5,
        "otp_resend_s": 60,
        "session_hours": 12,
        "show_mock_code": True,
        "guest_access": False,
    },
    "gates": {
        "phase0_merged": False,
        "phase0_note": "",
        "sample_reviewed": False,
        "sample_max_windows": 12,
    },
    "demo": {
        "guest_mode": "live",
        "months": 12,
    },
    "reports": {
        "auto_daily": True,
        "daily_time": "21:00",
        "mail_roles": ["super_admin", "committee_operator"],
    },
    # the committee chair's human side: who reviews what, reminders, retries, alerts
    "workflow": {
        "auto_assign": True,
        "reminders": True,
        "reminder_time": "09:00",
        "min_specialists": 3,
        "auto_retry": True,
        "retry_max": 2,
        "retry_first_min": 5,
        "retry_second_min": 30,
        "failure_alerts": True,
        "alert_roles": ["super_admin", "committee_operator"],
    },
}

DEFAULT_ROLES = [
    {
        "key": "super_admin",
        "name_ar": "المشرف العام",
        "name_en": "Super admin",
        "description_ar": "كل الصلاحيات، ومنها الإعدادات وسير عمل الوكلاء. لا يُعدَّل.",
        "system": 1,
        "permissions": list(config.PERMISSIONS),
    },
    {
        "key": "committee_operator",
        "name_ar": "مشغّل اللجنة",
        "name_en": "Committee operator",
        "description_ar": "يشغّل مهام الوكلاء على العيّنة ويتابع التقدّم والتقارير.",
        "system": 0,
        "permissions": [
            "view_dashboard", "view_tasks", "run_tasks", "manage_tasks",
            "view_reports", "generate_reports", "view_audit",
        ],
    },
    {
        "key": "specialist",
        "name_ar": "المتخصص",
        "name_en": "Specialist",
        "description_ar": "يراجع الوحدات ويعتمد أو يطلب تعديلاً أو يرفض. الاعتماد قراره وحده.",
        "system": 0,
        "permissions": ["view_dashboard", "view_tasks", "view_reports", "review_units"],
    },
    {
        "key": "viewer",
        "name_ar": "مشاهد",
        "name_en": "Viewer",
        "description_ar": "اطلاع فقط على اللوحة والمهام والتقارير.",
        "system": 0,
        "permissions": ["view_dashboard", "view_tasks", "view_reports"],
    },
]

DEFAULT_LANGUAGES = [
    ("ar", "العربية", "Arabic", "rtl", 1, 1, 10),
    ("en", "English", "English", "ltr", 1, 0, 20),
    ("zh", "中文", "Chinese", "ltr", 1, 0, 30),
    ("ur", "اردو", "Urdu", "rtl", 1, 0, 40),
]


def seed() -> None:
    """Insert default roles, languages and settings that do not exist yet."""
    with db.connect() as con:
        for r in DEFAULT_ROLES:
            exists = con.execute("SELECT id FROM roles WHERE key=?", (r["key"],)).fetchone()
            if exists is None:
                con.execute(
                    "INSERT INTO roles(key,name_ar,name_en,description_ar,system,permissions)"
                    " VALUES (?,?,?,?,?,?)",
                    (r["key"], r["name_ar"], r["name_en"], r["description_ar"], r["system"],
                     db.dumps(r["permissions"])),
                )
            elif r["system"]:
                # system role always keeps every permission (new permissions included)
                con.execute("UPDATE roles SET permissions=? WHERE key=?",
                            (db.dumps(r["permissions"]), r["key"]))
        if con.execute("SELECT COUNT(*) FROM languages").fetchone()[0] == 0:
            con.executemany(
                "INSERT INTO languages(code,name_native,name_en,dir,enabled,is_default,sort)"
                " VALUES (?,?,?,?,?,?,?)",
                DEFAULT_LANGUAGES,
            )
        for section, values in DEFAULTS.items():
            if con.execute("SELECT 1 FROM settings WHERE key=?", (section,)).fetchone() is None:
                con.execute("INSERT INTO settings(key,value,updated_at) VALUES (?,?,?)",
                            (section, db.dumps(values), db.now()))


def get(section: str) -> dict[str, Any]:
    stored = db.loads(db.scalar("SELECT value FROM settings WHERE key=?", (section,)), {}) or {}
    merged = copy.deepcopy(DEFAULTS.get(section, {}))
    merged.update({k: v for k, v in stored.items() if k in merged})
    if section == "smtp" and os.environ.get("MIRQAH_SMTP_PASSWORD"):
        merged["password"] = os.environ["MIRQAH_SMTP_PASSWORD"]
    if section == "llm" and not merged.get("python_bin"):
        merged["python_bin"] = sys.executable
    return merged


def get_all(redact: bool = True) -> dict[str, dict[str, Any]]:
    out = {s: get(s) for s in DEFAULTS}
    if redact:
        for section, key in SECRET_KEYS:
            out[section][key] = ""
            out[section][f"{key}_set"] = bool(get(section).get(key))
    return out


_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SettingsError(ValueError):
    pass


def _coerce(section: str, key: str, value: Any) -> Any:
    default = DEFAULTS[section][key]
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise SettingsError(f"{section}.{key} must be true/false")
        return value
    if isinstance(default, int):
        try:
            value = int(value)
        except (TypeError, ValueError) as e:
            raise SettingsError(f"{section}.{key} must be a number") from e
        return value
    if isinstance(default, list):
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise SettingsError(f"{section}.{key} must be a list of strings")
        return value
    if not isinstance(value, str):
        raise SettingsError(f"{section}.{key} must be text")
    return value.strip()


def _validate(section: str, values: dict[str, Any]) -> None:
    if section == "smtp":
        if values["mode"] not in ("mock", "smtp"):
            raise SettingsError("smtp.mode must be mock or smtp")
        if values["security"] not in ("starttls", "ssl", "none"):
            raise SettingsError("smtp.security must be starttls, ssl or none")
        if not 1 <= values["port"] <= 65535:
            raise SettingsError("smtp.port out of range")
        if values["from_email"] and not _EMAIL_RE.match(values["from_email"]):
            raise SettingsError("smtp.from_email is not an email address")
        if values["mode"] == "smtp" and not (values["host"] and values["from_email"]):
            raise SettingsError("smtp mode needs host and from_email")
    if section == "security":
        if not 4 <= values["otp_length"] <= 8:
            raise SettingsError("security.otp_length must be 4–8")
        if not 1 <= values["otp_ttl_min"] <= 60:
            raise SettingsError("security.otp_ttl_min must be 1–60")
        if not 1 <= values["otp_max_attempts"] <= 10:
            raise SettingsError("security.otp_max_attempts must be 1–10")
        if not 1 <= values["session_hours"] <= 72:
            raise SettingsError("security.session_hours must be 1–72")
    if section == "reports" and not _TIME_RE.match(values["daily_time"]):
        raise SettingsError("reports.daily_time must be HH:MM")
    if section == "llm":
        if not values["base_url"].startswith(("http://", "https://")):
            raise SettingsError("llm.base_url must start with http:// or https://")
        if values["runtime"] not in ("ollama-local", "hosted"):
            raise SettingsError("llm.runtime must be ollama-local or hosted")
        if not 30 <= values["step_timeout_s"] <= 3600:
            raise SettingsError("llm.step_timeout_s must be 30–3600")
        for k in ("classifier_model", "verifier_model"):
            if not re.match(r"^[A-Za-z0-9._:/-]{1,80}$", values[k] or ""):
                raise SettingsError(f"llm.{k} is not a valid model tag")
    if section == "general":
        if not re.match(r"^data/[a-z0-9_/]+$", values["data_root"]):
            raise SettingsError("general.data_root must look like data/<name>")
        if not re.match(r"^\d{1,3}:\d{1,3}$", values["sample_ayah"]):
            raise SettingsError("general.sample_ayah must look like 24:35")
        if values["console_url"] and not re.match(r"^https?://[A-Za-z0-9.-]+(:\d+)?(/[^\s]*)?$",
                                                  values["console_url"]):
            raise SettingsError("general.console_url must be like https://console.example.com")
    if section == "demo":
        if values["guest_mode"] not in ("live", "demo"):
            raise SettingsError("demo.guest_mode must be live or demo")
        if not 3 <= values["months"] <= 18:
            raise SettingsError("demo.months must be 3–18")
    if section == "workflow":
        if not _TIME_RE.match(values["reminder_time"]):
            raise SettingsError("workflow.reminder_time must be HH:MM")
        if not 0 <= values["retry_max"] <= 5:
            raise SettingsError("workflow.retry_max must be 0–5")
        for k in ("retry_first_min", "retry_second_min"):
            if not 1 <= values[k] <= 1440:
                raise SettingsError(f"workflow.{k} must be 1–1440 minutes")
        if not 1 <= values["min_specialists"] <= 20:
            raise SettingsError("workflow.min_specialists must be 1–20")
    if section == "gates" and not 1 <= values["sample_max_windows"] <= 60:
        raise SettingsError("gates.sample_max_windows must be 1–60")


def update(section: str, patch: dict[str, Any], user_id: int | None) -> dict[str, Any]:
    if section not in DEFAULTS:
        raise SettingsError(f"unknown settings section {section!r}")
    current = get(section)
    if section == "smtp" and os.environ.get("MIRQAH_SMTP_PASSWORD"):
        current["password"] = db.loads(
            db.scalar("SELECT value FROM settings WHERE key='smtp'"), {}).get("password", "")
    changed = []
    for key, value in (patch or {}).items():
        if key not in DEFAULTS[section]:
            continue
        if (section, key) in SECRET_KEYS and (value is None or value == ""):
            continue  # empty secret field = keep the stored one
        new = _coerce(section, key, value)
        if current.get(key) != new:
            changed.append(key)
        current[key] = new
    _validate(section, current)
    db.execute(
        "INSERT INTO settings(key,value,updated_at,updated_by) VALUES (?,?,?,?)"
        " ON CONFLICT(key) DO UPDATE SET value=excluded.value,"
        " updated_at=excluded.updated_at, updated_by=excluded.updated_by",
        (section, db.dumps(current), db.now(), user_id),
    )
    redacted = [c if (section, c) not in SECRET_KEYS else f"{c} (secret)" for c in changed]
    db.audit("settings.update", user_id=user_id, target=section, detail={"changed": redacted})
    return get_all()[section]
