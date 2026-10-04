"""Branded HTML e-mails (Arabic, right-to-left) with a plain-text twin.

Every message the console sends goes through ``shell()``: a table layout that
mail clients (Gmail, Outlook, Apple Mail) render the same way, a dark green
header with the مِرْقاة wordmark as an inline image (``cid:mqlogo``, so it shows
without "load images"), a badge and an optional status pill, a white body and a
quiet footer. Builders return ``Mail`` objects; ``mailer.send_mail`` sends them.

Never put tafsir text, tags or approvals in a mail: these are operational
messages only (sign-in codes, tests, welcome, daily counts).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from html import escape
from typing import Any, Iterable

from . import config, settings

LOGO_CID = "mqlogo"
LOGO_FILE = config.STATIC_DIR / "brand" / "mail-wordmark.png"
LOGO_W, LOGO_H = 150, 111  # display size; the PNG is 2x for sharp screens

C = {
    "page": "#f3f1ea", "header": "#0b3d34", "badge": "#1d5a4c", "badge_text": "#efe3c2",
    "ink": "#1f2d29", "muted": "#6b766f", "line": "#ebe5d6", "gold": "#b8893a",
    "gold_soft": "#f7f0de", "green": "#0f6b55", "green_soft": "#e8f3ee", "foot": "#fbf9f3",
    "warn": "#b45309", "warn_soft": "#fff6e8", "bad": "#b91c1c", "bad_soft": "#fdeeee",
}
FONT = "Tahoma,'Segoe UI','Noto Naskh Arabic','Geeza Pro',Arial,sans-serif"
MONO = "'SFMono-Regular',Menlo,Consolas,'Courier New',monospace"
PILL = {"green": "#0f7a5f", "gold": "#a8792c", "amber": "#c26d0a", "red": "#c0392b",
        "slate": "#5b6b66"}


@dataclass
class Mail:
    subject: str
    text: str
    html: str
    # what the outbox keeps for real (SMTP) mail, e.g. the sign-in code masked
    outbox_text: str | None = None
    outbox_html: str | None = None
    kind: str = "mail"
    inline: list[tuple[str, bytes]] = field(default_factory=list)


def e(value: Any) -> str:
    return escape("" if value is None else str(value), quote=True)


def console_url() -> str:
    return (settings.get("general").get("console_url") or "").rstrip("/")


def _logo() -> list[tuple[str, bytes]]:
    try:
        return [(LOGO_CID, LOGO_FILE.read_bytes())]
    except OSError:  # pragma: no cover - the PNG ships with the console
        return []


# ------------------------------------------------------------------ building blocks

def shell(title: str, body_html: str, *, pill: str | None = None, pill_color: str = "green",
          preheader: str = "", badge: str | None = None) -> str:
    gen = settings.get("general")
    badge = badge or f"لوحة لجنة الذكاء · {gen['project_name']}"
    pill_html = (f'<span style="display:inline-block;background:{PILL.get(pill_color, pill_color)};'
                 f'color:#ffffff;font-family:{FONT};font-size:12px;font-weight:700;border-radius:6px;'
                 f'padding:3px 10px;margin-right:6px;">{e(pill)}</span>') if pill else ""
    logo = (f'<img src="cid:{LOGO_CID}" width="{LOGO_W}" height="{LOGO_H}" alt="{e(gen["team_name"])}" '
            f'style="display:block;border:0;outline:none;width:{LOGO_W}px;height:{LOGO_H}px;">')
    foot = (f'{e(gen["team_name"])} · {e(gen["project_name"])} — رسالة آلية من لوحة لجنة الذكاء، '
            f'لا تردّ عليها.<br><span dir="ltr" style="unicode-bidi:isolate;">'
            f'Automated message from the {e("Mirqah")} committee console.</span>')
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light">
<title>{e(title)}</title>
<style>:root{{color-scheme:light only}} body{{background:{C['page']} !important;margin:0;padding:0}}
@media (max-width:620px){{.mq-card{{width:100% !important;max-width:100% !important}} .mq-px{{padding-left:20px !important;padding-right:20px !important}}
.mq-tile{{display:block !important;width:100% !important;margin-bottom:8px}}}}</style></head>
<body bgcolor="{C['page']}" dir="rtl" style="margin:0;padding:0;background:{C['page']};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:{C['page']};">{e(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{C['page']}" style="background:{C['page']};padding:24px 0;">
<tr><td align="center">
<table role="presentation" class="mq-card" width="600" cellpadding="0" cellspacing="0" dir="rtl" style="width:600px;max-width:94%;">
  <tr><td class="mq-px" bgcolor="{C['header']}" align="right" dir="rtl" style="background:{C['header']};border-radius:14px 14px 0 0;padding:26px 32px 22px;text-align:right;">
    {logo}
    <div style="color:#ffffff;font-family:{FONT};font-size:21px;font-weight:700;line-height:1.5;padding-top:14px;">{e(title)}</div>
    <div style="padding-top:10px;"><span style="display:inline-block;background:{C['badge']};color:{C['badge_text']};font-family:{FONT};font-size:12px;font-weight:700;border-radius:6px;padding:3px 10px;">{e(badge)}</span>{pill_html}</div>
  </td></tr>
  <tr><td height="4" style="height:4px;line-height:4px;font-size:0;background:{C['gold']};background-image:linear-gradient(90deg,#9a722c,#dcbd6c,#9a722c);">&nbsp;</td></tr>
  <tr><td class="mq-px" bgcolor="#ffffff" align="right" dir="rtl" style="background:#ffffff;border-left:1px solid {C['line']};border-right:1px solid {C['line']};padding:26px 32px;font-family:{FONT};font-size:15px;line-height:1.85;color:{C['ink']};text-align:right;">
    {body_html}
  </td></tr>
  <tr><td class="mq-px" bgcolor="{C['foot']}" align="right" dir="rtl" style="background:{C['foot']};border:1px solid {C['line']};border-top:1px solid {C['line']};border-radius:0 0 14px 14px;padding:14px 32px 18px;font-family:{FONT};font-size:12px;line-height:1.7;color:{C['muted']};text-align:right;">
    {foot}
  </td></tr>
</table>
</td></tr></table>
</body></html>"""


def p(html: str, *, size: int = 15, color: str | None = None, mt: int = 0) -> str:
    return (f'<p style="margin:{mt}px 0 12px;font-size:{size}px;line-height:1.85;'
            f'color:{color or C["ink"]};">{html}</p>')


def callout(title: str, text_html: str, tone: str = "gold") -> str:
    bg, line, fg = {
        "gold": (C["gold_soft"], "#e2c98f", "#7a5a1c"), "green": (C["green_soft"], "#9fd0bd", C["green"]),
        "warn": (C["warn_soft"], "#f3c98b", C["warn"]), "bad": (C["bad_soft"], "#f2b8b8", C["bad"]),
    }[tone]
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:6px 0 16px;">'
            f'<tr><td dir="rtl" style="background:{bg};border:1px solid {line};border-right:4px solid {fg};'
            f'border-radius:10px;padding:12px 16px;font-family:{FONT};text-align:right;">'
            f'<div style="font-weight:700;color:{fg};font-size:14.5px;margin-bottom:4px;">{e(title)}</div>'
            f'<div style="font-size:14px;line-height:1.8;color:{C["ink"]};">{text_html}</div></td></tr></table>')


def kv(rows: Iterable[tuple[str, str]]) -> str:
    """Label/value rows; values are trusted HTML (escape before passing)."""
    out = "".join(
        f'<tr><td valign="top" style="padding:7px 0 7px 14px;color:{C["muted"]};font-size:13px;'
        f'white-space:nowrap;vertical-align:top;">{e(k)}</td>'
        f'<td style="padding:7px 0;font-size:14px;color:{C["ink"]};">{v}</td></tr>' for k, v in rows)
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" dir="rtl" '
            f'style="border-collapse:collapse;margin:4px 0 14px;font-family:{FONT};">{out}</table>')


def button(label: str, url: str, hint: str = "") -> str:
    if not url:
        return ""
    h = f'<td style="padding-right:14px;font-size:12.5px;color:{C["muted"]};font-family:{FONT};">{e(hint)}</td>' if hint else ""
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:10px 0 6px;"><tr>'
            f'<td bgcolor="{C["green"]}" style="background:{C["green"]};border-radius:9px;">'
            f'<a href="{e(url)}" style="display:inline-block;padding:11px 22px;font-family:{FONT};font-size:15px;'
            f'font-weight:700;color:#ffffff;text-decoration:none;border-radius:9px;">{e(label)} ‹</a></td>{h}</tr></table>')


def code_box(code: str) -> str:
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:6px 0 14px;"><tr>'
            f'<td dir="ltr" style="background:{C["gold_soft"]};border:1px dashed #d4b46a;border-radius:12px;'
            f'padding:14px 26px;font-family:{MONO};font-size:32px;font-weight:700;letter-spacing:10px;'
            f'color:{C["green"]};text-align:center;">{e(code)}</td></tr></table>')


def section(title: str) -> str:
    return (f'<div style="font-weight:700;font-size:13px;letter-spacing:.02em;color:{C["gold"]};'
            f'margin:18px 0 8px;border-bottom:1px solid {C["line"]};padding-bottom:6px;">{e(title)}</div>')


def tiles(items: list[tuple[str, Any, str]]) -> str:
    """[(label, value, color)] as a row of stat tiles."""
    w = int(100 / max(1, len(items)))
    cells = "".join(
        f'<td class="mq-tile" width="{w}%" valign="top" style="padding:0 0 0 8px;">'
        f'<div style="background:#faf8f2;border:1px solid {C["line"]};border-radius:10px;padding:10px 12px;">'
        f'<div style="font-size:12px;color:{C["muted"]};">{e(label)}</div>'
        f'<div style="font-size:22px;font-weight:700;color:{color};font-family:{FONT};">{e(val)}</div></div></td>'
        for label, val, color in items)
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:4px 0 12px;">'
            f'<tr>{cells}</tr></table>')


def bar(label: str, done: int, total: int, extra: str = "") -> str:
    pct = 0 if not total else max(0, min(100, round(100 * done / total)))
    fill = f'<td width="{pct}%" bgcolor="{C["green"]}" style="background:{C["green"]};height:8px;line-height:8px;font-size:0;border-radius:4px;">&nbsp;</td>' if pct else ""
    rest = '<td bgcolor="#ece7da" style="background:#ece7da;height:8px;line-height:8px;font-size:0;">&nbsp;</td>' if pct < 100 else ""
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:2px 0 10px;">'
            f'<tr><td style="font-size:13.5px;padding-bottom:4px;">{e(label)} <span style="color:{C["muted"]};font-size:12.5px;">'
            f'· {done}/{total}{(" · " + e(extra)) if extra else ""}</span></td></tr>'
            f'<tr><td><table role="presentation" width="100%" cellpadding="0" cellspacing="0" dir="rtl" '
            f'style="border-radius:4px;overflow:hidden;"><tr>{fill}{rest}</tr></table></td></tr></table>')


def ul(items: Iterable[str]) -> str:
    lis = "".join(f'<li style="margin:0 0 6px;">{x}</li>' for x in items)
    return f'<ul style="margin:0 0 12px;padding:0 20px 0 0;font-size:14px;line-height:1.8;">{lis}</ul>'


def _when(ts: float | None = None) -> str:
    tz_name = settings.get("general")["timezone"]
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:  # pragma: no cover
        tz = dt.timezone(dt.timedelta(hours=3))
    d = dt.datetime.fromtimestamp(ts or dt.datetime.now().timestamp(), tz)
    return d.strftime("%Y-%m-%d %H:%M") + f" ({tz_name})"


# ------------------------------------------------------------------ messages

def otp(name: str, email: str, code: str, ttl_min: int, ip: str | None) -> Mail:
    gen = settings.get("general")
    team = gen["team_name"]
    url = console_url()
    subject = f"رمز الدخول — {team}"

    def build(c: str) -> tuple[str, str]:
        text = (f"السلام عليكم {name}،\n\n"
                f"رمز الدخول إلى لوحة لجنة {team}: {c}\n"
                f"صالح لمدة {ttl_min} دقائق. لا تشاركه مع أحد.\n"
                + (f"اللوحة: {url}\n" if url else "")
                + f"\nYour sign-in code: {c} (valid {ttl_min} min).\n")
        body = (p(f"السلام عليكم <b>{e(name)}</b>،")
                + p(f"رمز الدخول إلى لوحة لجنة <b>{e(team)}</b>:", mt=0)
                + code_box(c)
                + p(f"صالح لمدة <b>{ttl_min} دقائق</b> ولمرة واحدة. لا تشاركه مع أحد — فريقنا لن يطلبه منك.",
                    size=14)
                + kv([("الحساب", f'<span dir="ltr">{e(email)}</span>'),
                      ("وقت الطلب", e(_when())),
                      ("من عنوان", f'<span dir="ltr">{e(ip or "—")}</span>')])
                + callout("لم تطلب هذا الرمز؟", "تجاهل الرسالة؛ لا يمكن الدخول دون الرمز، وتنتهي صلاحيته تلقائياً.",
                          "gold")
                + button("فتح اللوحة", url)
                + p(f'<span dir="ltr" style="unicode-bidi:isolate;">Your sign-in code: <b>{e(c)}</b> '
                    f'(valid {ttl_min} min).</span>', size=12.5, color=C["muted"], mt=10))
        return text, shell("رمز الدخول إلى اللوحة", body, pill="رمز لمرة واحدة", pill_color="gold",
                           preheader=f"رمز الدخول: {c} — صالح {ttl_min} دقائق")

    text, html = build(code)
    mtext, mhtml = build("•" * len(code))
    return Mail(subject, text, html, mtext, mhtml, kind="otp", inline=_logo())


def test(to: str) -> Mail:
    cfg = settings.get("smtp")
    team = settings.get("general")["team_name"]
    subject = f"اختبار البريد — {team}"
    text = ("رسالة اختبار من لوحة لجنة مِرْقاة. إن وصلتك فإعدادات البريد سليمة.\n"
            "Test message from the Mirqah committee console.\n")
    body = (p("هذه رسالة اختبار من لوحة لجنة الذكاء.")
            + callout("إعدادات البريد تعمل", "إن وصلتك هذه الرسالة فرموز الدخول والتقارير اليومية ستصل أيضاً.",
                      "green")
            + kv([("الطريقة", e(cfg["mode"])), ("الخادم", f'<span dir="ltr">{e(cfg["host"] or "—")}:{e(cfg["port"])}</span>'),
                  ("المرسِل", f'<span dir="ltr">{e(cfg["from_email"] or "—")}</span>'),
                  ("المستلم", f'<span dir="ltr">{e(to)}</span>'), ("الوقت", e(_when()))])
            + button("فتح اللوحة", console_url()))
    return Mail(subject, text, shell("اختبار البريد", body, pill="SMTP", pill_color="green",
                                     preheader="رسالة اختبار — إعدادات البريد تعمل"),
                kind="test", inline=_logo())


def welcome(name: str, email: str, role_name: str, role_desc: str, inviter: str | None) -> Mail:
    team = settings.get("general")["team_name"]
    url = console_url()
    subject = f"أهلاً بك في لوحة لجنة {team}"
    who = f"أضافك <b>{e(inviter)}</b>" if inviter else "أُضيف حسابك"
    link = (f': <a href="{e(url)}" dir="ltr" style="color:{C["green"]};font-weight:700;">{e(url)}</a>'
            if url else "")
    steps = [
        f"افتح اللوحة{link}.",
        f'اكتب بريدك <span dir="ltr">{e(email)}</span>.',
        "أدخل الرمز الذي يصلك بالبريد — لا توجد كلمة مرور.",
    ]
    text = (f"السلام عليكم {name}،\n\n"
            f"{('أضافك ' + inviter) if inviter else 'أُضيف حسابك'} إلى لوحة لجنة {team} بصلاحية: {role_name}.\n"
            f"{role_desc}\n\n"
            "طريقة الدخول: افتح اللوحة، اكتب بريدك، ثم أدخل الرمز الذي يصلك بالبريد (لا كلمة مرور).\n"
            + (f"اللوحة: {url}\n" if url else "")
            + f"\nYou have been added to the Mirqah committee console ({role_name}). Sign in with {email};"
              " a one-time code is mailed to you.\n")
    body = (p(f"السلام عليكم <b>{e(name)}</b>،")
            + p(f"{who} إلى لوحة لجنة <b>{e(team)}</b>.")
            + kv([("الصلاحية", f"<b>{e(role_name)}</b>"), ("ما تتيحه", e(role_desc or "—")),
                  ("الحساب", f'<span dir="ltr">{e(email)}</span>')])
            + section("طريقة الدخول")
            + ul(steps)
            + callout("قاعدة ثابتة", "اللجنة الآلية تقترح فقط؛ الاعتماد قرار المتخصص البشري وحده.", "green")
            + button("الدخول إلى اللوحة", url))
    return Mail(subject, text, shell(f"أهلاً بك في لوحة لجنة {team}", body, pill=role_name, pill_color="gold",
                                     preheader=f"أُضيف حسابك بصلاحية {role_name}"),
                kind="welcome", inline=_logo())


AGENT_AR = {"classifier": "المصنّف", "verifier": "المدقّق", "chair": "رئيس اللجنة",
            "packet_check": "فحص الحزم", "checker": "الفاحص الحتمي"}
REASON_AR = {"written_abstain": "امتناع مكتوب", "force_specialist": "إحالة الفاحص",
             "agent_disagree": "اختلاف الوكيلين", "unclear_bounds": "حدود غير متقاطعة",
             "weak_evidence": "دليل غير كافٍ", "agent_missing": "لم يعمل المدقّق بعد"}


def report(c: dict, text: str) -> Mail:
    """Daily report as HTML; ``text`` is runner.report_markdown(c)."""
    team = settings.get("general")["team_name"]
    names = config.TAFSIR_NAMES_AR
    st = c["steps"]
    url = console_url()
    subject = f"التقرير اليومي — {team} — {c['day']}"
    parts = [tiles([("خطوات اليوم", st["total"], C["ink"]), ("نجحت", st["done"], C["green"]),
                    ("فشلت", st["failed"], C["bad"] if st["failed"] else C["muted"]),
                    ("تُخطّيت", st["skipped"], C["muted"])])]
    if c.get("agents"):
        rows = []
        for k, v in c["agents"].items():
            rows.append((AGENT_AR.get(k, k),
                         f"نجح <b>{v['done']}</b> · فشل <b>{v['failed']}</b> · تخطٍّ {v['skipped']}"
                         + (f" · متوسط {v['avg_s']} ث" if v.get("avg_s") else "")
                         + (f'<br><span dir="ltr" style="font-family:{MONO};font-size:12px;color:{C["muted"]};">'
                            f'{e(", ".join(v["models"]))}</span>' if v.get("models") else "")))
        parts += [section("الوكلاء"), kv(rows)]
    r = c["routes"]
    parts += [section(f"التوجيه ({c.get('routes_caption_ar', 'أعداد توجيه وليست دقة')})"),
              tiles([("حركات", r["moves"], C["ink"]), ("مرشّح للمراجعة", r["auto_candidate"], C["green"]),
                     ("بانتظار المتخصص", r["specialist"], C["gold"]), ("أعلام", r["flags"], C["warn"])])]
    cm = c.get("committee") or {}
    if cm.get("windows"):
        reasons = " · ".join(f"{e(REASON_AR.get(k, k))} {v}" for k, v in (cm.get("reasons") or {}).items() if v)
        parts += [section("قرار رئيس اللجنة"),
                  tiles([("نوافذ", cm["windows"], C["ink"]), ("حركات", cm["moves"], C["ink"]),
                         ("مرشّح للمراجعة", cm["auto_candidate"], C["green"]),
                         ("بانتظار المتخصص", cm["specialist"], C["gold"])]),
                  p(f"أسباب الامتناع: {reasons or '—'}", size=13.5, color=C["muted"])]
    d = c["decisions"]
    parts += [section("قرارات المتخصص"),
              tiles([("المجموع", d["n"], C["ink"]), ("اعتماد", d["approve"], C["green"]),
                     ("يحتاج تعديلاً", d["needs_edit"], C["warn"]), ("رفض", d["reject"], C["bad"])])]
    pr = c["progress"]
    parts += [section("التقدّم التراكمي"),
              bar("نوافذ صنّفها المصنّف", pr["classifier"], pr["windows"]),
              bar("نوافذ عمل عليها الوكيلان", pr["both"], pr["windows"]),
              bar("نوافذ قرّر فيها رئيس اللجنة", pr.get("committee", 0), pr["windows"])]
    if c.get("windows_by_tafsir"):
        parts.append(p(" · ".join(f"{e(names.get(t, t))} {n}" for t, n in c["windows_by_tafsir"].items()),
                       size=13, color=C["muted"]))
    if c.get("failures"):
        parts += [section("الإخفاقات"),
                  ul(f"#{f['task_id']} {e(AGENT_AR.get(f['agent'], f['agent']))} · {e(names.get(f['tafsir'], f['tafsir']))} "
                     f'<span dir="ltr">{e(f["window"])}</span> — <span style="color:{C["muted"]};">{e(f["last_line"])}</span>'
                     for f in c["failures"][:10])]
    if c.get("next_ar"):
        parts += [section("الخطوة التالية"), ul(e(x) for x in c["next_ar"])]
    parts.append(p(f"النماذج: المصنّف <span dir=\"ltr\">{e(c['models']['classifier'])}</span> · المدقّق "
                   f"<span dir=\"ltr\">{e(c['models']['verifier'])}</span> — أعداد توجيه وتوقيت وليست دقة.",
                   size=12.5, color=C["muted"], mt=8))
    parts.append(button("فتح التقرير في اللوحة", f"{url}/#/reports/{c['day']}" if url else ""))
    pill, color = ("فيه إخفاقات", "amber") if st["failed"] else ("يومي", "green")
    return Mail(subject, text, shell(f"التقرير اليومي — {c['day']}", "".join(parts), pill=pill, pill_color=color,
                                     preheader=f"خطوات {st['total']} · نجحت {st['done']} · فشلت {st['failed']}"),
                kind="report", inline=_logo())
