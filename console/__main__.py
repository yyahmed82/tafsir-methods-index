"""Run the console or manage users from the command line.

    python -m console                      # serve on http://127.0.0.1:8800
    python -m console --host 0.0.0.0       # LAN (use only on a trusted network)
    python -m console create-user --email you@example.com --name "Yosri" --role super_admin
    python -m console list-users
    python -m console settings-show [section]
    python -m console settings-set smtp mode=smtp host=smtp-relay.brevo.com port=587
    python -m console mail-test --to you@example.com
"""

from __future__ import annotations

import argparse
import logging
import re
import sys


def _create_user(args: argparse.Namespace) -> int:
    from . import auth, db, settings
    db.init()
    settings.seed()
    email = auth.normalize_email(args.email)
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        print("invalid email", file=sys.stderr)
        return 2
    role = db.row("SELECT * FROM roles WHERE key=?", (args.role,))
    if role is None:
        print(f"unknown role {args.role!r}", file=sys.stderr)
        return 2
    existing = db.row("SELECT id FROM users WHERE email=?", (email,))
    if existing:
        db.execute("UPDATE users SET role_id=?, name=?, active=1 WHERE id=?",
                   (role["id"], args.name, existing["id"]))
        print(f"updated {email} → {args.role}")
    else:
        db.execute("INSERT INTO users(email,name,role_id,lang,active,created_at) VALUES"
                   " (?,?,?,?,1,?)", (email, args.name, role["id"], args.lang, db.now()))
        print(f"created {email} as {args.role}")
    db.audit("user.cli_create", target=email, detail={"role": args.role})
    return 0


def _list_users(_args: argparse.Namespace) -> int:
    from . import db
    db.init()
    for u in db.rows("SELECT u.email,u.name,u.active,r.key FROM users u JOIN roles r ON"
                     " r.id=u.role_id ORDER BY u.id"):
        print(f"{u['email']:<40} {u['key']:<20} {'active' if u['active'] else 'disabled':<9}"
              f" {u['name']}")
    return 0


_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _cli_value(section: str, key: str, raw: str):
    """Turn KEY=VALUE text into the type the settings default has."""
    from . import settings
    default = settings.DEFAULTS[section][key]
    if isinstance(default, bool):
        low = raw.strip().lower()
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
        raise settings.SettingsError(f"{section}.{key} must be true/false")
    if isinstance(default, list):
        return [x.strip() for x in raw.split(",") if x.strip()]
    return raw


def _settings_show(args: argparse.Namespace) -> int:
    import json
    from . import db, settings
    db.init()
    settings.seed()
    data = settings.get_all(redact=True)
    if args.section:
        if args.section not in data:
            print(f"unknown section {args.section!r}; one of: {', '.join(data)}", file=sys.stderr)
            return 2
        data = {args.section: data[args.section]}
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def _settings_set(args: argparse.Namespace) -> int:
    import json
    from . import db, settings
    db.init()
    settings.seed()
    if args.section not in settings.DEFAULTS:
        print(f"unknown section {args.section!r}; one of: {', '.join(settings.DEFAULTS)}",
              file=sys.stderr)
        return 2
    patch = {}
    try:
        for pair in args.pairs:
            if "=" not in pair:
                raise settings.SettingsError(f"expected KEY=VALUE, got {pair!r}")
            key, raw = pair.split("=", 1)
            key = key.strip()
            if key not in settings.DEFAULTS[args.section]:
                raise settings.SettingsError(f"unknown key {args.section}.{key}")
            if (args.section, key) in settings.SECRET_KEYS:
                raise settings.SettingsError(
                    f"{args.section}.{key} is a secret: put it in the server environment file")
            patch[key] = _cli_value(args.section, key, raw)
        result = settings.update(args.section, patch, None)
    except settings.SettingsError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(json.dumps({args.section: result}, ensure_ascii=False, indent=2))
    return 0


def _mail_test(args: argparse.Namespace) -> int:
    from . import db, mailer, settings
    db.init()
    settings.seed()
    gen = settings.get("general")
    try:
        res = mailer.send(args.to, f"اختبار البريد — {gen['team_name']}",
                          "رسالة اختبار من لوحة لجنة مِرْقاة.\nTest message from the Mirqah "
                          "committee console.\n")
    except mailer.MailError as e:
        print(f"mail failed: {e}", file=sys.stderr)
        return 1
    print(f"mail {res['status']} (mode={res['mode']}) to {args.to}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m console")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8800)
    sub = p.add_subparsers(dest="cmd")
    c = sub.add_parser("create-user", help="add or update a registered user")
    c.add_argument("--email", required=True)
    c.add_argument("--name", required=True)
    c.add_argument("--role", default="super_admin")
    c.add_argument("--lang", default="")
    sub.add_parser("list-users")
    sh = sub.add_parser("settings-show", help="print settings (secrets redacted)")
    sh.add_argument("section", nargs="?")
    st = sub.add_parser("settings-set", help="change settings: SECTION KEY=VALUE ...")
    st.add_argument("section")
    st.add_argument("pairs", nargs="+")
    mt = sub.add_parser("mail-test", help="send a test e-mail with the current SMTP settings")
    mt.add_argument("--to", required=True)
    args = p.parse_args(argv)
    if args.cmd == "create-user":
        return _create_user(args)
    if args.cmd == "list-users":
        return _list_users(args)
    if args.cmd == "settings-show":
        return _settings_show(args)
    if args.cmd == "settings-set":
        return _settings_set(args)
    if args.cmd == "mail-test":
        return _mail_test(args)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        import uvicorn
    except ImportError:
        print("missing dependency: pip install -r console/requirements.txt", file=sys.stderr)
        return 1
    from .app import create_app
    print(f"\n  مِرْقاة — committee console:  http://{args.host}:{args.port}\n")
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info",
                proxy_headers=False, server_header=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
