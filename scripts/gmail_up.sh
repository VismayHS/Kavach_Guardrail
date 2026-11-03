#!/usr/bin/env bash
# KAVACH on your real Gmail. No demo company, no fake inbox, no Mailpit: an agent (Claude Code, or any MCP client)
# reads your Gmail inbox and sends from your Gmail account, and only through KAVACH.
#
#   scripts/gmail_up.sh          then  scripts/demo_claude.sh   (Claude)   or   scripts/llama_agent.py   (Llama on Qualcomm)
#   console: http://127.0.0.1:8000/#/activity   every action an agent proposes, KAVACH's decision, what Gmail did
#
# Needs in .env (git-ignored; or ../.env, or the environment):
#   KAVACH_GMAIL_USER=you@gmail.com
#   KAVACH_GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx    (Google account > Security > 2-Step Verification > App passwords)
# The password stays in KAVACH's process: the agent never sees it. Reading is read-only (nothing is marked read);
# every email the agent sends waits KAVACH_MAIL_HOLD_S seconds (30) in which you can cancel it on the console.
set -euo pipefail
cd "$(dirname "$0")/.."
PORT=${PORT:-8000}
mkdir -p .kavach

if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' 2>/dev/null | grep -qx 'kavach-kavach-1'; then
  echo "Stopping the compose stack's KAVACH container (it holds port $PORT)"
  docker compose stop kavach >/dev/null
fi
if curl -sf "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
  echo "Something already answers on port $PORT (an earlier KAVACH?). Stop it first: scripts/demo_reset.sh"
  exit 1
fi

# only these settings are read from .env, never printed
setting() {
  local k=$1 f
  [ -n "${!k:-}" ] && return 0
  for f in .env ../.env; do
    [ -f "$f" ] || continue
    local v
    v=$(sed -n "s/^[[:space:]]*$k[[:space:]]*=[[:space:]]*//p" "$f" | tail -1 | tr -d "\"'")
    [ -n "$v" ] && { export "$k=$v"; return 0; }
  done
}
for k in KAVACH_GMAIL_USER KAVACH_GMAIL_APP_PASSWORD INFERENCE_CLOUD_API_KEY INFERENCE_CLOUD_ENDPOINT \
         IMAGINE_API_KEY IMAGINE_API_ENDPOINT; do setting "$k"; done
if [ -z "${KAVACH_GMAIL_USER:-}" ] || [ -z "${KAVACH_GMAIL_APP_PASSWORD:-}" ]; then
  echo "Put KAVACH_GMAIL_USER and KAVACH_GMAIL_APP_PASSWORD in .env first (see the top of this script)."
  exit 1
fi

PY=${PYTHON:-python3}
[ -x .venv/bin/python ] && [ -z "${PYTHON:-}" ] && PY=.venv/bin/python
"$PY" - <<'EOF' || { echo "Gmail refused the login: check the address and the App Password in .env"; exit 1; }
import os
from kavach.connectors import GmailInbox
n = len(GmailInbox.from_env().latest(1))
print(f"Gmail:   {os.environ['KAVACH_GMAIL_USER']} (inbox readable, {n} newest message fetched as a check)")
EOF

export KAVACH_MAIL=gmail KAVACH_MCP_TOOLS=${KAVACH_MCP_TOOLS:-mail.read_inbox,mail.send}
export KAVACH_MAIL_HOLD_S=${KAVACH_MAIL_HOLD_S:-30} KAVACH_SWEEP_S=${KAVACH_SWEEP_S:-1}
export KAVACH_DB_URL=${KAVACH_DB_URL:-sqlite:///$PWD/.kavach/gmail.db}
if curl -s -o /dev/null --max-time 1 http://127.0.0.1:4318/ 2>/dev/null; then
  export OTEL_EXPORTER_OTLP_ENDPOINT=${OTEL_EXPORTER_OTLP_ENDPOINT:-http://127.0.0.1:4318} OTEL_SERVICE_NAME=kavach-gmail
fi
[ -n "${INFERENCE_CLOUD_API_KEY:-}${IMAGINE_API_KEY:-}" ] && echo "Qualcomm: key loaded (the judge's note on approvals; scripts/llama_agent.py)"
echo "Console: http://127.0.0.1:$PORT/#/activity"
echo "Agents:  scripts/demo_claude.sh (Claude Code)  |  .venv/bin/python scripts/llama_agent.py (Llama on Qualcomm)"
echo $$ > .kavach/kavach.pid
exec "$PY" -m uvicorn kavach.server:app --host 127.0.0.1 --port "$PORT"
