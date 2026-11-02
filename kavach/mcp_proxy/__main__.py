"""Run KAVACH as an MCP proxy.

    python -m kavach.mcp_proxy --config kavach_mcp.yaml                 # stdio: point Claude Desktop / an IDE here
    python -m kavach.mcp_proxy --config kavach_mcp.yaml --http 8100     # Streamable HTTP at http://127.0.0.1:8100/mcp
    python -m kavach.mcp_proxy --config kavach_mcp.yaml --console 8000  # also serve the approvals console and API
    python -m kavach.mcp_proxy --config kavach_mcp.yaml --scan          # connect, report every tool's status, exit

In stdio mode stdout belongs to the MCP protocol: everything KAVACH says goes to stderr.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import threading
from contextlib import AsyncExitStack

from .proxy import KavachMCPProxy, ProxyConfig


def start_console(proxy: KavachMCPProxy, port: int) -> None:
    """The KAVACH API and console in this process, on the proxy's own gateway (so a person can approve
    escalated calls while the agent waits)."""
    import uvicorn

    from .. import server as api
    api.gw, api.env = proxy.gw, proxy.gw.env
    cfg = uvicorn.Config(api.app, host="127.0.0.1", port=port, log_level="warning")
    threading.Thread(target=uvicorn.Server(cfg).run, daemon=True, name="kavach-console").start()
    print(f"KAVACH console: http://127.0.0.1:{port}  (approvals: /api/hitl)", file=sys.stderr)


def report(proxy: KavachMCPProxy) -> int:
    """mcp-scan-style report. Exit code 1 if any tool is quarantined or changed."""
    bad = 0
    for t in proxy.tools.values():
        print(f"{t.status:12s} {t.name:40s} {t.hash}", file=sys.stderr)
        for f in t.findings:
            print(f"{'':12s}   {f['severity']}: {f['kind']}: {f['evidence'][:100]}", file=sys.stderr)
        bad += t.status in ("quarantined", "changed")
    return 1 if bad else 0


async def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m kavach.mcp_proxy", description=__doc__.split("\n")[0])
    ap.add_argument("--config", required=True)
    ap.add_argument("--http", type=int, help="serve Streamable HTTP on this port instead of stdio")
    ap.add_argument("--console", type=int, help="also serve the KAVACH API and approvals console on this port")
    ap.add_argument("--scan", action="store_true", help="connect, report each tool's status and findings, exit")
    a = ap.parse_args(argv)
    proxy = KavachMCPProxy(ProxyConfig.from_yaml(a.config))
    async with AsyncExitStack() as stack:
        await proxy.connect(stack)
        if a.scan:
            return report(proxy)
        report(proxy)
        if a.console:
            start_console(proxy, a.console)
        srv = proxy.server()
        if a.http:
            import uvicorn
            cfg = uvicorn.Config(srv.streamable_http_app(), host="127.0.0.1", port=a.http, log_level="warning")
            print(f"KAVACH MCP proxy: http://127.0.0.1:{a.http}/mcp", file=sys.stderr)
            await uvicorn.Server(cfg).serve()
        else:
            from mcp.server.stdio import stdio_server
            async with stdio_server() as (read, write):
                await srv.run(read, write, srv.create_initialization_options())
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
