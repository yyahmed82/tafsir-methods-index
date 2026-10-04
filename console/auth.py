"""Login by one-time code sent to a registered e-mail, sessions and RBAC."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import threading
import time
from collections import defaultdict, deque

from . import config, db, mailer, settings

log = logging.getLogger("mirqah.console")

_PEPPER_FILE = None  # set in init()
_PEPPER = b""
_RATE: dict[str, deque] = defaultdict(deque)
_RATE_LOCK = threading.Lock()


def init() -> None:
    """Load or create the local pepper used to hash OTP codes and tokens."""
    global _PEPPER
    path = config.VAR_DIR / "secret.key"
    if not path.exists():
        path.write_bytes(secrets.token_bytes(32))
        try:
            path.chmod(0o600)
        except OSError:
            pass
    _PEPPER = path.read_bytes()


def _h(value: str) -> str:
    return hmac.new(_PEPPER, value.encode("utf-8"), hashlib.sha256).hexdigest()


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def rate_limited(bucket: str, limit: int, per_s: int) -> bool:
    """Sliding-window limiter kept in memory (local single-process server)."""
    t = time.monotonic()
    with _RATE_LOCK:
        q = _RATE[bucket]
        while q and t - q[0] > per_s:
            q.popleft()
        if len(q) >= limit:
            return True
        q.append(t)
        return False


def reset_rate_limits() -> None:
    with _RATE_LOCK:
        _RATE.clear()


# ---------------------------------------------------------------- OTP

def request_otp(email: str, ip: str | None) -> dict:
    """Create and mail a code if (and only if) the e-mail belongs to an active user.

    The HTTP answer is the same either way so the form does not reveal who is
    registered. In mock mode with ``show_mock_code`` the code is returned for
    local testing; turn that off in Settings → Security before any demo.
    """
    email = normalize_email(email)
    sec = settings.get("security")
    out = {"ok": True, "cooldown_s": sec["otp_resend_s"]}
    user = db.row("SELECT * FROM users WHERE email=? AND active=1", (email,))
    if user is None:
        db.audit("auth.otp_unknown", target=email, ip=ip)
        return out
    last = db.row("SELECT created_at FROM otp_codes WHERE email=? ORDER BY created_at DESC LIMIT 1",
                  (email,))
    if last and db.now() - last["created_at"] < sec["otp_resend_s"]:
        out["cooldown_s"] = int(sec["otp_resend_s"] - (db.now() - last["created_at"])) + 1
        return out
    code = "".join(secrets.choice("0123456789") for _ in range(sec["otp_length"]))
    db.execute("UPDATE otp_codes SET used=1 WHERE email=? AND used=0", (email,))
    db.execute(
        "INSERT INTO otp_codes(email,code_hash,created_at,expires_at,ip) VALUES (?,?,?,?,?)",
        (email, _h(f"{email}:{code}"), db.now(), db.now() + sec["otp_ttl_min"] * 60, ip),
    )
    gen = settings.get("general")
    body = (
        f"السلام عليكم {user['name']}،\n\n"
        f"رمز الدخول إلى لوحة لجنة {gen['team_name']}: {code}\n"
        f"صالح لمدة {sec['otp_ttl_min']} دقائق. لا تشاركه مع أحد.\n\n"
        f"Your sign-in code: {code} (valid {sec['otp_ttl_min']} min).\n"
    )
    try:
        res = mailer.send(email, f"رمز الدخول — {gen['team_name']}", body)
    except mailer.MailError as e:
        log.error("otp mail failed for %s: %s", email, e)
        db.audit("auth.otp_mail_failed", user_id=user["id"], ip=ip, detail={"error": str(e)})
        out["mail_error"] = True
        return out
    db.audit("auth.otp_sent", user_id=user["id"], ip=ip, detail={"mode": res["mode"]})
    if res["mode"] == "mock":
        log.warning("MOCK OTP for %s: %s", email, code)
        if sec["show_mock_code"]:
            out["mock_code"] = code
    return out


def verify_otp(email: str, code: str, ip: str | None, user_agent: str | None) -> tuple[str, dict]:
    """Return (session_token, user) or raise PermissionError with a reason key."""
    email = normalize_email(email)
    code = (code or "").strip()
    sec = settings.get("security")
    rec = db.row(
        "SELECT * FROM otp_codes WHERE email=? AND used=0 ORDER BY created_at DESC LIMIT 1",
        (email,),
    )
    if rec is None or rec["expires_at"] < db.now():
        raise PermissionError("otp_expired")
    if rec["attempts"] >= sec["otp_max_attempts"]:
        db.execute("UPDATE otp_codes SET used=1 WHERE id=?", (rec["id"],))
        raise PermissionError("otp_locked")
    if not hmac.compare_digest(rec["code_hash"], _h(f"{email}:{code}")):
        db.execute("UPDATE otp_codes SET attempts=attempts+1 WHERE id=?", (rec["id"],))
        db.audit("auth.otp_wrong", target=email, ip=ip)
        raise PermissionError("otp_wrong")
    user = db.row("SELECT * FROM users WHERE email=? AND active=1", (email,))
    if user is None:
        raise PermissionError("otp_wrong")
    db.execute("UPDATE otp_codes SET used=1 WHERE id=?", (rec["id"],))
    token = secrets.token_urlsafe(32)
    db.execute(
        "INSERT INTO sessions(token_hash,user_id,created_at,expires_at,ip,user_agent)"
        " VALUES (?,?,?,?,?,?)",
        (_h(token), user["id"], db.now(), db.now() + sec["session_hours"] * 3600, ip,
         (user_agent or "")[:200]),
    )
    db.execute("UPDATE users SET last_login_at=? WHERE id=?", (db.now(), user["id"]))
    db.audit("auth.login", user_id=user["id"], ip=ip)
    return token, user


def session_user(token: str | None) -> dict | None:
    if not token:
        return None
    s = db.row(
        "SELECT s.id AS sid, s.expires_at, u.*, r.key AS role_key, r.name_ar AS role_name_ar,"
        " r.name_en AS role_name_en, r.permissions AS role_permissions"
        " FROM sessions s JOIN users u ON u.id=s.user_id JOIN roles r ON r.id=u.role_id"
        " WHERE s.token_hash=? AND s.revoked=0",
        (_h(token),),
    )
    if s is None or s["expires_at"] < db.now() or not s["active"]:
        return None
    s["permissions"] = sorted(set(db.loads(s.pop("role_permissions"), [])))
    return s


def revoke(token: str | None) -> None:
    if token:
        db.execute("UPDATE sessions SET revoked=1 WHERE token_hash=?", (_h(token),))


def revoke_user_sessions(user_id: int) -> None:
    db.execute("UPDATE sessions SET revoked=1 WHERE user_id=?", (user_id,))


def public_user(u: dict) -> dict:
    return {
        "id": u["id"], "email": u["email"], "name": u["name"], "lang": u.get("lang") or "",
        "role": {"key": u.get("role_key"), "name_ar": u.get("role_name_ar"),
                 "name_en": u.get("role_name_en")},
        "permissions": u.get("permissions", []),
    }
