"""Real connectors (E7): what an allowed action actually does outside the demo world.

KAVACH decides before the action. When KAVACH also runs the action (the gateway, not the MCP proxy or a hook), a
connector delivers it for real, and only *after* KAVACH lets it go: an email that waited out its recall window, or one
a human approved. A connector never decides anything and never sees a call KAVACH refused.

SMTP (any mail server; Mailpit in the compose stack, http://localhost:8025, catches everything for a demo):

    KAVACH_SMTP_HOST=mailpit  KAVACH_SMTP_PORT=1025
    KAVACH_SMTP_FROM=agent@infycorp.com      (default)
    KAVACH_SMTP_USER / KAVACH_SMTP_PASSWORD  (optional; with KAVACH_SMTP_STARTTLS=1 on port 587)

Each message carries X-Kavach-Outbox (the hold id) and X-Kavach-Correlation (the call id behind it), so a mail log can
be matched to KAVACH's receipts: GET /api/trace/<correlation id> shows the decision, approval and delivery.
"""
from __future__ import annotations

import json
import os
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage

from .addresses import parse_recipients


class DeliveryUncertain(Exception):
    """The connection broke after the message was handed to the mail server: it may or may not have arrived."""


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
        if msg.get("corr"):                      # the call's id: GET /api/trace/<it> shows the decision behind it
            m["X-Kavach-Correlation"] = str(msg["corr"])
        m.set_content(str(msg.get("body", "")))
        return m

    def send(self, msg: dict) -> dict:
        """Deliver one outbox message. Returns what the mail server accepted. Raises on failure (the caller records
        it; the decision and its receipt stand): DeliveryUncertain if the connection broke after the message was
        handed over (it may have arrived), any other error if the server never took it."""
        m = self.message(msg)
        rcpts = parse_recipients(msg.get("to", ""), msg.get("cc", ""), msg.get("bcc", ""))
        if not rcpts:
            raise ValueError("no recipient address")
        with self._smtp(self.host, self.port, timeout=self.timeout) as s:       # an error up to here: nothing sent
            if self.starttls:
                s.starttls()
            if self.user:
                s.login(self.user, self.password or "")
            try:
                refused = s.send_message(m, from_addr=self.sender, to_addrs=rcpts)
            except (smtplib.SMTPResponseException, smtplib.SMTPRecipientsRefused, ConnectionRefusedError):
                raise                                  # the server said no, or never let us in: it didn't take it
            except OSError as e:                       # timeout or dropped connection mid-send: we can't know
                raise DeliveryUncertain(f"{type(e).__name__}: {e}") from e
        self.sent += 1
        return {"via": f"smtp://{self.host}:{self.port}", "to": rcpts, "refused": sorted(refused or {})}


class GmailInbox:
    """A real Gmail inbox, read over IMAP with an App Password (imap.gmail.com:993). Read-only: messages are fetched
    with BODY.PEEK, so nothing is marked as read, moved or deleted. The newest `limit` messages, newest first.

    Credentials stay in KAVACH's process (the connector side): the agent only ever sees the messages, which KAVACH
    labels untrusted, since someone else wrote them.

        KAVACH_GMAIL_USER=you@gmail.com  KAVACH_GMAIL_APP_PASSWORD=...    (scripts/gmail_up.sh reads them from .env)
    """

    def __init__(self, user: str, password: str, host: str = "imap.gmail.com", port: int = 993, folder: str = "INBOX",
                 limit: int = 10, max_body: int = 4000, imap=None, timeout: float = 20.0):
        import imaplib
        self.user, self.password = user, password.replace(" ", "")
        self.host, self.port, self.folder, self.limit, self.max_body = host, int(port), folder, limit, max_body
        self.timeout = timeout                          # a stalled connection raises instead of waiting forever
        self._imap = imap or imaplib.IMAP4_SSL

    @classmethod
    def from_env(cls, environ=None) -> "GmailInbox | None":
        env = os.environ if environ is None else environ
        user, pw = env.get("KAVACH_GMAIL_USER"), env.get("KAVACH_GMAIL_APP_PASSWORD")
        return cls(user, pw, limit=int(env.get("KAVACH_GMAIL_READ_LIMIT") or 10)) if user and pw else None

    def latest(self, n: int | None = None) -> list[dict]:
        import email
        from email import policy
        from email.utils import parseaddr, parsedate_to_datetime
        n = n or self.limit
        out = []
        m = self._imap(self.host, self.port, timeout=self.timeout)
        try:
            m.login(self.user, self.password)
            m.select(self.folder, readonly=True)
            _typ, data = m.uid("search", None, "ALL")
            uids = (data[0] or b"").split()[-n:]
            for uid in reversed(uids):
                _typ, parts = m.uid("fetch", uid, "(FLAGS BODY.PEEK[])")
                raw = next((p[1] for p in parts if isinstance(p, tuple)), b"")
                flags = b" ".join(p[0] for p in parts if isinstance(p, tuple))
                msg = email.message_from_bytes(raw, policy=policy.default)
                name, addr = parseaddr(str(msg.get("From", "")))
                try:
                    when = parsedate_to_datetime(str(msg.get("Date"))).isoformat()
                except (TypeError, ValueError):
                    when = str(msg.get("Date", ""))
                out.append({"id": f"gmail-{uid.decode()}", "from": addr.lower(), "from_name": name,
                            "to": str(msg.get("To", "")), "subject": str(msg.get("Subject", "")), "date": when,
                            "unread": b"\\Seen" not in flags, "body": _text_of(msg)[:self.max_body]})
        finally:
            try:
                m.logout()
            except Exception:
                pass
        return out


def _text_of(msg) -> str:
    """The readable text of an email: its plain-text part, or its HTML part with the tags taken out."""
    import html as _html
    import re as _re
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    text = part.get_content()
    if part.get_content_type() == "text/html":
        text = _re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
        text = _html.unescape(_re.sub(r"<[^>]+>", " ", text))
    return _re.sub(r"[ \t]+", " ", _re.sub(r"\n\s*\n+", "\n\n", text)).strip()


def gmail_sender(environ=None) -> "SmtpMailer | None":
    """Sending through the same Gmail account (smtp.gmail.com:587, STARTTLS, App Password), after KAVACH's check and
    its window: what a person would see in Gmail's Sent folder."""
    env = os.environ if environ is None else environ
    user, pw = env.get("KAVACH_GMAIL_USER"), env.get("KAVACH_GMAIL_APP_PASSWORD")
    if not (user and pw):
        return None
    return SmtpMailer("smtp.gmail.com", 587, sender=user, user=user, password=pw.replace(" ", ""), starttls=True,
                      timeout=20.0)


class SandboxBank:
    """Payments KAVACH lets go go to a bank API: the demo's scripts/sandbox_bank.py, its own service with its own page,
    the way Mailpit is for email.   KAVACH_BANK_URL=http://127.0.0.1:8030

    Each transfer carries the hold id as its idempotency key, so the bank books a retry of the same payment once."""

    def __init__(self, url: str, timeout: float = 10.0):
        self.url, self.timeout = url.rstrip("/"), timeout

    @classmethod
    def from_env(cls, environ=None) -> "SandboxBank | None":
        env = os.environ if environ is None else environ
        return cls(env["KAVACH_BANK_URL"]) if env.get("KAVACH_BANK_URL") else None

    def pay(self, tx: dict) -> dict:
        body = json.dumps({"id": tx.get("hold") or tx["id"], "to_account": tx["to"], "amount": tx["amount"],
                           "currency": tx.get("currency") or "INR", "memo": str(tx.get("invoice") or tx.get("memo") or "")})
        req = urllib.request.Request(self.url + "/transfers", data=body.encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError:
            raise                                      # the bank answered no: nothing was booked
        except urllib.error.URLError as e:
            if isinstance(e.reason, ConnectionRefusedError):
                raise                                  # never reached the bank
            raise DeliveryUncertain(f"{type(e.reason).__name__}: {e.reason}") from e
        except OSError as e:                           # the answer never came: it may be booked
            raise DeliveryUncertain(f"{type(e).__name__}: {e}") from e
