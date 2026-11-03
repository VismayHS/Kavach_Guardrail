"""KAVACH as Claude Agent SDK hooks.

    guard = KavachGuard(manifests=["kavach/manifests/claude_code.yaml"])
    options = ClaudeAgentOptions(hooks=kavach_hooks(guard))

UserPromptSubmit starts a KAVACH task with the user's prompt; PreToolUse checks each call: DENY -> "deny" (the reason
goes back to Claude), ESCALATE -> "ask" (the person at the keyboard decides, with KAVACH's reason shown), ALLOW -> no
opinion, so the user's own permission settings still apply (KAVACH only ever tightens them). PostToolUse labels
what each tool returned.
"""
from __future__ import annotations

from .guard import KavachGuard


def kavach_hooks(guard: KavachGuard) -> dict:
    from claude_agent_sdk import HookMatcher

    async def on_prompt(input_data, tool_use_id, context):
        guard.start(input_data.get("prompt", ""))
        return {}

    async def pre(input_data, tool_use_id, context):
        d = guard.check(input_data["tool_name"], input_data.get("tool_input") or {})
        if d.allowed:
            return {}
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                       "permissionDecision": "deny" if d.verdict == "DENY" else "ask",
                                       "permissionDecisionReason": d.message}}

    async def post(input_data, tool_use_id, context):
        guard.record(input_data["tool_name"], input_data.get("tool_input") or {}, input_data.get("tool_response"))
        return {}

    return {"UserPromptSubmit": [HookMatcher(hooks=[on_prompt])], "PreToolUse": [HookMatcher(hooks=[pre])],
            "PostToolUse": [HookMatcher(hooks=[post])]}
