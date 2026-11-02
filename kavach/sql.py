"""What a SQL statement will do, as reported by SQLite's own compiler.

Regexes on the statement text are fooled by a leading comment or a CTE
(`/* x */ DELETE ...`, `WITH t AS (...) DELETE ...`). SQLite calls an authorizer
for every operation while it compiles a statement, so compiling it under EXPLAIN
lists the real operations without running anything.
"""
from __future__ import annotations

import re
import sqlite3

_WRITE = {sqlite3.SQLITE_INSERT: "insert", sqlite3.SQLITE_UPDATE: "update", sqlite3.SQLITE_DELETE: "delete"}
_DDL = {sqlite3.SQLITE_DROP_TABLE: "drop", sqlite3.SQLITE_DROP_TEMP_TABLE: "drop", sqlite3.SQLITE_DROP_VIEW: "drop",
        sqlite3.SQLITE_DROP_INDEX: "drop", sqlite3.SQLITE_DROP_TRIGGER: "drop", sqlite3.SQLITE_ALTER_TABLE: "alter"}
_CREATE = {sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_CREATE_TEMP_TABLE, sqlite3.SQLITE_CREATE_VIEW,
           sqlite3.SQLITE_CREATE_INDEX, sqlite3.SQLITE_CREATE_TRIGGER}
_COMMENT = re.compile(r"/\*.*?\*/|--[^\n]*", re.S)


def classify(conn: sqlite3.Connection, sql: str) -> dict:
    """Compile `sql` on `conn` (never executed) and return its operations and tables."""
    ops: set[str] = set()
    tables: set[str] = set()
    written: set[str] = set()      # tables the statement changes or drops (not ones it only reads)

    def record(action, arg1, arg2, _db, _src):
        table = arg2 if action == sqlite3.SQLITE_ALTER_TABLE else arg1
        if action in _WRITE:
            ops.add(_WRITE[action])
        elif action in _DDL:
            ops.add(_DDL[action])
        elif action in _CREATE:
            ops.add("create")
        if table and action in (*_WRITE, *_DDL, sqlite3.SQLITE_READ) and not str(table).startswith("sqlite_"):
            tables.add(str(table).lower())
            if action != sqlite3.SQLITE_READ:
                written.add(str(table).lower())
        return sqlite3.SQLITE_OK

    error = None
    conn.set_authorizer(record)
    try:
        conn.execute("EXPLAIN " + sql).fetchall()
    except (sqlite3.Error, sqlite3.Warning) as e:   # invalid SQL, or more than one statement
        error = str(e)
    finally:
        conn.set_authorizer(None)
    bare = _COMMENT.sub(" ", sql)
    return {"ops": sorted(ops), "tables": sorted(tables), "tables_written": sorted(written), "error": error,
            "writes": bool(ops & {"insert", "update", "delete", "create"}),
            "ddl": bool(ops & {"drop", "alter"}),
            # ponytail: a WHERE inside a CTE also counts; the sandbox row count (R10) still catches bulk changes
            "no_where": bool(ops & {"update", "delete"}) and not re.search(r"\bWHERE\b", bare, re.I)}
