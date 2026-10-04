#!/usr/bin/env python3
"""Read, write and run with the server's environment files (/etc/mirqah/*.env).

The files use the systemd ``EnvironmentFile`` format. To keep systemd, this
script and the shell in exact agreement, values may not contain quotes,
backslashes, ``$``, backticks or newlines.

    envfile.py get  FILE KEY              print a value ("" if missing)
    envfile.py set  FILE KEY              read the value from stdin and store it
    envfile.py exec FILE --user U --cwd D -- CMD...
                                          run CMD as user U in D with the file's variables
"""

from __future__ import annotations

import os
import re
import sys

KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
BAD_VALUE = re.compile(r"[\"'\\$`\r\n]")


def parse(path: str) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        return out
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if KEY_RE.match(key):
            out[key] = value
    return out


def set_value(path: str, key: str, value: str) -> None:
    if not KEY_RE.match(key):
        raise SystemExit(f"bad key {key!r}")
    if BAD_VALUE.search(value):
        raise SystemExit(f"{key}: value may not contain quotes, backslash, $, ` or newlines")
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        lines = []
    new = f'{key}="{value}"'
    active = re.compile(rf"^\s*{re.escape(key)}=")
    commented = re.compile(rf"^\s*#\s*{re.escape(key)}=")
    hits = [i for i, line in enumerate(lines) if active.match(line)]
    if hits:
        lines[hits[0]] = new
        lines = [line for i, line in enumerate(lines) if i not in hits[1:]]
    else:
        hint = next((i for i, line in enumerate(lines) if commented.match(line)), None)
        if hint is None:
            lines.append(new)
        else:
            lines[hint] = new
    tmp = f"{path}.tmp"
    st = os.stat(path) if os.path.exists(path) else None
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    if st is not None:
        os.chown(tmp, st.st_uid, st.st_gid)
        os.chmod(tmp, st.st_mode & 0o777)
    os.replace(tmp, path)


def run_as(path: str, user: str, cwd: str, cmd: list[str]) -> None:
    import pwd
    env = {k: v for k, v in os.environ.items()
           if k in ("PATH", "LANG", "LC_ALL", "TERM", "TZ")}
    env.setdefault("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
    env.setdefault("LANG", "C.UTF-8")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(parse(path))
    pw = pwd.getpwnam(user)
    env["HOME"] = pw.pw_dir
    os.chdir(cwd)
    if os.getuid() != pw.pw_uid:
        os.initgroups(user, pw.pw_gid)
        os.setgid(pw.pw_gid)
        os.setuid(pw.pw_uid)
    os.execvpe(cmd[0], cmd, env)


def main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[0] == "get":
        print(parse(argv[1]).get(argv[2], ""))
        return 0
    if len(argv) == 3 and argv[0] == "set":
        value = sys.stdin.readline().rstrip("\r\n")
        set_value(argv[1], argv[2], value)
        return 0
    if len(argv) >= 2 and argv[0] == "exec":
        path, rest = argv[1], argv[2:]
        user, cwd = "mirqah", "/"
        while rest and rest[0] != "--":
            if rest[0] == "--user" and len(rest) > 1:
                user, rest = rest[1], rest[2:]
            elif rest[0] == "--cwd" and len(rest) > 1:
                cwd, rest = rest[1], rest[2:]
            else:
                raise SystemExit(f"unknown option {rest[0]!r}")
        if not rest or rest[0] != "--" or len(rest) < 2:
            raise SystemExit("usage: envfile.py exec FILE --user U --cwd D -- CMD...")
        run_as(path, user, cwd, rest[1:])
        return 0  # not reached
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
