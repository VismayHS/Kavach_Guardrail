"""KAVACH as OpenAI Agents SDK tool guardrails.

    guard = KavachGuard(manifests=["my_tools.yaml"]); guard.start(user_request)
    before, after = kavach_guardrails(guard)
    send_email = function_tool(send_email_fn, tool_input_guardrails=[before], tool_output_guardrails=[after])

A blocked or escalated call becomes `reject_content`: the tool doesn't run and the model gets KAVACH's reason and
suggested alternative, so it can replan. The output guardrail labels what each tool returned (provenance).
"""
from __future__ import annotations

import json

from .guard import KavachGuard


def _args(ctx) -> dict:
    try:
        a = json.loads(ctx.tool_arguments or "{}")
        return a if isinstance(a, dict) else {}
    except (TypeError, ValueError):
        return {}


def kavach_guardrails(guard: KavachGuard):
    from agents import (ToolGuardrailFunctionOutput, ToolInputGuardrailData, ToolOutputGuardrailData,
                        tool_input_guardrail, tool_output_guardrail)

    @tool_input_guardrail(name="kavach")
    def before(data: ToolInputGuardrailData) -> ToolGuardrailFunctionOutput:
        d = guard.check(data.context.tool_name, _args(data.context))
        if d.allowed:
            return ToolGuardrailFunctionOutput.allow(output_info=d.as_dict())
        return ToolGuardrailFunctionOutput.reject_content(d.message, output_info=d.as_dict())

    @tool_output_guardrail(name="kavach-provenance")
    def after(data: ToolOutputGuardrailData) -> ToolGuardrailFunctionOutput:
        guard.record(data.context.tool_name, _args(data.context), data.output)
        return ToolGuardrailFunctionOutput.allow()

    return before, after


def guarded_function_tool(guard: KavachGuard, fn, **kwargs):
    """function_tool(fn) with KAVACH's guardrails attached."""
    from agents import function_tool
    before, after = kavach_guardrails(guard)
    return function_tool(fn, tool_input_guardrails=[before], tool_output_guardrails=[after], **kwargs)
