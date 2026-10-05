"""SQLite storage for the console (users, roles, sessions, tasks, reports…).

The database lives in ``console/var/console.db`` (gitignored). It holds console
state only — never tafsir text, tags or approvals of record.
"""

from __future__ import annotations

import contextvars
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from . import config

_LOCK = threading.RLock()
_DB_PATH: Path | None = None
# "live" or "demo". In demo mode connections open demo.db with the live database
# attached: tables that demo.db does not have (settings, roles, languages, sessions…)
# resolve to the live ones, while tasks, steps, reports, decisions, audit and the
# demo people come from the simulation. See console/demo.py.
_MODE: contextvars.ContextVar[str] = contextvars.ContextVar("mirqah_db_mode", default="live")

DEMO_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, email TEXT NOT NULL, name TEXT NOT NULL, role_key TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, title_ar TEXT NOT NULL, params TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued', created_by INTEGER, created_at REAL NOT NULL,
  started_at REAL, finished_at REAL, total_steps INTEGER NOT NULL DEFAULT 0,
  done_steps INTEGER NOT NULL DEFAULT 0, failed_steps INTEGER NOT NULL DEFAULT 0,
  skipped_steps INTEGER NOT NULL DEFAULT 0, cancel_requested INTEGER NOT NULL DEFAULT 0, error TEXT
);
CREATE TABLE IF NOT EXISTS task_steps (
  id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, seq INTEGER NOT NULL, agent TEXT NOT NULL,
  tafsir TEXT NOT NULL, window TEXT NOT NULL, model TEXT, status TEXT NOT NULL DEFAULT 'queued',
  started_at REAL, finished_at REAL, duration_ms INTEGER, exit_code INTEGER, result TEXT,
  output_tail TEXT, variant TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS steps_task ON task_steps(task_id, seq);
CREATE INDEX IF NOT EXISTS steps_finished ON task_steps(finished_at);
CREATE INDEX IF NOT EXISTS steps_status ON task_steps(status);
CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY, day TEXT UNIQUE NOT NULL, generated_at REAL NOT NULL,
  generated_by INTEGER, content TEXT NOT NULL, mailed_at REAL
);
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY, tafsir TEXT NOT NULL, window TEXT NOT NULL, annotator TEXT NOT NULL,
  move_id TEXT NOT NULL, decision TEXT NOT NULL, compared_with_source INTEGER NOT NULL DEFAULT 0,
  note TEXT NOT NULL DEFAULT '', user_id INTEGER NOT NULL, created_at REAL NOT NULL,
  teach TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS decisions_unit ON decisions(tafsir, window, annotator, move_id);
CREATE INDEX IF NOT EXISTS decisions_at ON decisions(created_at);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY, at REAL NOT NULL, user_id INTEGER, action TEXT NOT NULL, target TEXT,
  detail TEXT, ip TEXT
);
CREATE INDEX IF NOT EXISTS audit_at ON audit(at);
CREATE TABLE IF NOT EXISTS demo_units (
  tafsir TEXT NOT NULL, window TEXT NOT NULL, ayah TEXT NOT NULL, ayah_number INTEGER NOT NULL,
  span_count INTEGER NOT NULL, chars INTEGER NOT NULL, moves INTEGER NOT NULL,
  auto_candidate INTEGER NOT NULL, specialist INTEGER NOT NULL, flags INTEGER NOT NULL,
  reasons TEXT NOT NULL, classifier_at REAL, verifier_at REAL, committee_at REAL,
  PRIMARY KEY (tafsir, window)
);
CREATE TABLE IF NOT EXISTS demo_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assignments (
  tafsir TEXT NOT NULL, window TEXT NOT NULL, user_id INTEGER NOT NULL, assigned_at REAL NOT NULL,
  assigned_by INTEGER, status TEXT NOT NULL DEFAULT 'open', done_at REAL, last_reminder_at REAL,
  PRIMARY KEY (tafsir, window)
);
CREATE TABLE IF NOT EXISTS publications (
  id INTEGER PRIMARY KEY, version INTEGER UNIQUE NOT NULL, created_at REAL NOT NULL,
  created_by INTEGER, note TEXT NOT NULL DEFAULT '', units INTEGER NOT NULL DEFAULT 0,
  sha256 TEXT NOT NULL DEFAULT '', path TEXT NOT NULL DEFAULT '', live INTEGER NOT NULL DEFAULT 0,
  made_live_at REAL, made_live_by INTEGER, summary TEXT NOT NULL DEFAULT ''
);
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS roles (
  id INTEGER PRIMARY KEY,
  key TEXT UNIQUE NOT NULL,
  name_ar TEXT NOT NULL,
  name_en TEXT NOT NULL,
  description_ar TEXT NOT NULL DEFAULT '',
  system INTEGER NOT NULL DEFAULT 0,
  permissions TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  role_id INTEGER NOT NULL REFERENCES roles(id),
  lang TEXT NOT NULL DEFAULT '',
  active INTEGER NOT NULL DEFAULT 1,
  created_at REAL NOT NULL,
  created_by INTEGER,
  last_login_at REAL
);
CREATE TABLE IF NOT EXISTS otp_codes (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL,
  code_hash TEXT NOT NULL,
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  used INTEGER NOT NULL DEFAULT 0,
  ip TEXT
);
CREATE INDEX IF NOT EXISTS otp_email ON otp_codes(email, created_at);
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY,
  token_hash TEXT UNIQUE NOT NULL,
  user_id INTEGER NOT NULL REFERENCES users(id),
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL,
  ip TEXT,
  user_agent TEXT,
  revoked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at REAL,
  updated_by INTEGER
);
CREATE TABLE IF NOT EXISTS languages (
  code TEXT PRIMARY KEY,
  name_native TEXT NOT NULL,
  name_en TEXT NOT NULL,
  dir TEXT NOT NULL DEFAULT 'ltr',
  enabled INTEGER NOT NULL DEFAULT 1,
  is_default INTEGER NOT NULL DEFAULT 0,
  sort INTEGER NOT NULL DEFAULT 100
);
CREATE TABLE IF NOT EXISTS translations (
  lang TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  PRIMARY KEY (lang, key)
);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,
  title_ar TEXT NOT NULL,
  params TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  created_by INTEGER,
  created_at REAL NOT NULL,
  started_at REAL,
  finished_at REAL,
  total_steps INTEGER NOT NULL DEFAULT 0,
  done_steps INTEGER NOT NULL DEFAULT 0,
  failed_steps INTEGER NOT NULL DEFAULT 0,
  skipped_steps INTEGER NOT NULL DEFAULT 0,
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  error TEXT
);
CREATE TABLE IF NOT EXISTS task_steps (
  id INTEGER PRIMARY KEY,
  task_id INTEGER NOT NULL REFERENCES tasks(id),
  seq INTEGER NOT NULL,
  agent TEXT NOT NULL,
  tafsir TEXT NOT NULL,
  window TEXT NOT NULL,
  model TEXT,
  status TEXT NOT NULL DEFAULT 'queued',
  started_at REAL,
  finished_at REAL,
  duration_ms INTEGER,
  exit_code INTEGER,
  result TEXT,
  output_tail TEXT
);
CREATE INDEX IF NOT EXISTS steps_task ON task_steps(task_id, seq);
CREATE INDEX IF NOT EXISTS steps_finished ON task_steps(finished_at);
CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY,
  day TEXT UNIQUE NOT NULL,
  generated_at REAL NOT NULL,
  generated_by INTEGER,
  content TEXT NOT NULL,
  mailed_at REAL
);
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY,
  tafsir TEXT NOT NULL,
  window TEXT NOT NULL,
  annotator TEXT NOT NULL,
  move_id TEXT NOT NULL,
  decision TEXT NOT NULL,
  compared_with_source INTEGER NOT NULL DEFAULT 0,
  note TEXT NOT NULL DEFAULT '',
  user_id INTEGER NOT NULL REFERENCES users(id),
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS decisions_unit ON decisions(tafsir, window, annotator, move_id);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY,
  at REAL NOT NULL,
  user_id INTEGER,
  action TEXT NOT NULL,
  target TEXT,
  detail TEXT,
  ip TEXT
);
CREATE INDEX IF NOT EXISTS audit_at ON audit(at);
-- a user may hold several roles; users.role_id stays the primary (shown first)
CREATE TABLE IF NOT EXISTS user_roles (
  user_id INTEGER NOT NULL REFERENCES users(id),
  role_id INTEGER NOT NULL REFERENCES roles(id),
  PRIMARY KEY (user_id, role_id)
);
-- the committee chair gives each reviewed window (both blind versions) to one specialist
CREATE TABLE IF NOT EXISTS assignments (
  tafsir TEXT NOT NULL,
  window TEXT NOT NULL,
  user_id INTEGER NOT NULL REFERENCES users(id),
  assigned_at REAL NOT NULL,
  assigned_by INTEGER,
  status TEXT NOT NULL DEFAULT 'open',
  done_at REAL,
  last_reminder_at REAL,
  PRIMARY KEY (tafsir, window)
);
CREATE INDEX IF NOT EXISTS assignments_user ON assignments(user_id, status);
-- what mirqah.app shows: versioned snapshots of approved units; one is live
CREATE TABLE IF NOT EXISTS publications (
  id INTEGER PRIMARY KEY,
  version INTEGER UNIQUE NOT NULL,
  created_at REAL NOT NULL,
  created_by INTEGER,
  note TEXT NOT NULL DEFAULT '',
  units INTEGER NOT NULL DEFAULT 0,
  sha256 TEXT NOT NULL DEFAULT '',
  path TEXT NOT NULL DEFAULT '',
  live INTEGER NOT NULL DEFAULT 0,
  made_live_at REAL,
  made_live_by INTEGER,
  summary TEXT NOT NULL DEFAULT ''
);
-- small scheduler state: last reminder day, last alert time…
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outbox (
  id INTEGER PRIMARY KEY,
  at REAL NOT NULL,
  to_addr TEXT NOT NULL,
  subject TEXT NOT NULL,
  body TEXT NOT NULL,
  html TEXT,
  mode TEXT NOT NULL,
  status TEXT NOT NULL,
  error TEXT
);
"""


def init(db_path: Path | None = None) -> Path:
    """Open (and create) the database. Safe to call more than once."""
    global _DB_PATH
    config.ensure_dirs()
    _DB_PATH = Path(db_path) if db_path else (config.VAR_DIR / "console.db")
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as con:
        con.executescript(SCHEMA)
        _migrate(con)
    # a simulation built by an older release gets the same additive columns, otherwise
    # demo mode fails with "no such column" after an upgrade (dashboard, tasks)
    if demo_path().exists():
        init_demo()
    return _DB_PATH


def _add_columns(con: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    if not cols:
        return
    for name, decl in columns.items():
        if name not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


# step arm (''=baseline, 'profile'=arm B) and the reviewer's lesson for the agents
_STEP_DECISION_COLUMNS = {
    # attempt/not_before/last_error: automatic retries; alerted_at: failure mail sent;
    # interruptions: killed by a restart (not the step's fault, no attempt used)
    "task_steps": {"variant": "TEXT NOT NULL DEFAULT ''",
                   "attempt": "INTEGER NOT NULL DEFAULT 1",
                   "not_before": "REAL",
                   "last_error": "TEXT",
                   "alerted_at": "REAL",
                   "interruptions": "INTEGER NOT NULL DEFAULT 0"},
    "decisions": {"teach": "TEXT NOT NULL DEFAULT ''"},
    # a retry is part of its original task: retry_of = the attempt it retried,
    # origin_id = the original task (NULL on the original itself)
    "tasks": {"retry_of": "INTEGER", "origin_id": "INTEGER"},
}


def backfill_task_chain(con: sqlite3.Connection) -> int:
    """Link retries written by older releases (``params.retry_of`` only) to their
    original task. Idempotent; returns how many rows changed."""
    parent: dict[int, int | None] = {}
    current: dict[int, tuple] = {}
    for r in con.execute("SELECT id, params, retry_of, origin_id FROM tasks").fetchall():
        rid = r[2]
        if rid is None:
            p = loads(r[1], {}) or {}
            rid = p.get("retry_of") if isinstance(p, dict) else None
        try:
            parent[int(r[0])] = int(rid) if rid else None
        except (TypeError, ValueError):
            parent[int(r[0])] = None
        current[int(r[0])] = (r[2], r[3])
    changed = 0
    for tid, p in parent.items():
        if p is None:
            continue
        root, seen = p, {tid}
        while parent.get(root) and root not in seen:
            seen.add(root)
            root = parent[root]
        if current[tid] != (p, root):
            con.execute("UPDATE tasks SET retry_of=?, origin_id=? WHERE id=?", (p, root, tid))
            changed += 1
    return changed


def _migrate(con: sqlite3.Connection) -> None:
    """Additive column changes for databases created by older releases."""
    _add_columns(con, "outbox", {"html": "TEXT"})
    for table, columns in _STEP_DECISION_COLUMNS.items():
        _add_columns(con, table, columns)
    con.execute("CREATE INDEX IF NOT EXISTS tasks_origin ON tasks(origin_id)")
    backfill_task_chain(con)
    # every user's primary role is also one of their roles
    con.execute("INSERT OR IGNORE INTO user_roles(user_id, role_id) SELECT id, role_id FROM users")


def demo_path() -> Path:
    if _DB_PATH is None:
        raise RuntimeError("db.init() was not called")
    return _DB_PATH.with_name("demo.db")


def mode() -> str:
    return _MODE.get()


@contextmanager
def use(new_mode: str) -> Iterator[None]:
    """Run the block against the live database or the simulation (demo.db)."""
    token = _MODE.set("demo" if new_mode == "demo" else "live")
    try:
        yield
    finally:
        _MODE.reset(token)


def init_demo() -> Path:
    path = demo_path()
    con = sqlite3.connect(path, timeout=30)
    try:
        con.execute("PRAGMA journal_mode = WAL")
        con.executescript(DEMO_SCHEMA)
        for table, columns in _STEP_DECISION_COLUMNS.items():
            _add_columns(con, table, columns)
        con.execute("CREATE INDEX IF NOT EXISTS tasks_origin ON tasks(origin_id)")
        backfill_task_chain(con)
        con.commit()
    finally:
        con.close()
    return path


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    if _DB_PATH is None:
        raise RuntimeError("db.init() was not called")
    with _LOCK:
        if _MODE.get() == "demo":
            con = sqlite3.connect(demo_path(), timeout=30)
            con.execute("ATTACH DATABASE ? AS live", (str(_DB_PATH),))
        else:
            con = sqlite3.connect(_DB_PATH, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA journal_mode = WAL")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()


def now() -> float:
    return time.time()


def rows(sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
    with connect() as con:
        return [dict(r) for r in con.execute(sql, params).fetchall()]


def row(sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
    with connect() as con:
        r = con.execute(sql, params).fetchone()
        return dict(r) if r else None


def execute(sql: str, params: tuple | list = ()) -> int:
    with connect() as con:
        cur = con.execute(sql, params)
        return int(cur.lastrowid or 0)


def scalar(sql: str, params: tuple | list = ()) -> Any:
    with connect() as con:
        r = con.execute(sql, params).fetchone()
        return r[0] if r else None


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads(value: str | None, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


# A user's roles: the user_roles rows plus the primary users.role_id (always one of them,
# even for rows written by older code or tests). Use in FROM/JOIN as a table.
USER_ROLES = "(SELECT user_id, role_id FROM user_roles UNION SELECT id, role_id FROM users)"


def meta_get(key: str, default: Any = None) -> Any:
    return loads(scalar("SELECT value FROM meta WHERE key=?", (key,)), default)


def meta_set(key: str, value: Any) -> None:
    execute("INSERT INTO meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET"
            " value=excluded.value", (key, dumps(value)))


def audit(action: str, *, user_id: int | None = None, target: str | None = None,
          detail: Any = None, ip: str | None = None) -> None:
    execute(
        "INSERT INTO audit(at, user_id, action, target, detail, ip) VALUES (?,?,?,?,?,?)",
        (now(), user_id, action, target, dumps(detail) if detail is not None else None, ip),
    )
