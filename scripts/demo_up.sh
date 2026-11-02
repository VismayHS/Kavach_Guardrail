#!/usr/bin/env bash
# Start the live demo: Mailpit (a local inbox that catches every email) and KAVACH (console, API and /mcp for Claude).
#
#   scripts/demo_up.sh          console http://127.0.0.1:8000   inbox http://127.0.0.1:8025   MCP http://127.0.0.1:8000/mcp
#   scripts/demo_reset.sh       stop KAVACH, empty the inbox, forget the demo state
#
# An email KAVACH lets through waits KAVACH_MAIL_HOLD_S seconds (30 here) before it is handed to Mailpit; Cancel in
# the console's Undo windows page stops it. KAVACH's state (receipts, waiting emails) is kept in .kavach/demo.db, so
# a restart mid-wait neither loses nor re-sends anything. Needs: brew install mailpit (macOS) or any Mailpit binary.
set -euo pipefail
cd "$(dirname "$0")/.."
PORT=${PORT:-8000}
mkdir -p .kavach

# Optional real Gmail: with KAVACH_GMAIL_USER and KAVACH_GMAIL_APP_PASSWORD (environment, or ../.env, which stays out
# of git), Mailpit forwards the emails KAVACH lets out to real Gmail, but only those addressed to KAVACH_GMAIL_TO
# (in ../.env; default: the sending account itself): an address a judge types reaches Mailpit only. A cancelled email never reaches
# Mailpit, so it never reaches Gmail. The password goes only into .kavach/gmail-relay.yaml (owner-only), for Mailpit:
# not into KAVACH's environment, and never into Claude's.
ENV_FILE=${KAVACH_ENV_FILE:-../.env}
envval() { [ -f "$ENV_FILE" ] && sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$ENV_FILE" | tail -1 | tr -d "\"'"; }
GMAIL_USER=${KAVACH_GMAIL_USER:-$(envval KAVACH_GMAIL_USER || true)}
GMAIL_PASS=${KAVACH_GMAIL_APP_PASSWORD:-$(envval KAVACH_GMAIL_APP_PASSWORD || true)}
GMAIL_TO=${KAVACH_GMAIL_TO:-$(envval KAVACH_GMAIL_TO || true)}
GMAIL_TO=${GMAIL_TO:-$GMAIL_USER}
[ "${KAVACH_GMAIL:-on}" = "off" ] && GMAIL_USER=          # KAVACH_GMAIL=off: Mailpit only (no internet on stage)
RELAY=()
if [ -n "$GMAIL_USER" ] && [ -n "$GMAIL_PASS" ]; then
  (umask 077; printf "host: smtp.gmail.com\nport: 587\nstarttls: true\nauth: plain\nusername: '%s'\npassword: '%s'\noverride-from: '%s'\nsubject-prefix: '[KAVACH demo] '\n" \
    "$GMAIL_USER" "${GMAIL_PASS// /}" "$GMAIL_USER" > .kavach/gmail-relay.yaml)
  RELAY=(--smtp-relay-config .kavach/gmail-relay.yaml --smtp-relay-matching "^${GMAIL_TO//./\\.}\$")
  export KAVACH_DEMO_MAIL_TO=$GMAIL_TO            # the Live demo page suggests this address
fi
relay_on() { curl -sf http://127.0.0.1:8025/api/v1/webui | grep -q '"Enabled":true'; }
if curl -sf http://127.0.0.1:8025/api/v1/info >/dev/null && [ ${#RELAY[@]} -gt 0 ] && ! relay_on; then
  kill "$(lsof -nP -tiTCP:8025 -sTCP:LISTEN)" 2>/dev/null && sleep 1        # restart it with Gmail forwarding on
fi
if ! curl -sf http://127.0.0.1:8025/api/v1/info >/dev/null; then
  command -v mailpit >/dev/null || { echo "Mailpit is not installed (macOS: brew install mailpit)"; exit 1; }
  nohup mailpit --listen 127.0.0.1:8025 --smtp 127.0.0.1:1025 --api-cors "127.0.0.1:${PORT},localhost:${PORT}" \
    ${RELAY[@]+"${RELAY[@]}"} > .kavach/mailpit.log 2>&1 &      # --api-cors: the Live demo page reads the inbox
  for _ in 1 2 3 4 5 6 7 8 9 10; do curl -sf http://127.0.0.1:8025/api/v1/info >/dev/null && break; sleep 0.5; done
fi
echo "Inbox:   http://127.0.0.1:8025$([ ${#RELAY[@]} -gt 0 ] && echo "   (emails to $GMAIL_TO also go to real Gmail, from $GMAIL_USER)")"

PY=${PYTHON:-python3}
[ -x .venv/bin/python ] && [ -z "${PYTHON:-}" ] && PY=.venv/bin/python
if ! curl -sf http://127.0.0.1:8030/transfers >/dev/null; then       # the sandbox bank: Demo 2's proof page
  KAVACH_BANK_DB=.kavach/bank.db nohup "$PY" -m uvicorn scripts.sandbox_bank:create --factory --host 127.0.0.1 \
    --port 8030 > .kavach/bank.log 2>&1 &
  for _ in 1 2 3 4 5 6 7 8 9 10; do curl -sf http://127.0.0.1:8030/transfers >/dev/null && break; sleep 0.5; done
fi
echo "Bank:    http://127.0.0.1:8030"

export KAVACH_BANK_URL=http://127.0.0.1:8030 KAVACH_INVOICE_DEMO=1     # INV-101, vendor V001 = TEST-ACCT-001
export KAVACH_SMTP_HOST=127.0.0.1 KAVACH_SMTP_PORT=1025
export KAVACH_MAIL_HOLD_S=${KAVACH_MAIL_HOLD_S:-30} KAVACH_PAYMENT_HOLD_S=${KAVACH_PAYMENT_HOLD_S:-60}
export KAVACH_DB_URL=${KAVACH_DB_URL:-sqlite:///$PWD/.kavach/demo.db}
export KAVACH_MCP_TOOLS=${KAVACH_MCP_TOOLS:-mail.read_inbox,mail.send,crm.query,invoice.read,vendor.read,payment.release}
export KAVACH_SWEEP_S=${KAVACH_SWEEP_S:-1}        # check every second, so it leaves when the countdown ends
echo "Console: http://127.0.0.1:$PORT   (Claude connects to http://127.0.0.1:$PORT/mcp)"
echo $$ > .kavach/kavach.pid
exec "$PY" -m uvicorn kavach.server:app --host 127.0.0.1 --port "$PORT"
