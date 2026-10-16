"""Review buttons in the web app: decisions land in the hash-chained trail, bad input is refused."""

from fastapi.testclient import TestClient

from rosetta_flow.app.server import create_app


def _flagged_run(client):
    return next(r["trace_id"] for r in client.get("/api/runs").json() if r["findings"])


def test_review_is_recorded_and_the_trail_stays_intact(tmp_path):
    client = TestClient(create_app(cfg=None, review_log=tmp_path / "log.jsonl"))
    run = _flagged_run(client)
    for decision in ("false_alarm", "confirmed"):  # a reviewer may revise; the trail keeps both
        r = client.post("/api/review", json={"trace_id": run, "finding": 0, "decision": decision, "reviewer": "qa"})
        assert r.status_code == 200
    trail = client.get("/api/review").json()
    assert trail["count"] == 2 and trail["intact"] and trail["latest"][f"{run}#0"] == "confirmed"


def test_review_refuses_unknown_findings_and_decisions(tmp_path):
    client = TestClient(create_app(cfg=None, review_log=tmp_path / "log.jsonl"))
    run = _flagged_run(client)
    bad = [{"trace_id": "nope", "finding": 0, "decision": "confirmed", "reviewer": "qa"},
           {"trace_id": run, "finding": 99, "decision": "confirmed", "reviewer": "qa"},
           {"trace_id": run, "finding": 0, "decision": "maybe", "reviewer": "qa"},
           {"trace_id": run, "finding": 0, "decision": "confirmed", "reviewer": " "}]  # fmt: skip
    assert [client.post("/api/review", json=b).status_code for b in bad] == [404, 404, 422, 422]
    assert client.get("/api/review").json()["count"] == 0
