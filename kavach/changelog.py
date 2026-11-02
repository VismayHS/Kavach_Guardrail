"""Row-level change log for SQLite, built from temporary triggers (A5, A7).

Two uses:
  * in the staging sandbox: which rows and which columns a statement really changes (rules R16 and R26 read this
    instead of guessing from the SQL text);
  * on the live database: the before and after image of every row an action changed, so undo can take back
    exactly those rows and refuse if somebody changed them since, instead of restoring a whole-database snapshot
    over other people's work.

Temporary triggers live only on the connection that created them and are dropped right after the statement.
"""
from __future__ import annotations

import json
import sqlite3

LOG = "temp._kavach_changes"


def _tables(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT name FROM main.sqlite_master WHERE type = 'table' "
                                       "AND name NOT LIKE 'sqlite_%'")]


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA main.table_info('{table}')")]


def _json(cols: list[str], alias: str) -> str:
    return "json_object(" + ", ".join(f"'{c}', {alias}.\"{c}\"" for c in cols) + ")"


def install(conn: sqlite3.Connection, tables: list[str] | None = None) -> list[str]:
    """Create the log table and AFTER triggers on `tables` (default: every table). Returns the tables covered."""
    tables = [t for t in (tables or _tables(conn)) if t in _tables(conn)]
    conn.execute(f"CREATE TEMP TABLE IF NOT EXISTS _kavach_changes(seq INTEGER PRIMARY KEY, tbl TEXT, op TEXT, "
                 "rid INTEGER, old TEXT, new TEXT)")
    conn.execute(f"DELETE FROM {LOG}")
    for t in tables:
        cols = _columns(conn, t)
        q = t.replace('"', '""')
        conn.execute(f'CREATE TEMP TRIGGER IF NOT EXISTS "_kv_u_{q}" AFTER UPDATE ON main."{q}" BEGIN '
                     f"INSERT INTO _kavach_changes(tbl, op, rid, old, new) VALUES('{t}', 'update', NEW.rowid, "
                     f"{_json(cols, 'OLD')}, {_json(cols, 'NEW')}); END")
        conn.execute(f'CREATE TEMP TRIGGER IF NOT EXISTS "_kv_d_{q}" AFTER DELETE ON main."{q}" BEGIN '
                     f"INSERT INTO _kavach_changes(tbl, op, rid, old, new) VALUES('{t}', 'delete', OLD.rowid, "
                     f"{_json(cols, 'OLD')}, NULL); END")
        conn.execute(f'CREATE TEMP TRIGGER IF NOT EXISTS "_kv_i_{q}" AFTER INSERT ON main."{q}" BEGIN '
                     f"INSERT INTO _kavach_changes(tbl, op, rid, old, new) VALUES('{t}', 'insert', NEW.rowid, "
                     f"NULL, {_json(cols, 'NEW')}); END")
    return tables


def collect(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(f"SELECT tbl, op, rid, old, new FROM {LOG} ORDER BY seq").fetchall()
    conn.execute(f"DELETE FROM {LOG}")
    return [{"table": t, "op": op, "rowid": rid, "old": json.loads(o) if o else None,
             "new": json.loads(n) if n else None} for t, op, rid, o, n in rows]


def uninstall(conn: sqlite3.Connection) -> None:
    for (name,) in conn.execute("SELECT name FROM temp.sqlite_master WHERE type = 'trigger' "
                                "AND name LIKE '_kv_%'").fetchall():
        conn.execute(f'DROP TRIGGER IF EXISTS temp."{name}"')
    conn.execute("DROP TABLE IF EXISTS temp._kavach_changes")


def record_id(change: dict):
    """The record's id as users name it (its `id` column), else the rowid."""
    img = change["old"] or change["new"] or {}
    return img.get("id", change["rowid"])


def summarize(changes: list[dict], cap: int = 500) -> tuple[dict, dict]:
    """rows_changed {table: [ids]} for updates and deletes, columns_changed {table: [cols]} for updates."""
    rows: dict[str, list] = {}
    cols: dict[str, set] = {}
    for c in changes:
        if c["op"] in ("update", "delete"):
            ids = rows.setdefault(c["table"], [])
            if len(ids) < cap and record_id(c) not in ids:
                ids.append(record_id(c))
        if c["op"] == "update":
            diff = {k for k in c["new"] if c["old"].get(k) != c["new"].get(k)}
            cols.setdefault(c["table"], set()).update(diff)
    return rows, {t: sorted(v) for t, v in cols.items() if v}


def _current(conn, table, rowid):
    cols = _columns(conn, table)
    r = conn.execute(f'SELECT {", ".join(chr(34) + c + chr(34) for c in cols)} FROM main."{table}" WHERE rowid = ?',
                     (rowid,)).fetchone()
    return None if r is None else dict(zip(cols, tuple(r)))


def conflicts(conn: sqlite3.Connection, changes: list[dict]) -> list[str]:
    """Rows that no longer look the way the action left them (someone changed them since)."""
    out = []
    for c in changes:
        now = _current(conn, c["table"], c["rowid"])
        expected = c["new"]
        if c["op"] == "delete":
            if now is not None:
                out.append(f"{c['table']} {record_id(c)} was re-created")
        elif now != expected:
            out.append(f"{c['table']} {record_id(c)}")
    return out


def invert(conn: sqlite3.Connection, changes: list[dict]) -> None:
    """Apply the inverse of `changes`, newest first. The caller checks conflicts() and commits."""
    for c in reversed(changes):
        t, rid = c["table"], c["rowid"]
        if c["op"] == "insert":
            conn.execute(f'DELETE FROM main."{t}" WHERE rowid = ?', (rid,))
        elif c["op"] == "update":
            cols = list(c["old"])
            conn.execute(f'UPDATE main."{t}" SET {", ".join(chr(34) + k + chr(34) + " = ?" for k in cols)} '
                         "WHERE rowid = ?", [c["old"][k] for k in cols] + [rid])
        else:
            cols = list(c["old"])
            conn.execute(f'INSERT INTO main."{t}"(rowid, {", ".join(chr(34) + k + chr(34) for k in cols)}) '
                         f"VALUES(?, {', '.join('?' * len(cols))})", [rid] + [c["old"][k] for k in cols])
