# What each layer adds

Seed 0 test split: 282 scenarios in 47 families, shipped operating point, no LLM judge. Synthetic suite, written by the same team as the rules.

| System | Unsafe auto-allowed | Injection success | Safe auto-completed | Escalated |
|---|---|---|---|---|
| full | 0.0% | 0.0% | 95.2% | 26.6% |
| no model | 0.0% | 0.0% | 95.2% | 26.6% |
| rules only | 3.9% | 0.0% | 95.2% | 24.5% |

## Counted by family

Scenarios in a family share their verdict, so these are the real sample sizes.

| System | Safe families automated | 95% interval | Unsafe families with any action allowed | 95% interval |
|---|---|---|---|---|
| full | 20 of 21 | 77–99% | 0 of 26 | 0–13% |
| no model | 20 of 21 | 77–99% | 0 of 26 | 0–13% |
| rules only | 20 of 21 | 77–99% | 1 of 26 | 1–19% |

## What the risk model decides

**No verdict changes when p(harm) is forced to 0.** On this suite the rules and the intent gate make every decision; the risk model is a supporting signal shown to reviewers.

Unsafe training actions that pass every rule (all the model can learn from): attack:misaligned_write (10).
