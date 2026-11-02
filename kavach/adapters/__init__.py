"""Framework adapters (E2): put KAVACH in front of an agent's tools without changing the agent.

    from kavach.adapters import KavachGuard
    from kavach.adapters.openai_agents import kavach_guardrails      # OpenAI Agents SDK tool guardrails
    from kavach.adapters.langchain import guard_tool                  # LangChain / LangGraph tools
    from kavach.adapters.claude_agent_sdk import kavach_hooks         # Claude Agent SDK hooks
Claude Code (the CLI) uses integrations/claude_code_hook.py as command hooks; Topaz AgentOS uses
integrations/agentos_hook.py. Each adapter imports its framework lazily, so only the one you use must be installed.
"""
from .guard import GuardDecision, KavachGuard

__all__ = ["GuardDecision", "KavachGuard"]
