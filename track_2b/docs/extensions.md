# rosetta-flow: potential extensions

Unless marked as built, none of these exists yet; each names what it adds and what in the repository it builds on.
Summarised in section 8 of the technical report.

| Horizon | Extension | What it adds | Builds on |
|---|---|---|---|
| Weeks | **OpenTelemetry importer** | audit any agent instrumented with OTLP `gen_ai.*` spans, no converter | trace format, tau-bench converter |
| Weeks | **New domains as kits**: banking (identity checks, transfer limits, masked IBANs), insurance claims, public services | a policy, tools and error injectors per domain; exact labels for each | `DomainSpec` hooks, 10 generic injectors |
| Weeks | **Confirmer checks the finding** instead of re-auditing the whole run (*built and measured on dev: five times cheaper but less accurate than investigating, report section 5.2*) | a cheaper second tier; next: let it open the cited steps with tools instead of reading the whole run | two-tier pipeline, evidence check |
| Months | **Thinking confirmer** for the hard cases: the `-thinking` variants of Apertus in verify mode (they serve no tool calls, verify needs none), used only where slow, careful reasoning pays: rules that combine several conditions, amounts and tolerances to recompute (refund minus fees, a measurement against a drawing limit), consistency across a long run, and high-stakes flags such as a lot release or a large refund | a second opinion where the plain confirmer is unsure, at a cost paid only on few runs | verify mode already strips the reasoning before parsing; a probe on one run: about 20 times the output tokens, and it argued itself out of a real error, so it needs measuring first |
| Months | **Guard before the action**: run the auditor on a pending high-risk tool call (a refund, a lot release) and hold it if a rule is broken | from finding errors after the fact to preventing them | harness, policy rules, token cap for latency |
| Months | **Learning from reviewers on premises**: decisions in the review trail become labels that retrain the screener inside the organisation | the auditor improves on the company's own runs without data leaving the building | `review.py`, LoRA and GRPO pipelines |
| Months | **Fleet analytics**: which policy rules agents break most, per agent and version | fix agent prompts and tools where they fail, not one run at a time | typed findings, fleet view |
| Months | **Small screener at the edge**: a quantised 8B on CPU for disconnected sites (plants, branches) | auditing without any GPU on site | llama.cpp builds of Apertus v1.5 exist |
| Research | **Calibrated escalation**: a screener probability that sets the threshold, so cost and recall become a dial | built on the investigating harness, where the single-pass GRPO screener failed | `screen.py`, `rl.py`, Brier reward |
| Research | **Preference training (DPO)** on accepted vs rejected 70B investigations, then multi-step RL on the investigation itself | fewer false alarms from the 8B alone | 557 accepted investigations, and 272 runs where every attempt was rejected |
| Research | Multiple errors per run, long traces (coding agents), a pilot on real, consented traces from a Swiss organisation | evidence beyond synthetic data | evaluation and scoring code |
