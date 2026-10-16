"""The two-tier pipeline offline: escalation rules, configuration, and the screener -> confirmer handoff."""

from pathlib import Path

import pytest
from test_harness import CTX, GOOD_FINDING, POLICY, READ_ALL, TRACE, _report, _resp

from rosetta_flow import llm
from rosetta_flow.pipeline import PipelineConfig, Tier, escalates, run

SMALL, LARGE = "small", "large"


def _models(monkeypatch, replies: dict[str, list]):
    """Fake chat that answers per model and records the task message each model saw."""
    queues, seen = {m: iter(r) for m, r in replies.items()}, {}

    def chat(cfg, messages, model=None, **_):
        seen.setdefault(model, messages[1]["content"])
        return next(queues[model])

    monkeypatch.setattr(llm, "chat", chat)
    return seen


def test_config_reads_the_shipped_toml_and_rejects_inconsistent_options(tmp_path):
    shipped = PipelineConfig.from_toml(Path(__file__).parents[2] / "pipeline.toml")
    assert shipped.confirmer is not None and not shipped.bookmarks and not shipped.handoff and not shipped.review
    one_tier = tmp_path / "p.toml"
    one_tier.write_text('[screener]\nmodel = "m"\n', encoding="utf-8")
    assert PipelineConfig.from_toml(one_tier).confirmer is None
    with pytest.raises(ValueError, match="handoff needs bookmarks"):
        PipelineConfig(Tier("m"), handoff=True)
    with pytest.raises(ValueError, match="unknown escalation"):
        PipelineConfig(Tier("m"), escalate_on=frozenset({"always"}))


def test_only_flagged_or_failed_runs_reach_the_confirmer(monkeypatch):
    config = PipelineConfig(Tier(SMALL), Tier(LARGE))
    _models(monkeypatch, {SMALL: [READ_ALL, _report(verdict="ok")]})
    cleared = run(TRACE, POLICY, config, CTX.cfg)
    assert not cleared.escalated and cleared.final.report.verdict == "ok"

    _models(monkeypatch, {SMALL: [READ_ALL, _report(GOOD_FINDING)], LARGE: [READ_ALL, _report(verdict="ok")]})
    overruled = run(TRACE, POLICY, config, CTX.cfg)
    assert overruled.escalated and overruled.final.report.verdict == "ok"  # the confirmer's verdict is final
    assert not escalates(cleared.screen) and escalates(overruled.screen)
    assert not escalates(overruled.screen, frozenset({"failed"}))  # rules are configurable


def test_handoff_gives_the_confirmer_the_screeners_bookmarks_only_when_on(monkeypatch):
    bookmark = _resp(None, [("bookmark", '{"span_id": "005", "note": "eligible false"}')])
    for handoff in (False, True):
        seen = _models(monkeypatch, {
            SMALL: [bookmark, READ_ALL, _report(GOOD_FINDING)],
            LARGE: [READ_ALL, _report(GOOD_FINDING)],
        })  # fmt: skip
        result = run(TRACE, POLICY, PipelineConfig(Tier(SMALL), Tier(LARGE), bookmarks=True, handoff=handoff), CTX.cfg)
        assert result.screen.bookmarks == [{"span_id": "005", "note": "eligible false"}]
        assert ("eligible false" in seen[LARGE]) is handoff
        assert result.meta["handoff"] is handoff
