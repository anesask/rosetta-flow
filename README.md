# rosetta-flow

An open, on-premise auditor for AI-agent runs, built with Apertus. Hack Apertus 2026, Track 2B (own project).

The small Apertus 8B screens every agent run, the large 70B confirms only the flagged ones, and every finding
comes with evidence that code has checked verbatim against the cited step.

Everything is in [`track_2b/`](track_2b/), the project root required by the hackathon template:

- [`track_2b/README.md`](track_2b/README.md): how to run it (`make run`, three `LLM_*` env vars, Docker)
- [`track_2b/technical_report.md`](track_2b/technical_report.md): the technical report (PDF next to it)
- [`track_2b/docs/architecture.md`](track_2b/docs/architecture.md): how the two tiers and the harness work
- [`track_2b/results/README.md`](track_2b/results/README.md): where every number in the report comes from

Demo video (1:53): https://youtu.be/zZuEkJsSdbQ

On Hugging Face:

- LoRA adapters (Apache-2.0): [anesdevtoday/rosetta-flow-auditor-lora](https://huggingface.co/anesdevtoday/rosetta-flow-auditor-lora)
- Dataset (CDLA-Permissive-2.0; tau-bench subset MIT): [anesdevtoday/rosetta-flow-traces](https://huggingface.co/datasets/anesdevtoday/rosetta-flow-traces)

Licences: code Apache-2.0 ([`LICENSE`](LICENSE)), report CC-BY-4.0, adapters Apache-2.0, dataset CDLA-Permissive-2.0.
