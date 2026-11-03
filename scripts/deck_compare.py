"""Comparison and AgentOS content shared by the solution deck and the reference deck.

A "-" means the feature is not in the paper or documentation we read. Published attack rates stay out of this table:
they come from other tests and models, so they can't be ranked against ours.
"""
HEAD = ['Approach (example)', 'Decides at the tool call', 'Traces where values came from', 'Reads the real effect first',
        'Hold or undo before it lands', 'Approval tied to the exact call', 'Signed, verifiable receipts']
ROWS = [
    ['Text scanner (Infosys PromptGuard, RAI proxy)', '—', '—', '—', '—', '—', '—'],
    ['Prompt + reasoning scanner (Meta LlamaFirewall)', 'Partly', '—', '—', '—', '—', '—'],
    ['Tool name + schema check (NVIDIA NeMo tool rails)', 'Yes', '—', '—', '—', '—', '—'],
    ['Pattern gate + hooks (Infosys AgentOS)', 'Yes', 'Partly', '—', '—', 'Partly', '—'],
    ['Policy gateway (AWS AgentCore Policy)', 'Yes', '—', '—', '—', '—', '—'],
    ['Least privilege (Progent)', 'Yes', '—', '—', '—', 'Partly', '—'],
    ['Information flow (Google CaMeL)', 'Yes', 'Yes', '—', '—', 'Partly', '—'],
    ['Information flow (Microsoft FIDES)', 'Yes', 'Yes', '—', '—', '—', '—'],
    ['KAVACH', 'Yes', 'Yes', 'Yes*', 'Yes*', 'Yes*', 'Yes'],
]
USP = ('OUR USP: each approach above checks part of an action. KAVACH brings it all together at the tool call: where each '
       'value came from, what the call would really change, a person’s approval for that exact call, a chance to stop it, '
       'and a signed record of what happened.')
LEGEND = ('* SQL and files are measured in a sandbox; email and payments are predicted. Hold, undo and exact-call approval '
          'apply when KAVACH runs the tool. — = not a feature in the paper or docs we read, which doesn’t prove it can’t be added. '
          'Stronger elsewhere: CaMeL and FIDES enforce information flow by design, if the agent runs inside their planner; '
          'KAVACH’s tracing is value matching, with known limits.')
COMPARE_NOTES = ('Say it plainly: nobody here is useless, each approach solves part of the problem. KAVACH’s difference is the '
                 'combination at the tool call. Be ready for the honest answer: CaMeL and FIDES have stronger guarantees by '
                 'design, but the agent must run inside their planner; KAVACH sits in front of an existing agent. Partly means: '
                 'LlamaFirewall audits agent reasoning and scans inputs, rather than deciding on the call’s arguments; AgentOS has a '
                 'real approval queue, and collects provenance metadata that its default gate doesn’t use to decide; Progent asks for approval when a policy widens; CaMeL asks the user when a policy blocks. '
                 'Published attack rates are left out on purpose: other tests and models can’t be ranked against ours. This table '
                 'covers published systems. We have no information about what other hackathon teams built.')
COMPARE_SOURCES = ('arXiv 2503.18813 (CaMeL); arXiv 2505.23643 (FIDES); arXiv 2504.11703 (Progent); arXiv 2505.03574 (LlamaFirewall); '
                   'docs.nvidia.com NeMo Guardrails tool-calling page; aws.amazon.com Policy in Bedrock AgentCore; '
                   'docs/INFOSYS_GAP_ANALYSIS.md')
AGENTOS_HEAD = ['', 'Infosys AgentOS (built-in paths we read)', 'KAVACH']
AGENTOS_ROWS = [
    ['What it looks at', 'Hooks, tool and skill names, and patterns over commands and arguments', 'Where each value came from, and what this call would change'],
    ['Injected email', 'PromptGuard and the RAI proxy paths don’t see tool output; a custom hook could', 'Output labelled untrusted; an address taken from it is refused'],
    ['Business limits', 'approval_rules are evaluated inside a tool the agent must choose to call, on context it supplies', 'Rules run outside the model; payment facts come from records (demo company today)'],
    ['Approval card', 'Durable holds, with a stale-config check; card shows tool, command preview, skill, rule', 'Effect, each argument’s origin, explanation; tied to the exact call'],
    ['Undo', 'Holds pause a call; “rollback” means tool-code versions', 'Hold, recall, park or snapshot when KAVACH runs the tool'],
    ['Audit log', 'JSONL and OpenTelemetry; no linked hash chain in the path we read', 'Hash chain, HMAC, Ed25519, signed checkpoint'],
]
AGENTOS_KEYS = [('AgentOS pre-tool gate, default config, autonomous', 'AgentOS default gate'),
                ('AgentOS pre-tool gate, hardened config, autonomous', 'AgentOS hardened gate'),
                ('KAVACH (full)', 'KAVACH')]
AGENTOS_BAND = ('We plug in, we don’t replace. AgentOS keeps routing, sandboxing, approval operations and RBAC, where it is ahead of us; '
                'KAVACH joins through its PreToolUse hooks and supplies the judgment. Tested through AgentOS’s governance code with a stand-in '
                'agent; a full LLM-driven AgentOS chat isn’t verified. There AgentOS runs the tool, so KAVACH’s hold and undo don’t apply.')
AGENTOS_NOTES = ('AgentOS is Infosys’s own agent runtime, inside Infosys Agentic Foundry. We read and ran its code rather than relying on its '
                 'documentation. Its default gate looks for dangerous patterns. Hardening it works, with zero injection success, but only by '
                 'sending most actions to a person, which risks approval fatigue. KAVACH allows no unsafe action on the same suite while sending far '
                 'fewer to a person, because it knows the origin and effect of each call. This suite is written by us, so read the numbers as showing '
                 'the mechanism. The Infosys gate code was loaded and executed; the RAI classifiers were not run. Don’t say Infosys has no guardrails: '
                 'say the built-in paths we read don’t combine these checks by default, and custom hooks can add more. KAVACH’s payment facts are the '
                 'demo company’s; a real ERP needs integration work. AgentOS also truncates hook outputs, which can weaken tracing. Approval SLAs, '
                 'durable approvals, SafeKernel, RBAC and multi-tenancy are stronger than anything we built, which is why we plug into it.')
AGENTOS_SOURCES = 'docs/INFOSYS_GAP_ANALYSIS.md; bench/results/infosys_compare.json; INFOSYS_COMPARISON.md; AGENTOS_LIVE.md; integrations/agentos_hook.py'
