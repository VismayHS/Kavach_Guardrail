# KAVACH policies in Cedar: proofs and parity

Policies: `kavach/policies/cedar/kavach.cedar`. Facts come from KAVACH's engines (provenance, staging, lookalike and canary checks); Cedar decides. Method: Cedar's partial evaluator, with only the facts a property is about fixed and every other fact unknown; a definite Deny holds for every value of the unknowns. This is not Cedar's SMT analyzer (the Rust cedar-symcc tool), and partial evaluation is an experimental upstream feature.

## Proofs

| Property | Result |
|---|---|
| Untrusted content the user didn't point at can never choose where an external action goes (R1) | **proved** |
| A destination read from a source the user pointed at never runs without a person (R1) | **proved** |
| No schema-destructive SQL in production, whatever else is true (R4) | **proved** |
| A planted canary record never leaves the company (R28) | **proved** |
| A paused agent can do nothing at all (kill switch) | **proved** |
| Whoever proposed a payment can never release it (R19, separation of duties) | **proved** |
| Vendor bank details never change on the say-so of an email or document (R20) | **proved** |
| Credential files are never read into an agent's context (R9) | **proved** |
| Once a task holds private data and untrusted content, an outbound action to a destination the user didn't give never runs without a person (R14) | **proved** |
| A EUR 650,000 release never runs without a person when the releaser's limit is EUR 25,000 (R18; for these amounts, not every amount) | **proved** |
| A tool onboarded from MCP annotations never runs without a person until approved (R6) | **proved** |

Control (not vacuous): a clean read with every fact known gets `PASS`.

## Parity with the Python engine

1027 of 1027 decisions agree (bench suite, holdout, demo scenarios). Cedar floors: {'PASS': 626, 'REQUIRE_APPROVAL': 106, 'DENY': 295}.

Rules exercised: R1:DENY x102, R5:REQUIRE_APPROVAL x85, R2:REQUIRE_APPROVAL x71, R14:REQUIRE_APPROVAL x51, R10:REQUIRE_APPROVAL x49, R11:DENY x41, R4:DENY x21, R9:DENY x21, R6:DENY x21, R20:DENY x21, R19:DENY x21, R3:DENY x20, R8:DENY x20, R12:DENY x20, R1:REQUIRE_APPROVAL x20, R5:DENY x7, R18:REQUIRE_APPROVAL x1, R21:DENY x1.

