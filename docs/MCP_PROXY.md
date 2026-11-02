# KAVACH as an MCP proxy

Put KAVACH between any MCP client (Claude Desktop, Claude Code, Cursor, VS Code, an agent SDK) and the MCP servers it
uses. The client talks to KAVACH; KAVACH talks to the real servers. Every tool call is checked before it reaches a
server, using the same provenance, consequence, rules and risk as the rest of KAVACH.

```
MCP client ──stdio/HTTP──▶ KAVACH proxy ──stdio/HTTP──▶ filesystem / fetch / mail / any MCP server
                              │
                              ├─ scans and pins every tool definition (poisoning, shadowing, rug pulls)
                              ├─ checks every call (provenance, effect, rules R1-R29, risk)
                              └─ asks a person when a call needs one (approvals console)
```

## What it stops

| Attack | What KAVACH does |
|---|---|
| A page or email the agent read tells it to send data somewhere | The destination came from untrusted content: **DENY (R1/R11)**; the upstream server never sees the call |
| A server's tool description carries hidden instructions (`<IMPORTANT>`, invisible Unicode, "don't tell the user") | Tool **quarantined**: never listed, calls refused |
| One server's tool tells the model how to use another server's tool (shadowing) | Tool **quarantined** |
| A server changes a tool's definition after you approved it (rug pull) | Definition hash no longer matches the pin: tool hidden, calls **DENY (R6)** until a person re-approves |
| Private data plus untrusted input plus an outbound call in one task (lethal trifecta) | **ESCALATE (R14)**: a person decides |
| PII, lookalike domains, unrequested SQL columns, schema changes... | The same rules as KAVACH's own tools, once the tool's manifest names its effect model |

## Run it

```bash
python -m kavach.mcp_proxy --config examples/mcp/kavach_mcp.yaml --scan        # see what it found, then exit
python -m kavach.mcp_proxy --config examples/mcp/kavach_mcp.yaml               # stdio
python -m kavach.mcp_proxy --config examples/mcp/kavach_mcp.yaml --http 8100   # http://127.0.0.1:8100/mcp
python -m kavach.mcp_proxy --config examples/mcp/kavach_mcp.yaml --console 8000  # + approvals at :8000
```

### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "kavach": {
      "command": "/path/to/Kavach_Guardrail/.venv/bin/python",
      "args": ["-m", "kavach.mcp_proxy", "--config", "/path/to/Kavach_Guardrail/examples/mcp/kavach_mcp.yaml",
               "--console", "8000"],
      "cwd": "/path/to/Kavach_Guardrail"
    }
  }
}
```

Remove the servers you put behind KAVACH from the client's own config, or the agent can go around it.

## Describing upstream tools

KAVACH needs to know what a tool does. In the config (or a manifest file listed under `manifests:`):

```yaml
tools:
  send_email:                      # the upstream's name, or the exposed <server>__<tool>
    effect: external_send
    sink: external
    reversibility: irreversible
    control_args: [to]             # the arguments that pick where it goes
    data_args: [subject, body]     # the arguments that carry data
    effect_model: email            # gets every email rule: R2, R14, R17, R24, R25
    arg_map: {to: recipients}      # if the tool names its arguments differently
```

Effect models: `email`, `sql_write`, `sql_read`, `file_write`, `file_delete`, `file_read`, `web_fetch`, `transfer`,
`refund`, `ledger_post`, `bank_change`, `ap_propose`, `ap_release`, `invoice_read`. A tool with no description is
judged from its MCP annotations with MCP's cautious defaults: not read-only, destructive, open world. That means its
calls go to a person until you describe it.

## Honest limits

- KAVACH decides; the upstream server executes. It can't hold, recall or snapshot what another server does, so in
  proxy mode it never claims an undo (`local_execution: false`). A payment tool with a real cancel window should be
  described with that window in its manifest.
- MCP doesn't carry the user's request to tools. Clients that can should send `_meta: {"kavach/userRequest": ...}`.
  Otherwise the config's `request` is used, and intent checks are weaker (provenance rules still apply).
- MCP's 2026 protocol is stateless per request. A session is what the client names in `_meta["kavach/session"]`;
  without one, the proxy process is one session (the stdio case).
- Only tools are proxied (not resources or prompts).
