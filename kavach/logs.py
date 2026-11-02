"""Structured JSON logs (F11): one JSON object per line, for Loki, CloudWatch, Elastic or any log pipeline.

KAVACH_LOG_JSON=1 turns it on (the container image sets it). Each decision is logged without its arguments (they
may carry personal data): tool, verdict, rules, receipt, latency, task, tenant.
"""
from __future__ import annotations

import json
import logging
import time

log = logging.getLogger("kavach")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": round(record.created, 3), "level": record.levelname.lower(), "logger": record.name,
               "msg": record.getMessage()}
        out.update(getattr(record, "kv", {}) or {})
        if record.exc_info:
            out["error"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def setup(json_logs: bool = True, level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter() if json_logs else logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    for name in ("kavach", "uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers[:] = [handler]
        lg.setLevel(level)
        lg.propagate = False


def decision_logger(rec: dict) -> None:
    """Receipt listener: a log line per decision, no arguments."""
    b = rec["body"]
    if b.get("type") != "decision":
        return
    d = b["decision"]
    log.info("decision", extra={"kv": {"event": "decision", "receipt": rec["id"], "task": b.get("task_id"),
                                       "tenant": b.get("tenant"), "tool": d["call"]["tool"], "verdict": d["verdict"],
                                       "rules": [g["rule_id"] for g in d.get("gates", []) if g.get("outcome") != "PASS"],
                                       "latency_ms": d.get("latency_ms"), "at": time.time()}})
