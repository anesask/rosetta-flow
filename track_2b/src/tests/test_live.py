"""Break the agent, offline: sabotage stays exact, and the live stream reports both tiers and whether it was caught."""

from test_harness import CTX, GOOD_FINDING, READ_ALL, TRACE, _report

from rosetta_flow import llm
from rosetta_flow.app.live import LiveRun, stream
from rosetta_flow.pipeline import PipelineConfig, Tier


def _events(monkeypatch, replies: dict[str, list], sabotage=None):
    queues = {m: iter(r) for m, r in replies.items()}
    monkeypatch.setattr(llm, "chat", lambda cfg, messages, model=None, **_: next(queues[model]))
    run = LiveRun(TRACE, world_seed=0, intent="test")
    return list(stream(run, sabotage, PipelineConfig(Tier("small"), Tier("large")), CTX.cfg))


def test_live_stream_reports_each_tier_in_order(monkeypatch):
    events = _events(
        monkeypatch, {"small": [READ_ALL, _report(GOOD_FINDING)], "large": [READ_ALL, _report(GOOD_FINDING)]}
    )
    tools = [e for e in events if e["event"] == "tool"]
    rest = [e for e in events if e["event"] != "tool"]
    assert [e["event"] for e in rest] == ["run", "tier", "screened", "tier", "confirmed", "done"]
    assert rest[2]["escalated"] is True and rest[-1]["verdict"] == "issues_found"
    # each tool call is streamed as it happens, tagged with its tier
    assert [t["tier"] for t in tools] == ["screener"] * (len(tools) // 2) + ["confirmer"] * (len(tools) // 2)
    assert tools and all(t["name"] for t in tools)
    assert events[-1]["caught"] is None  # nothing was sabotaged, so there is nothing to catch

    cleared = _events(monkeypatch, {"small": [READ_ALL, _report(verdict="ok")]})
    assert [e["event"] for e in cleared if e["event"] != "tool"] == [
        "run",
        "tier",
        "screened",
        "done",
    ]  # the 70B never ran


def test_unknown_sabotage_is_an_error_event_not_a_crash(monkeypatch):
    events = _events(monkeypatch, {}, sabotage="does_not_exist")
    assert events == [{"event": "error", "message": "sabotage 'does_not_exist' does not fit this run"}]
