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

# Port 8000 must be this KAVACH's: Claude's /mcp, the hook and the console all point there. The compose stack's own
# KAVACH (docker compose up) would answer instead, with none of the demo's settings, so it is stopped (Mailpit,
# Prometheus and Grafana keep running and are reused). A KAVACH already started by this script is left alone.
if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' 2>/dev/null | grep -qx 'kavach-kavach-1'; then
  echo "Stopping the compose stack's KAVACH container (it holds port $PORT): docker compose stop kavach"
  docker compose stop kavach >/dev/null
fi
if curl -sf "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
  echo "Something already answers on port $PORT (a KAVACH from an earlier run?). Stop it first: scripts/demo_reset.sh"
  exit 1
fi

if ! curl -sf http://127.0.0.1:8025/api/v1/info >/dev/null; then
  command -v mailpit >/dev/null || { echo "Mailpit is not installed (macOS: brew install mailpit)"; exit 1; }
  nohup mailpit --listen 127.0.0.1:8025 --smtp 127.0.0.1:1025 --api-cors "127.0.0.1:${PORT},localhost:${PORT}" \
    > .kavach/mailpit.log 2>&1 &      # --api-cors: the console's Live demo page reads the inbox directly
  for _ in 1 2 3 4 5 6 7 8 9 10; do curl -sf http://127.0.0.1:8025/api/v1/info >/dev/null && break; sleep 0.5; done
fi
echo "Inbox:   http://127.0.0.1:8025"

PY=${PYTHON:-python3}
[ -x .venv/bin/python ] && [ -z "${PYTHON:-}" ] && PY=.venv/bin/python
if ! curl -sf http://127.0.0.1:8030/transfers >/dev/null; then       # the sandbox bank: Demo 2's proof page
  KAVACH_BANK_DB=.kavach/bank.db nohup "$PY" -m uvicorn scripts.sandbox_bank:create --factory --host 127.0.0.1 \
    --port 8030 > .kavach/bank.log 2>&1 &
  for _ in 1 2 3 4 5 6 7 8 9 10; do curl -sf http://127.0.0.1:8030/transfers >/dev/null && break; sleep 0.5; done
fi
echo "Bank:    http://127.0.0.1:8030"

if [ -f .env ] && [ -z "${KAVACH_NO_DOTENV:-}" ]; then   # the Qualcomm key: the judge writes its note on approval cards
  set -a; . ./.env; set +a                                 # (values are never printed; KAVACH_NO_DOTENV=1 skips it)
  echo "Qualcomm: key loaded from .env (judge on escalations; console badge QUALCOMM AI ON)"
fi
export KAVACH_BANK_URL=http://127.0.0.1:8030 KAVACH_INVOICE_DEMO=1     # INV-101, vendor V001 = TEST-ACCT-001
export KAVACH_SMTP_HOST=127.0.0.1 KAVACH_SMTP_PORT=1025
export KAVACH_MAIL_HOLD_S=${KAVACH_MAIL_HOLD_S:-30} KAVACH_PAYMENT_HOLD_S=${KAVACH_PAYMENT_HOLD_S:-60}
export KAVACH_DB_URL=${KAVACH_DB_URL:-sqlite:///$PWD/.kavach/demo.db}
export KAVACH_MCP_TOOLS=${KAVACH_MCP_TOOLS:-mail.read_inbox,mail.send,invoice.read,vendor.read,payment.release,crm.query}   # crm.query: the poisoned-inbox story (an analyst agent reads the customer records the injected email asks for; Claude, as ap_agent, may not)
export KAVACH_SWEEP_S=${KAVACH_SWEEP_S:-1}        # check every second, so it leaves when the countdown ends
if curl -s -o /dev/null --max-time 1 http://127.0.0.1:4318/ 2>/dev/null; then      # the compose stack's collector
  export OTEL_EXPORTER_OTLP_ENDPOINT=${OTEL_EXPORTER_OTLP_ENDPOINT:-http://127.0.0.1:4318} OTEL_SERVICE_NAME=kavach-demo
  echo "Traces:  http://127.0.0.1:16686 (service kavach-demo; one span per decision, tagged with its correlation id)"
fi
if curl -sf --max-time 1 http://127.0.0.1:3000/api/health >/dev/null 2>&1; then
  echo "Grafana: http://127.0.0.1:3000 (KAVACH dashboard; Prometheus scrapes this KAVACH as host.docker.internal)"
fi
echo "Console: http://127.0.0.1:$PORT   (Claude connects to http://127.0.0.1:$PORT/mcp)"
echo $$ > .kavach/kavach.pid
exec "$PY" -m uvicorn kavach.server:app --host 127.0.0.1 --port "$PORT"
