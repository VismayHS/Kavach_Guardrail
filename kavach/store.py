"""Durable state: receipts, approvals and the calls waiting on them, and human labels (U9).

    KAVACH_STATE=/var/lib/kavach/kavach.db KAVACH_RECEIPT_KEY=... uvicorn kavach.server:app

One SQLite file in WAL mode, every write committed before the call returns. The receipt chain's signed checkpoint
(count + head, U10) is kept in a separate file, `<state>.anchor.json`, so truncating the database can be told apart
from a short log: in production that file belongs on write-once storage, apart from the database.

What isn't stored: the demo company itself (its database, held payments and queued emails live in memory), so after a
restart the undo windows of earlier actions are gone, and their receipts say what happened.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path

TABLES = ("approvals", "pending_calls")


class Store:
    def __init__(self, path: str | os.PathLike, anchor: str | os.PathLike | None = None):
        self.path = Path(path)
        self.anchor_path = Path(anchor) if anchor else self.path.with_suffix(".anchor.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)   # autocommit
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.execute("PRAGMA synchronous = FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS receipts(seq INTEGER PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS approvals(id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS pending_calls(id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS labels(id INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT NOT NULL);
        """)
        self.lock = threading.Lock()

    # ---------------------------------------------------------------- receipts
    def receipts(self) -> list[dict]:
        return [json.loads(b) for (b,) in self.db.execute("SELECT body FROM receipts ORDER BY seq")]

    def add_receipt(self, rec: dict) -> None:
        with self.lock:
            self.db.execute("INSERT INTO receipts(seq, body) VALUES(?, ?)", (rec["seq"], json.dumps(rec, default=str)))

    def read_anchor(self) -> dict | None:
        try:
            return json.loads(self.anchor_path.read_text())
        except FileNotFoundError:
            return None

    def write_anchor(self, anchor: dict) -> None:
        tmp = self.anchor_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(anchor))
        os.replace(tmp, self.anchor_path)                  # atomic: a crash leaves the old checkpoint or the new one

    # ---------------------------------------------------------------- approvals and the calls waiting on them
    def put(self, table: str, key: str, obj: dict) -> None:
        assert table in TABLES
        with self.lock:
            self.db.execute(f"INSERT OR REPLACE INTO {table}(id, body) VALUES(?, ?)", (key, json.dumps(obj, default=str)))

    def delete(self, table: str, key: str) -> None:
        assert table in TABLES
        with self.lock:
            self.db.execute(f"DELETE FROM {table} WHERE id = ?", (key,))

    def all(self, table: str) -> dict[str, dict]:
        assert table in TABLES
        return {k: json.loads(b) for k, b in self.db.execute(f"SELECT id, body FROM {table}")}

    # ---------------------------------------------------------------- human decisions as labels (U11)
    def add_label(self, label: dict) -> None:
        with self.lock:
            self.db.execute("INSERT INTO labels(body) VALUES(?)", (json.dumps(label, default=str),))

    def labels(self) -> list[dict]:
        return [json.loads(b) for (b,) in self.db.execute("SELECT body FROM labels ORDER BY id")]
