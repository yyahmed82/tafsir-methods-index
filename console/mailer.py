"""Outgoing mail: mock outbox (default) or real SMTP from settings.

Messages are multipart: a plain-text part and, when given, a branded HTML part
(console/mailtpl.py) with the logo attached inline (cid:), so it shows without
"load images".
"""

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


def send_mail(to_addr: str, mail) -> dict:
    """Send a ``mailtpl.Mail`` (text + HTML + inline logo)."""
    return send(to_addr, mail.subject, mail.text, outbox_body=mail.outbox_text, html=mail.html,
                outbox_html=mail.outbox_html, inline=mail.inline)


def send(to_addr: str, subject: str, body: str, outbox_body: str | None = None, *,
         html: str | None = None, outbox_html: str | None = None,
         inline: list[tuple[str, bytes]] | None = None) -> dict:
    """Send one UTF-8 message (text, plus HTML when given). Returns {"mode", "status"}.

    In mock mode nothing leaves the machine: the message is stored in the
    outbox table and as an .eml file under console/var/outbox/.
    ``outbox_body`` is what the outbox table keeps for real (SMTP) mail, e.g.
    the sign-in message with its code masked.
    """
    cfg = settings.get("smtp")
    msg = EmailMessage()
    from_email = cfg["from_email"] or "no-reply@mirqah.local"
    msg["From"] = formataddr((cfg["from_name"] or "Mirqah", from_email))
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=from_email.split("@")[-1])
    msg.set_content(body, charset="utf-8")
    if html:
        msg.add_alternative(html, subtype="html", charset="utf-8")
        html_part = msg.get_payload()[-1]
        for cid, data in inline or []:
            html_part.add_related(data, maintype="image", subtype="png", cid=f"<{cid}>",
                                  filename=f"{cid}.png", disposition="inline")

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
    keep_real = mode == "mock"
    db.execute(
        "INSERT INTO outbox(at,to_addr,subject,body,html,mode,status,error) VALUES (?,?,?,?,?,?,?,?)",
        (db.now(), to_addr, subject,
         body if keep_real or outbox_body is None else outbox_body,
         (html if keep_real or outbox_html is None else outbox_html) if html else None,
         mode, status, error),
    )
    if status == "failed":
        raise MailError(error or "send failed")
    return {"mode": mode, "status": status}
