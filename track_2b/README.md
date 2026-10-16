# rosetta-flow

**An on-prem auditor for AI agents, built with Apertus.** The small model (Apertus 8B) screens every agent run,
the large one (Apertus 70B) confirms only the runs it flags, and every finding comes with evidence that code has
checked word for word against the step it cites.

Each agent run (messages, tool calls, tool results) is opened like a code repository: one file per step, read and
search tools, and a typed report (error type, steps, quotes, explanation, severity). On 262 held-out runs in two
domains and four languages (de, fr, it, en), the two tiers reach a balanced accuracy of 0.68 against 0.70 for the
70B alone, with about half the false alarms (0.19 vs 0.38), while the 70B reads only about 56 % of the runs.
Details, negative results included: [technical_report.md](technical_report.md).

## Run it

You need Docker and an OpenAI-compatible endpoint serving Apertus. For the hackathon that is the CSCS API.

```bash
cp .env.example .env      # then put your key into LLM_API_KEY
make run                  # builds the image and starts the app
```

Open http://localhost:8000. `make run` first checks that the model answers, then serves three views:

- **Break the agent**: pick a recorded agent run, choose a sabotage ("skip a check the policy requires",
  "release a lot without quality approval", ...) or none, and watch the 8B screen it and the 70B confirm it live.
  The broken steps and the cited steps are highlighted, each quote shows whether it was found verbatim, and the page
  says whether the sabotage was caught. One audit takes about 5 to 60 s and roughly 5k to 60k tokens.
- **Fleet**: replays the 262 measured test runs through both tiers, with a cost meter (no model calls).
- **Review findings**: development runs with their precomputed 70B findings. Confirm each one, reject it as a false
  alarm, or mark it for follow-up; decisions go into a hash-chained trail (`reviews/review_log.jsonl`) whose
  integrity the page shows (no model calls).

Settings, all read from `.env` or the environment:

| Variable | Meaning | Default in `.env.example` |
|---|---|---|
| `LLM_BASE_URL` | OpenAI-compatible endpoint | `https://api.inference.cscs.ch/v1` |
| `LLM_NAME` | model checked at start-up | `swiss-ai/Apertus-v1.5-8B` |
| `LLM_API_KEY` | key for that endpoint | (empty) |

Which model does which job, and the optional parts (screener bookmarks, handoff, human review, the screener's
token cap) are set in [pipeline.toml](pipeline.toml).

## Run it on your own servers (on-prem, air-gapped)

At runtime nothing leaves your network: the container talks only to your model servers. Download the weights once
(build time), then serve them with vLLM:

```bash
vllm serve andreasmartin/apertus-v1.5-8b-text --served-model-name swiss-ai/Apertus-v1.5-8B \
    --dtype bfloat16 --max-model-len 16384 --enable-auto-tool-choice --tool-call-parser apertus \
    --chat-template-content-format string
```

The 8B needs one GPU with at least 24 GB and must run in bfloat16 (its activations overflow float16). The 70B needs
two 80 GB GPUs; serve `swiss-ai/Apertus-v1.5-70B` following swiss-ai's instructions for v1.5. Then point the app at
your servers: `LLM_BASE_URL=http://host.docker.internal:8000/v1` in `.env` (Docker Desktop reaching a server on the
same machine; on Linux use the host's address), and one `base_url` per tier in `pipeline.toml` if the models run on different machines. Without a
70B, remove the `[confirmer]` table and the 8B's verdict is final.

We ran the auditor with the network cut and measured it with the kernel's byte counters: see "Offline run,
measured" in the report and `results/offline-proof/`.

## Audit your own agent

Write your runs as JSON lines, one run per line, and your agent's rules as plain text:

```json
{"trace_id": "my-run-1", "domain": "refunds", "language": "en", "policy_id": "my-policy",
 "agent": {"name": "support-agent", "description": "Answers refund requests"},
 "spans": [
  {"id": "000", "kind": "user_message", "text": "Please refund order A-1."},
  {"id": "001", "kind": "tool_call", "tool": "get_order", "call_id": "c1", "args": {"order_id": "A-1"}},
  {"id": "002", "kind": "tool_result", "tool": "get_order", "call_id": "c1", "status": "ok",
   "result": {"refundable": false}},
  {"id": "003", "kind": "agent_message", "text": "Your refund is on its way."}]}
```

```bash
pip install -e .
python -m rosetta_flow.pipeline --traces my_runs.jsonl --policy-file my_policy.md --out results/my-audit
```

`results/my-audit/pipeline.jsonl` holds both tiers' reports per run, `summary.json` the verdicts, tokens and cost.
For a single model, use `python -m rosetta_flow.harness` with the same arguments.

## What is in this folder

| Path | What |
|---|---|
| `src/rosetta_flow/harness/` | the investigation harness: trace as repository, tools, report schema, evidence check |
| `src/rosetta_flow/pipeline.py`, `pipeline.toml` | the two tiers and their switches |
| `src/rosetta_flow/gen/` | simulated agents (refunds, manufacturing), error injectors with exact labels, tau-bench converter |
| `src/rosetta_flow/eval/` | scoring: balanced accuracy, strict F1, false alarms, localisation, evidence |
| `src/rosetta_flow/train/`, `screen.py` | LoRA distillation and the GRPO screener (both reported as experiments) |
| `src/rosetta_flow/app/` | the web app (FastAPI); `app/static/` holds the built front end |
| `web/` | front-end source (React + Chakra UI v3, Vite). `cd web && npm install && npm run build` writes the bundle into `app/static/`; the bundle is committed, so Docker needs no Node |
| `data/demo/` | the runs and results the app shows |
| `results/` | score tables of every evaluation in the report |
| `scripts/` | Hugging Face Jobs launchers for training, evaluation and the offline proof |

**Demo video:** [youtu.be/zZuEkJsSdbQ](https://youtu.be/zZuEkJsSdbQ) (1:53).

**Weights and data on Hugging Face:** LoRA adapters
[anesdevtoday/rosetta-flow-auditor-lora](https://huggingface.co/anesdevtoday/rosetta-flow-auditor-lora) (Apache-2.0),
dataset [anesdevtoday/rosetta-flow-traces](https://huggingface.co/datasets/anesdevtoday/rosetta-flow-traces)
(CDLA-Permissive-2.0; tau-bench subset MIT).

Code: Apache-2.0. The manufacturing domain follows the concept of the author's earlier project NeuralLine. Credits and sources are in
the report.

---

*Below: the organisers' challenge description for Track 2B, kept as provided.*

# Track 2 B: Own Project

Bring your own idea and build a working Apertus prototype that tackles a problem you care about — any domain, any use case. The project must be new, started within the hackathon period.

Submissions must use the Apertus model family.
For Track 2 this means that submitted solutions must be built with Apertus. Other open-weights models can be used to support development, e.g. as automatic judges during evaluation. Their role must be clearly described in the submission report.

💬 In case you have questions, join the conversation on [Discord](https://discord.gg/hack-apertus) or send an email to “hello@hackapertus.ch”

---

## 🔧 Resources & Tools

Check our resources & tools page for detailed information:
https://hackapertus.notion.site/resources-tools

| Models           | URL                                      |
|------------------|------------------------------------------|
| Apertus v1.5 8B  | [huggingface.co/swiss-ai/Apertus-v1.5-8B](https://huggingface.co/swiss-ai/Apertus-v1.5-8B)  |
| Apertus v1.5 70B | [huggingface.co/swiss-ai/Apertus-v1.5-70B](https://huggingface.co/swiss-ai/Apertus-v1.5-70B) |


## Target architecture (mandatory)

Whatever you build in Track 2B must be deployable in one of these three architectures:

- **a) On-premise** — on the organisation's own infrastructure, under its own administration.
- **b) Air-gapped** — with no external network connection at runtime.
- **c) Sovereign Swiss cloud** — on a cloud platform operated in Switzerland, under Swiss jurisdiction, with Swiss data residency.

---

## Data

The `data/` directory must not exceed 100 MB.

---

## 📦 Submission Requirements & Deliverables

❗️ Submissions are not handled on Devpost but via this URL only:
http://hackapertus.ch/online-hack/submissions

The submission must: 
1. follow the template repo and include all prerequisite files and definitions
2. follow the specified input/output formats
3. run in a Docker container, launched with `make run` from the root of the project
4. run end-to-end when judges try to run it

### Git repo (URL)
- Create your repo from this template (**Use this template**) and work in the `track_2b/` challenge directory. Delete the other track challenge directories.
- Keep `track_2b/` as it is: don't rename it or move its files.
- Set the repo to PUBLIC (Settings --> Collaborators --> Manage Visibility)
- Submit the URL of YOUR Git repo.

### Technical Report (pdf)
- Update [technical_report.md](technical_report.md) in this repository with all the details for your submission.
- Upload a pdf of your technical report to this directory, named as `TeamName_Report.pdf`.
- Format: pdf, max. 6 pages
- Submit the pdf of the technical report.

### Demo video (URL)
- Max. 2 min demo video of your prototype

### Dataset (URL) - optional, depending on your project
Submitted datasets must comply with our guidelines for responsibly sourced datasets.

- Create a user account on Hugging Face
- Clone our dataset template on Hugging Face: https://huggingface.co/datasets/HackApertus/online_hack_template
- Complete the dataset card with all required information
- Upload your dataset. It should consist of the following components:
    - evaluation dataset (i.e. individual test cases)
    - model response dataset (i.e. the model response to each test case)
    - metadata file (i.e. additional information about each test case; where relevant, this file must contain instance-level licensing information) 
- Make sure your dataset access control is set to PUBLIC
- Provide the URL of _your_ data set


---

## ⚖️ Judging Criteria

1. Purposeful use of AI
2. Technical rigour
3. Value, cost & scalability
4. Sovereign deployability
5. Implementation feasibility

Judges use a Scale 0–5 per dimension.

---

## Support

**Licensing requirements**
Please check our Terms & Conditions (6. What you build is open source):
https://hackapertus.ch/terms-and-conditions

## FAQ
💡 https://hackapertus.ch/faq

## Contact
💬 In case you have questions, join the conversation on Discord or send an email to “hello@hackapertus.ch”
