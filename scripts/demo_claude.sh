#!/usr/bin/env bash
# Claude Code for the live demo, able to act only through KAVACH (start KAVACH first: scripts/demo_up.sh).
#
#   scripts/demo_claude.sh                                   interactive, through KAVACH
#   scripts/demo_claude.sh -p "Send this test summary to demo-recipient@example.test: All checks passed."
#   scripts/demo_claude.sh --without-kavach                  the same Claude and tools, with no KAVACH in between
#
# --tools "" turns off every built-in tool (no shell, no files, no web), --no-chrome keeps Claude out of your browser,
# --strict-mcp-config ignores any other MCP server: KAVACH's /mcp is Claude's only way to act, and no mail or bank
# credentials are in Claude's environment. It starts in an empty folder (~/.kavach-demo) with only the demo's own
# settings, so Claude sees no repository, project notes, git status or personal plugins: a plain assistant.
# The hook (integrations/claude_code_hook.py --mcp) tells KAVACH what you typed: the trusted request.
#
# --without-kavach connects the same locked-down Claude to scripts/plain_mail_mcp.py instead: the same tool names
# over the same demo company, but every email goes to Mailpit at once. That is the comparison: same model, same
# prompt, same tools; the only difference is KAVACH.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
DEMO_HOME=${KAVACH_CLAUDE_HOME:-$HOME/.kavach-demo}
mkdir -p "$DEMO_HOME" && cd "$DEMO_HOME"
export KAVACH_REPO=$REPO                               # where the hook lives (settings.json uses it)
# Claude's own token use and cost, as Claude Code reports it, go to Grafana through the collector (when it runs):
# claude_code.cost.usage / claude_code.token.usage. The collector drops the account attributes before Prometheus.
if curl -s -o /dev/null --max-time 1 http://127.0.0.1:4318/ 2>/dev/null; then
  export CLAUDE_CODE_ENABLE_TELEMETRY=1 OTEL_METRICS_EXPORTER=otlp OTEL_EXPORTER_OTLP_PROTOCOL=http/json \
    OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318 OTEL_METRIC_EXPORT_INTERVAL=5000 \
    OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE=cumulative OTEL_METRICS_INCLUDE_ACCOUNT_UUID=false
fi
if [ "${1:-}" = "--without-kavach" ]; then
  shift
  PY=$REPO/.venv/bin/python
  [ -x "$PY" ] || PY=$(command -v python3)
  MCP=$(printf '{"mcpServers":{"mail":{"type":"stdio","command":"%s","args":["%s/scripts/plain_mail_mcp.py"]}}}' "$PY" "$REPO")
  exec claude --tools "" --no-chrome --setting-sources project,local --strict-mcp-config --mcp-config "$MCP" \
    --allowedTools "mcp__mail" "$@"
fi
exec claude --tools "" --no-chrome --setting-sources project,local --strict-mcp-config \
  --mcp-config "$REPO/integrations/claude_demo/mcp.json" --settings "$REPO/integrations/claude_demo/settings.json" \
  --allowedTools "mcp__kavach" "$@"
