"""KAVACH around LangChain / LangGraph tools.

    guard = KavachGuard(manifests=["my_tools.yaml"]); guard.start(user_request)
    tools = [guard_tool(t, guard) for t in tools]        # same names, descriptions and schemas

Before a tool runs KAVACH checks the call; a blocked or escalated call returns KAVACH's reason to the model instead
of running. After it runs, its output is labelled for provenance.
"""
from __future__ import annotations

from .guard import KavachGuard


def guard_tool(tool, guard: KavachGuard):
    from langchain_core.tools import StructuredTool

    def run(**kwargs):
        d = guard.check(tool.name, kwargs)
        if not d.allowed:
            return d.message
        out = tool.invoke(kwargs)
        guard.record(tool.name, kwargs, out)
        return out

    async def arun(**kwargs):
        d = guard.check(tool.name, kwargs)
        if not d.allowed:
            return d.message
        out = await tool.ainvoke(kwargs)
        guard.record(tool.name, kwargs, out)
        return out

    return StructuredTool.from_function(func=run, coroutine=arun, name=tool.name, description=tool.description,
                                        args_schema=tool.args_schema)
