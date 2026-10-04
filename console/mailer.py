"""Outgoing mail: mock outbox (default) or real SMTP from settings."""

from __future__ import annotations

import smtplib
import ssl
import time
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from . import config, db, settings


class MailError(RuntimeError):
    pass


def _write_eml(msg: EmailMessage) -> None:
    name = f"{time.strftime('%Y%m%d-%H%M%S')}-{abs(hash(msg['Message-ID'])) % 10**8:08d}.eml"
    (config.VAR_DIR / "outbox" / name).write_bytes(bytes(msg))


def send(to_addr: str, subject: str, body: str) -> dict:
    """Send one plain-text UTF-8 message. Returns {"mode", "status"}.

    In mock mode nothing leaves the machine: the message is stored in the
    outbox table and as an .eml file under console/var/outbox/.
    """
    cfg = settings.get("smtp")
    msg = EmailMessage()
    from_email = cfg["from_email"] or "no-reply@mirqah.local"
    msg["From"] = formataddr((cfg["from_name"] or "Mirqah", from_email))
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=from_email.split("@")[-1])
    msg.set_content(body, charset="utf-8")

    mode = cfg["mode"]
    status, error = "sent", None
    if mode == "mock":
        status = "mock"
        _write_eml(msg)
    else:
        try:
            if cfg["security"] == "ssl":
                with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=20,
                                      context=ssl.create_default_context()) as s:
                    if cfg["username"]:
                        s.login(cfg["username"], cfg["password"])
                    s.send_message(msg)
            else:
                with smtplib.SMTP(cfg["host"], cfg["port"], timeout=20) as s:
                    if cfg["security"] == "starttls":
                        s.starttls(context=ssl.create_default_context())
                    if cfg["username"]:
                        s.login(cfg["username"], cfg["password"])
                    s.send_message(msg)
        except (OSError, smtplib.SMTPException) as e:
            status, error = "failed", f"{type(e).__name__}: {e}"[:300]
    db.execute(
        "INSERT INTO outbox(at,to_addr,subject,body,mode,status,error) VALUES (?,?,?,?,?,?,?)",
        (db.now(), to_addr, subject, body, mode, status, error),
    )
    if status == "failed":
        raise MailError(error or "send failed")
    return {"mode": mode, "status": status}
