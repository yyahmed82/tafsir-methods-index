"""Run the console or manage users from the command line.

    python -m console                      # serve on http://127.0.0.1:8800
    python -m console --host 0.0.0.0       # LAN (use only on a trusted network)
    python -m console create-user --email you@example.com --name "Yosri" --role super_admin [--notify]
    python -m console list-users
    python -m console settings-show [section]
    python -m console settings-set smtp mode=smtp host=smtp-relay.brevo.com port=587
    python -m console mail-test --to you@example.com
    python -m console demo-seed [--months 12]   # simulated year for demo mode (separate database)
    python -m console demo-status | demo-clear
    python -m console llm-probe                 # can the console reach the model server?
"""

from __future__ import annotations

import argparse
import logging
import re
import sys


def _create_user(args: argparse.Namespace) -> int:
    """Add a user, or give an existing one more roles (roles are added, never removed here)."""
    from . import auth, config, db, settings
    db.init()
    settings.seed()
    email = auth.normalize_email(args.email)
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        print("invalid email", file=sys.stderr)
        return 2
    keys = [k.strip() for k in (args.role or "").split(",") if k.strip()]
    roles = []
    for k in keys:
        role = db.row("SELECT * FROM roles WHERE key=?", (k,))
        if role is None:
            print(f"unknown role {k!r}", file=sys.stderr)
            return 2
        roles.append(role)
    if not roles:
        print("give at least one role with --role", file=sys.stderr)
        return 2
    existing = db.row("SELECT id FROM users WHERE email=?", (email,))
    if existing:
        uid = existing["id"]
        db.execute("UPDATE users SET name=?, active=1 WHERE id=?", (args.name, uid))
    else:
        uid = db.execute("INSERT INTO users(email,name,role_id,lang,active,created_at) VALUES"
                         " (?,?,?,?,1,?)", (email, args.name, roles[0]["id"], args.lang, db.now()))
    with db.connect() as con:
        con.executemany("INSERT OR IGNORE INTO user_roles(user_id, role_id) VALUES (?,?)",
                        [(uid, r["id"]) for r in roles])
        held = [r[0] for r in con.execute(
            f"SELECT r.key FROM {db.USER_ROLES} ur JOIN roles r ON r.id=ur.role_id"
            " WHERE ur.user_id=?",
            (uid,)).fetchall()]
        order = {k: i for i, k in enumerate(config.ROLE_ORDER)}
        primary = sorted(held, key=lambda k: order.get(k, 99))[0]
        con.execute("UPDATE users SET role_id=(SELECT id FROM roles WHERE key=?) WHERE id=?",
                    (primary, uid))
    print(f"{'updated' if existing else 'created'} {email} → {', '.join(sorted(held))}")
    db.audit("user.cli_create", target=email, detail={"roles": sorted(held)})
    if args.notify:
        from . import mailer, mailtpl
        try:
            mailer.send_mail(email, mailtpl.welcome(
                args.name, email, " + ".join(r["name_ar"] for r in roles),
                " ".join(r["description_ar"] for r in roles), None))
            print(f"welcome mail sent to {email}")
        except mailer.MailError as e:
            print(f"welcome mail failed: {e}", file=sys.stderr)
    return 0


def _list_users(_args: argparse.Namespace) -> int:
    from . import db
    db.init()
    for u in db.rows("SELECT u.id,u.email,u.name,u.active FROM users u ORDER BY u.id"):
        keys = ",".join(r["key"] for r in db.rows(
            f"SELECT r.key FROM {db.USER_ROLES} ur JOIN roles r ON r.id=ur.role_id"
            " WHERE ur.user_id=? ORDER BY r.id", (u["id"],)))
        print(f"{u['email']:<40} {keys:<34} {'active' if u['active'] else 'disabled':<9}"
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
    from . import db, mailer, mailtpl, settings
    db.init()
    settings.seed()
    try:
        res = mailer.send_mail(args.to, mailtpl.test(args.to))
    except mailer.MailError as e:
        print(f"mail failed: {e}", file=sys.stderr)
        return 1
    print(f"mail {res['status']} (mode={res['mode']}) to {args.to}")
    return 0


def _llm_probe(_args: argparse.Namespace) -> int:
    import json
    from . import config, db, pipeline, settings
    db.init()
    settings.seed()
    out = pipeline.probe_llm()
    out["work_root"] = str(config.work_root())
    print(json.dumps(out, ensure_ascii=False, indent=2))
    ok = out.get("reachable") and out.get("classifier_installed") and out.get("verifier_installed")
    print("\nOK: the console can reach both models." if ok else
          "\nNOT READY: check the Mac is awake, Tailscale is up and llm.base_url is right.")
    return 0 if ok else 1


def _demo(args: argparse.Namespace) -> int:
    import json
    from . import db, demo, settings
    db.init()
    settings.seed()
    if args.cmd == "demo-clear":
        demo.clear()
        db.audit("demo.clear", detail={"via": "cli"})
        print("demo data removed")
        return 0
    if args.cmd == "demo-seed":
        months = args.months or settings.get("demo")["months"]
        try:
            out = demo.seed(months)
        except RuntimeError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        db.audit("demo.seed", detail={"months": months, "via": "cli"})
    else:
        out = demo.status()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m console")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8800)
    sub = p.add_subparsers(dest="cmd")
    c = sub.add_parser("create-user", help="add or update a registered user")
    c.add_argument("--email", required=True)
    c.add_argument("--name", required=True)
    c.add_argument("--role", default="super_admin",
                   help="one role or several, comma-separated (e.g. super_admin,specialist);"
                        " an existing user keeps the roles they have and gains these")
    c.add_argument("--lang", default="")
    c.add_argument("--notify", action="store_true", help="e-mail a welcome message with the sign-in steps")
    sub.add_parser("list-users")
    sh = sub.add_parser("settings-show", help="print settings (secrets redacted)")
    sh.add_argument("section", nargs="?")
    st = sub.add_parser("settings-set", help="change settings: SECTION KEY=VALUE ...")
    st.add_argument("section")
    st.add_argument("pairs", nargs="+")
    mt = sub.add_parser("mail-test", help="send a test e-mail with the current SMTP settings")
    mt.add_argument("--to", required=True)
    ds = sub.add_parser("demo-seed", help="build the simulated year shown in demo mode")
    ds.add_argument("--months", type=int, default=0, help="3–18 (default: Settings → demo)")
    sub.add_parser("demo-status")
    sub.add_parser("demo-clear")
    sub.add_parser("llm-probe", help="check the model server (base_url, models installed)")
    args = p.parse_args(argv)
    if args.cmd == "llm-probe":
        return _llm_probe(args)
    if args.cmd in ("demo-seed", "demo-status", "demo-clear"):
        return _demo(args)
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
