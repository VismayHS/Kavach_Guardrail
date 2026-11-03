# KAVACH on AgentDojo

AgentDojo v1.2.2 (ETH Zurich, NeurIPS 2024), the standard benchmark for prompt-injection defenses. The agent is Llama 3.3 70B on Qualcomm Cloud AI. Nobody on the team wrote these tasks or attacks.

| Suite | Attack | Defense | Utility (no attack) | Utility under attack | Attack success ↓ | … counting only calls that ran | Runs | KAVACH commit |
|---|---|---|---|---|---|---|---|---|
| banking | important_instructions | none | 50.0% (16) | 37.5% | 45.8% | 45.8% | 144 | - |
| banking | important_instructions | spotlighting_with_delimiting | 50.0% (16) | 51.4% | 47.9% | 47.9% | 144 | e682983 |
| slack | important_instructions | none | 42.9% (21) | 34.3% | 45.7% | 45.7% | 105 | b6a6aaf | ⚠ 1 model service errors
| slack | important_instructions | spotlighting_with_delimiting | 52.4% (21) | 32.4% | 44.8% | 44.8% | 105 | 4956838 | ⚠ 5 model service errors

**How to read this.** Utility = AgentDojo's own check that the user's task was done. Attack success = AgentDojo's check that the attacker's goal happened. For one slack attack (injection_task_5) AgentDojo counts the calls the agent attempted, so a call KAVACH blocked still counts as the attacker's; the next column redoes that check on the calls that ran (for every other attack the two are the same). KAVACH's manifests (bench/agentdojo_kavach.py) declare what each tool is; the banking one was written before any run and gained destination and user-only arguments, and the slack one was revised, after the offline ground-truth replay (bench/agentdojo_replay.py, AGENTDOJO_REPLAY.md), before the runs here. The rules changed with it are general (each has its own test on KAVACH's own tools); the risk model and operating point are the shipped ones, not tuned on AgentDojo. Numbers from other papers use other models and are not comparable with these.
