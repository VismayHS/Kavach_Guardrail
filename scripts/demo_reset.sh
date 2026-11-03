#!/usr/bin/env bash
# Reset the live demo to a clean start: stop KAVACH (if demo_up.sh started it), empty the Mailpit inbox and the
# sandbox bank, and forget KAVACH's demo state (receipts, waiting emails and payments). Then run scripts/demo_up.sh again.
set -uo pipefail
cd "$(dirname "$0")/.."

if [ -f .kavach/kavach.pid ] && kill -0 "$(cat .kavach/kavach.pid)" 2>/dev/null; then
  kill "$(cat .kavach/kavach.pid)" && echo "KAVACH stopped"
  sleep 1
fi
if [ -f .kavach/metrics-bridge.pid ]; then
  kill "$(cat .kavach/metrics-bridge.pid)" 2>/dev/null
  rm -f .kavach/metrics-bridge.pid
fi
rm -f .kavach/kavach.pid .kavach/demo.db .kavach/demo.db.checkpoint.json && echo "KAVACH demo state cleared"
if curl -sf -X DELETE http://127.0.0.1:8025/api/v1/messages >/dev/null; then
  echo "Mailpit inbox emptied"
else
  echo "Mailpit isn't running (nothing to empty)"
fi
if curl -sf -X DELETE http://127.0.0.1:8030/transfers >/dev/null; then
  echo "Sandbox bank emptied"
else
  rm -f .kavach/bank.db && echo "Sandbox bank cleared"
fi
echo "Start again with: scripts/demo_up.sh"
