"""Real connectors (E7): what an allowed action actually does outside the demo world.

KAVACH decides before the action. When KAVACH also runs the action (the gateway, not the MCP proxy or a hook), a
connector delivers it for real, and only *after* KAVACH lets it go: an email that waited out its recall window, or one
a human approved. A connector never decides anything and never sees a call KAVACH refused.

SMTP (any mail server; Mailpit in the compose stack, http://localhost:8025, catches everything for a demo):

    KAVACH_SMTP_HOST=mailpit  KAVACH_SMTP_PORT=1025
    KAVACH_SMTP_FROM=agent@infycorp.com      (default)
    KAVACH_SMTP_USER / KAVACH_SMTP_PASSWORD  (optional; with KAVACH_SMTP_STARTTLS=1 on port 587)

Each message carries X-Kavach-Outbox (the outbox id), so a mail log can be matched to KAVACH's receipts.
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

from .addresses import parse_recipients


class SmtpMailer:
    def __init__(self, host: str, port: int = 25, sender: str = "agent@infycorp.com", user: str | None = None,
                 password: str | None = None, starttls: bool = False, timeout: float = 10.0, smtp=smtplib.SMTP):
        self.host, self.port, self.sender = host, int(port), sender
        self.user, self.password, self.starttls, self.timeout = user, password, starttls, timeout
        self._smtp = smtp
        self.sent = 0

    @classmethod
    def from_env(cls, environ=None) -> "SmtpMailer | None":
        env = os.environ if environ is None else environ
        if not env.get("KAVACH_SMTP_HOST"):
            return None
        return cls(env["KAVACH_SMTP_HOST"], int(env.get("KAVACH_SMTP_PORT") or 25),
                   env.get("KAVACH_SMTP_FROM") or "agent@infycorp.com", env.get("KAVACH_SMTP_USER"),
                   env.get("KAVACH_SMTP_PASSWORD"), env.get("KAVACH_SMTP_STARTTLS") == "1")

    def message(self, msg: dict) -> EmailMessage:
        m = EmailMessage()
        m["From"] = self.sender
        m["To"] = ", ".join(parse_recipients(msg.get("to", ""))) or str(msg.get("to", ""))
        if msg.get("cc"):
            m["Cc"] = ", ".join(parse_recipients(msg["cc"]))
        m["Subject"] = str(msg.get("subject", ""))
        m["X-Kavach-Outbox"] = str(msg.get("id", ""))
        m.set_content(str(msg.get("body", "")))
        return m

    def send(self, msg: dict) -> dict:
        """Deliver one outbox message. Returns what the mail server accepted; raises on failure (the caller records
        the error on the outbox entry; the decision and its receipt stand)."""
        m = self.message(msg)
        rcpts = parse_recipients(msg.get("to", ""), msg.get("cc", ""), msg.get("bcc", ""))
        if not rcpts:
            raise ValueError("no recipient address")
        with self._smtp(self.host, self.port, timeout=self.timeout) as s:
            if self.starttls:
                s.starttls()
            if self.user:
                s.login(self.user, self.password or "")
            refused = s.send_message(m, from_addr=self.sender, to_addrs=rcpts)
        self.sent += 1
        return {"via": f"smtp://{self.host}:{self.port}", "to": rcpts, "refused": sorted(refused or {})}
