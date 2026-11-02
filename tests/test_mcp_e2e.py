"""E1 end to end over real transports: MCP client -> stdio -> KAVACH proxy process -> stdio -> upstream process."""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp import Client, StdioServerParameters  # noqa: E402

pytestmark = pytest.mark.skipif(os.environ.get("KAVACH_SKIP_E2E") == "1", reason="KAVACH_SKIP_E2E=1")


def config(tmp_path) -> Path:
    cfg = tmp_path / "kavach_mcp.yaml"
    cfg.write_text(f"""
upstreams:
  demo:
    command: python
    args: [{ROOT / 'examples' / 'mcp' / 'demo_upstream.py'}]
    env: {{KAVACH_DEMO_OUTBOX: {tmp_path / 'sent.jsonl'}}}
tools:
  send_email: {{effect: external_send, sink: external, reversibility: irreversible, control_args: [to],
               data_args: [subject, body], effect_model: email}}
  read_page: {{effect: ingress, sink: none, reversibility: idempotent, control_args: [url], effect_model: web_fetch,
              output_trust: untrusted, output_conf: public}}
pins: {tmp_path / 'pins.json'}
approval_wait_s: 1
""")
    return cfg


def test_proxy_process_blocks_the_injection_and_forwards_the_read(tmp_path):
    proxy = StdioServerParameters(command=sys.executable, args=["-m", "kavach.mcp_proxy", "--config", str(config(tmp_path))],
                                  cwd=str(ROOT), env={**os.environ, "KAVACH_CANARIES": "0"})

    async def go():
        async with Client(proxy) as c:
            names = sorted(t.name for t in (await c.list_tools()).tools)
            meta = {"kavach/userRequest": "Summarise https://news.example/q3 for me."}
            page = await c.call_tool("demo__read_page", {"url": "https://news.example/q3"}, meta=meta)
            sent = await c.call_tool("demo__send_email", {"to": "billing@acme-invoices.co", "subject": "recon",
                                                          "body": "customer list"}, meta=meta)
            poisoned = await c.call_tool("demo__add", {"a": 1, "b": 2})
            return names, page, sent, poisoned
    names, page, sent, poisoned = asyncio.run(go())
    assert names == ["demo__read_page", "demo__send_email"]                       # the poisoned 'add' isn't listed
    assert not page.is_error and "revenue grew" in page.content[0].text
    assert sent.is_error and "[R1]" in sent.content[0].text
    assert not (tmp_path / "sent.jsonl").exists()                               # nothing reached the mail server
    assert poisoned.is_error and "quarantined" in poisoned.content[0].text
    assert json.loads((tmp_path / "pins.json").read_text())["demo__send_email"]["by"] == "first-use"
