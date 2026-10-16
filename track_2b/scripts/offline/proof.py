"""Offline proof, audit phase: runs inside scripts/offline_job.sh after the network is cut. Tries to reach the
internet (must fail), then breaks recorded agent runs and audits them with the local Apertus 8B, exactly as the
web app's "Break the agent" does. Writes /tmp/offline/audits.json.

Args: LIVE_DIR (bundled demo runs) and pairs RUN_ID:SABOTAGE (empty sabotage = control run).
"""

import json
import sys
import urllib.request
from pathlib import Path

from rosetta_flow.app import live
from rosetta_flow.llm import LLMConfig
from rosetta_flow.pipeline import PipelineConfig, Tier

OUT = Path("/tmp/offline")


def main() -> int:
    live_dir, cases = Path(sys.argv[1]), [c.split(":", 1) for c in sys.argv[2:]]
    try:
        urllib.request.urlopen("https://huggingface.co", timeout=10)
        reach = "REACHED huggingface.co: the network is NOT cut"
    except Exception as e:
        reach = f"cannot reach huggingface.co: {type(e).__name__}: {e}"
    print("internet check:", reach, flush=True)

    runs = live.load(live_dir)
    config = PipelineConfig(Tier("apertus-8b-local"), None)  # one GPU: the 8B screener is the whole pipeline
    llm = LLMConfig.from_env()
    results = []
    for run_id, sabotage in cases:
        events = list(live.stream(runs[run_id], sabotage or None, config, llm))
        done = next(e for e in events if e["event"] in ("done", "error"))
        screened = next((e["result"] for e in events if e["event"] == "screened"), None)
        truth = next((e["truth"] for e in events if e["event"] == "run"), {})
        row = {"run": run_id, "sabotage": sabotage or None, "truth_spans": truth.get("span_ids"),
               "verdict": done.get("verdict"), "caught": done.get("caught"), "error": done.get("message"),
               "findings": [(f["error_type"], f["span_ids"]) for f in screened["findings"]] if screened else None,
               "quotes_verified": [e["verified"] for e in screened["evidence"]] if screened else None,
               "seconds": done.get("seconds"), "tokens": screened["tokens"] if screened else None}  # fmt: skip
        results.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    (OUT / "audits.json").write_text(json.dumps({"internet_check": reach, "audits": results}, indent=2,
                                                ensure_ascii=False) + "\n", encoding="utf-8")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
