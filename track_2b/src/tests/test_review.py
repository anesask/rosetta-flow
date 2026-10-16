"""Human review log: decisions, revisions, and tamper evidence."""

import json

import pytest

from rosetta_flow.review import ReviewLog


def test_review_trail_keeps_revisions_and_detects_tampering(tmp_path):
    log = ReviewLog(tmp_path / "reviews.jsonl")
    log.add("t1", 0, "false_alarm", "anes", "  agent was right ")
    log.add("t2", 0, "confirmed", "anes")
    log.add("t1", 0, "confirmed", "qa-lead", "second look")  # revision: the trail keeps both
    assert [r.decision for r in log.entries()] == ["false_alarm", "confirmed", "confirmed"]
    assert log.latest()[("t1", 0)].reviewer == "qa-lead" and log.entries()[0].note == "agent was right"
    assert log.verify() is None

    lines = log.path.read_text(encoding="utf-8").splitlines()
    edited = json.loads(lines[1]) | {"decision": "false_alarm"}  # someone rewrites history
    log.path.write_text("\n".join([lines[0], json.dumps(edited), lines[2]]) + "\n", encoding="utf-8")
    assert log.verify() == 1
    log.path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")  # or deletes an entry
    assert log.verify() == 1

    with pytest.raises(ValueError, match="decision"):
        log.add("t1", 0, "looks fine", "anes")
    with pytest.raises(ValueError, match="reviewer"):
        log.add("t1", 0, "confirmed", "  ")
