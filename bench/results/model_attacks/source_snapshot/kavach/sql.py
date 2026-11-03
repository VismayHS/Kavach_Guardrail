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

# The sandbox runs statements for real, on a copy of the database. These operations reach past that copy (a file on
# disk, the connection's settings, persistent code), so they are refused while any agent statement compiles or runs.
# VACUUM INTO and ATTACH both ask SQLite for SQLITE_ATTACH before anything happens; a trigger is code that runs later.
_FORBIDDEN = {sqlite3.SQLITE_ATTACH: "attach a database (VACUUM INTO, ATTACH)", sqlite3.SQLITE_DETACH: "detach",
              sqlite3.SQLITE_PRAGMA: "change connection settings (PRAGMA)",
              sqlite3.SQLITE_CREATE_TRIGGER: "create a trigger", sqlite3.SQLITE_CREATE_TEMP_TRIGGER: "create a trigger"}
_FORBIDDEN_FUNCTIONS = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer"}
# Statement kinds each tool runs (first keyword). A second, coarser check: the authorizer above is the one that holds.
WRITE_STATEMENTS = {"insert", "update", "delete", "replace", "with", "create", "drop", "alter"}
READ_STATEMENTS = {"select", "with"}
MAX_SQL_CHARS = 20000


def statement_kind(sql: str) -> str:
    """The statement's first keyword, ignoring comments and leading whitespace."""
    m = re.match(r"\s*([A-Za-z]+)", _COMMENT.sub(" ", sql))
    return m.group(1).lower() if m else ""


def forbidden(action: int, arg1, arg2) -> str | None:
    """Why an authorizer event is refused for agent SQL, or None if it's allowed."""
    if action in _FORBIDDEN:
        return _FORBIDDEN[action]
    if action == sqlite3.SQLITE_FUNCTION and str(arg2 or "").lower() in _FORBIDDEN_FUNCTIONS:
        return f"call {arg2}()"
    return None


def guard(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Lock a connection down for agent SQL: defensive mode, no attached databases, bounded statement size, and an
    authorizer that stays installed (until unguard) so forbidden operations fail when they compile."""
    conn.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, True)
    conn.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
    conn.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, MAX_SQL_CHARS)
    conn.set_authorizer(lambda a, x, y, _db, _src: sqlite3.SQLITE_DENY if forbidden(a, x, y) else sqlite3.SQLITE_OK)
    return conn


def unguard(conn: sqlite3.Connection) -> None:
    conn.set_authorizer(None)


def classify(conn: sqlite3.Connection, sql: str) -> dict:
    """Compile `sql` on `conn` (never executed) and return its operations and tables."""
    ops: set[str] = set()
    tables: set[str] = set()
    written: set[str] = set()      # tables the statement changes or drops (not ones it only reads)

    def record(action, arg1, arg2, _db, _src):
        why = forbidden(action, arg1, arg2)
        if why:
            ops.add("forbidden")
            return sqlite3.SQLITE_DENY
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
        conn.set_authorizer(None)    # callers re-guard: classify swaps in its own recording authorizer
    bare = _COMMENT.sub(" ", sql)
    return {"ops": sorted(ops), "tables": sorted(tables), "tables_written": sorted(written), "error": error,
            "writes": bool(ops & {"insert", "update", "delete", "create"}),
            "ddl": bool(ops & {"drop", "alter"}),
            # ponytail: a WHERE inside a CTE also counts; the sandbox row count (R10) still catches bulk changes
            "no_where": bool(ops & {"update", "delete"}) and not re.search(r"\bWHERE\b", bare, re.I)}
