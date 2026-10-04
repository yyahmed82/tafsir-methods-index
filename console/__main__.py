"""Run the console or manage users from the command line.

    python -m console                      # serve on http://127.0.0.1:8800
    python -m console --host 0.0.0.0       # LAN (use only on a trusted network)
    python -m console create-user --email you@example.com --name "Yosri" --role super_admin
    python -m console list-users
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
    args = p.parse_args(argv)
    if args.cmd == "create-user":
        return _create_user(args)
    if args.cmd == "list-users":
        return _list_users(args)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        import uvicorn
    except ImportError:
        print("missing dependency: pip install -r console/requirements.txt", file=sys.stderr)
        return 1
    from .app import create_app
    print(f"\n  مِرْقاة — committee console:  http://{args.host}:{args.port}\n")
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info",
                proxy_headers=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
