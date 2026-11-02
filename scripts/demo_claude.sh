#!/usr/bin/env bash
# Claude Code for the live demo, able to act only through KAVACH (start KAVACH first: scripts/demo_up.sh).
#
#   scripts/demo_claude.sh                                   interactive
#   scripts/demo_claude.sh -p "Send this test summary to demo-recipient@example.test: All checks passed."
#
# --tools "" turns off every built-in tool (no shell, no files, no web), --no-chrome keeps Claude out of your browser,
# --strict-mcp-config ignores any other MCP server: KAVACH's /mcp is Claude's only way to act, and no mail or bank
# credentials are in Claude's environment. It starts in an empty folder (~/.kavach-demo) with only the demo's own
# settings, so Claude sees no repository, project notes, git status or personal plugins: a plain assistant.
# The hook (integrations/claude_code_hook.py --mcp) tells KAVACH what you typed: the trusted request.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
DEMO_HOME=${KAVACH_CLAUDE_HOME:-$HOME/.kavach-demo}
mkdir -p "$DEMO_HOME" && cd "$DEMO_HOME"
export KAVACH_REPO=$REPO                               # where the hook lives (settings.json uses it)
exec claude --tools "" --no-chrome --setting-sources project,local --strict-mcp-config \
  --mcp-config "$REPO/integrations/claude_demo/mcp.json" --settings "$REPO/integrations/claude_demo/settings.json" \
  --allowedTools "mcp__kavach" "$@"
