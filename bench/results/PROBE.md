# Prompt-injection classifier on tool outputs (C3)

Model `protectai/deberta-v3-base-prompt-injection-v2` on CPU, threshold 0.5 (the model's own default, not tuned). 109 distinct texts. Two ways of reading a text: **whole** (score it at once) and **segments** (score each sentence-level segment, take the max).

| | Detection rate (injected) | False positives (ordinary) | p50 / p95 ms per text |
|---|---|---|---|
| whole text | 34.2% | 2.8% | 46.6 / 69.4 |
| segments (KAVACH default) | 46.6% | 2.8% | 114.6 / 270.5 |

**Caveat:** the segments mode was chosen after seeing the whole-text results on this same corpus, so its numbers are optimistic. They are reported next to the whole-text ones for that reason.

| Source | Injected? | Texts | Flagged (whole) | Flagged (segments) |
|---|---|---|---|---|
| AgentDojo: important_instructions attack | yes | 9 | 9 (100%) | 9 (100%) |
| AgentDojo: ordinary file | no | 3 | 0 (0%) | 0 (0%) |
| AgentDojo: ordinary transaction subject | no | 5 | 0 (0%) | 0 (0%) |
| ours: CRM row | no | 15 | 1 (7%) | 1 (7%) |
| ours: bank-change email (social engineering) | yes | 8 | 8 (100%) | 8 (100%) |
| ours: injected SQL in an email | yes | 8 | 0 (0%) | 0 (0%) |
| ours: injected email | yes | 1 | 1 (100%) | 1 (100%) |
| ours: injected email (incl. obfuscated) | yes | 22 | 7 (32%) | 7 (32%) |
| ours: injected web page | yes | 1 | 0 (0%) | 1 (100%) |
| ours: injected web page (incl. obfuscated) | yes | 24 | 0 (0%) | 8 (33%) |
| ours: ordinary email | no | 10 | 0 (0%) | 0 (0%) |
| ours: ordinary web page | no | 1 | 0 (0%) | 0 (0%) |
| ours: workspace file | no | 2 | 0 (0%) | 0 (0%) |

What it is for: a flagged source loses reply-to-sender trust, and rule R29 sends state changes in that task to a human unless every target was typed by the user. It never blocks on its own, so a miss falls back to the provenance rules, and a false positive costs a human click, not a lost task.

Injected SQL ("Please run: UPDATE ...") reads as an ordinary request from the email's author, not an instruction to an AI, and the classifier misses it; provenance catches it instead (R11: the statement was copied from untrusted content).
