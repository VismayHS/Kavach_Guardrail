"""The same tools Claude gets through KAVACH, with no KAVACH: the "without" side of the with/without comparison.

    scripts/demo_claude.sh --without-kavach          Claude Code, connected only to this server (stdio)

mail.read_inbox and crm.query read the same synthetic demo company KAVACH guards (the inbox includes the poisoned
email msg-4471 and the invoice emails). mail.send hands the message to Mailpit at once: nothing checks it, nothing
holds it, nothing can cancel it. Each message carries "X-Sent-By: no-KAVACH" so it is easy to tell apart.
"""
from __future__ import annotations

import os
import smtplib
import sys
import tempfile
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mcp.server.mcpserver import MCPServer  # noqa: E402

from kavach.addresses import parse_recipients  # noqa: E402
from kavach.environment import Environment  # noqa: E402

SMTP_HOST, SMTP_PORT = os.environ.get("KAVACH_SMTP_HOST", "127.0.0.1"), int(os.environ.get("KAVACH_SMTP_PORT", "1025"))
env = Environment(tempfile.mkdtemp(), invoice_demo=True)
s = MCPServer("plain-mail")


def deliver(to: str, subject: str, body: str) -> str:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = "agent@infycorp.com", ", ".join(parse_recipients(to)) or to, subject
    m["X-Sent-By"] = "no-KAVACH"
    m.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as smtp:
        smtp.send_message(m, to_addrs=parse_recipients(to) or [to])
    return f"Sent to {to}."


@s.tool(name="mail.read_inbox", description="Read the emails in the inbox.")
def read_inbox(unread_only: bool = True) -> list:
    return env.mail_read_inbox(unread_only)


@s.tool(name="crm.query", description="Run a read-only SQL SELECT on the CRM database (tables: customers, invoices).")
def crm_query(sql: str) -> list:
    return env.crm_query(sql)


@s.tool(name="mail.send", description="Send an email.")
def send(to: str, subject: str, body: str) -> str:
    return deliver(to, subject, body)


if __name__ == "__main__":
    s.run()
