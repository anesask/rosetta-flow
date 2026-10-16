"""Verify mode: the confirmer checks the screener's findings in one prompt, also on the -thinking variants."""

import json

import pytest
from test_harness import CTX, GOOD_FINDING, POLICY, TRACE, _resp

from rosetta_flow import llm
from rosetta_flow.harness.schema import AuditReport
from rosetta_flow.harness.verify import verify
from rosetta_flow.llm import LLMContext
from rosetta_flow.pipeline import PipelineConfig, Tier, confirm

SCREENED = AuditReport.model_validate({"verdict": "issues_found", "findings": [GOOD_FINDING]})
OK = json.dumps({"verdict": "ok", "findings": []})
CONFIRMED = json.dumps({"verdict": "issues_found", "findings": [GOOD_FINDING]})


def _replay(monkeypatch, *texts):
    texts, sent = list(texts), []

    def chat(cfg, messages, model=None, **kw):
        sent.append({"model": model, "kw": kw, "user": messages[1]["content"]})
        return _resp(texts.pop(0))

    monkeypatch.setattr(llm, "chat", chat)
    return sent


def test_verify_confirms_with_checked_evidence_and_shows_the_screener_findings_as_data(monkeypatch):
    sent = _replay(monkeypatch, CONFIRMED)
    result = verify(TRACE, POLICY, CTX, SCREENED)
    assert result.report.verdict == "issues_found" and result.evidence[0].verified
    assert sent[0]["kw"]["response_format"] == {"type": "json_object"}  # plain model: JSON mode
    assert "The screener's findings to check" in sent[0]["user"] and "Answer with the report JSON" in sent[0]["user"]


def test_thinking_model_reasons_first_and_json_inside_its_reasoning_is_not_the_answer(monkeypatch):
    reasoning = f"<|inner_prefix|>Maybe the report is {CONFIRMED}? No, step 006 is fine.<|inner_suffix|>"
    sent = _replay(monkeypatch, reasoning + OK)
    result = verify(TRACE, POLICY, LLMContext(CTX.cfg, "swiss-ai/Apertus-v1.5-70B-thinking"), SCREENED)
    assert result.report.verdict == "ok"  # the answer after the reasoning, not the JSON quoted inside it
    assert "response_format" not in sent[0]["kw"] and "Think it through" in sent[0]["user"]


def test_failed_screener_gets_a_full_audit_in_one_prompt(monkeypatch):
    sent = _replay(monkeypatch, OK)
    verify(TRACE, POLICY, CTX, None)
    assert "could not finish its audit" in sent[0]["user"]


def test_pipeline_confirmer_mode_picks_verify_and_unknown_modes_are_refused(monkeypatch):
    _replay(monkeypatch, OK)
    config = PipelineConfig(Tier("small"), Tier("large-thinking", mode="verify"))
    screen = type("S", (), {"report": SCREENED})()
    assert confirm(TRACE, POLICY, config, CTX.cfg, screen).tool_calls == 0  # one prompt, no investigation
    with pytest.raises(ValueError, match="unknown tier mode"):
        Tier("x", mode="think")
