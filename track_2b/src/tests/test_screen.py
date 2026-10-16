"""Calibrated screener offline: answer parsing, the RL reward, calibration metrics and the escalation curve."""

from rosetta_flow.screen import Decision, calibration, threshold_curve
from rosetta_flow.trace import ErrorType, Label, LabeledError
from rosetta_flow.train.rl import parse_decision, reward, score


def test_decision_parsing_accepts_only_valid_answers():
    ok = parse_decision('thinking... {"verdict": "issues_found", "p_issue": 0.8, "suspicious_spans": ["5", 6, "x"]}')
    assert ok == {"verdict": "issues_found", "p_issue": 0.8, "suspicious_spans": ["005", "006"]}
    for bad in ['{"verdict": "maybe", "p_issue": 0.5}', '{"verdict": "ok", "p_issue": 1.5}', '{"verdict": "ok"}',
                '{"verdict": "ok", "p_issue": true}', "no json", "{" * 5000]:  # fmt: skip
        assert parse_decision(bad) is None


def test_reward_prefers_calibrated_honest_answers():
    def r(p, verdict, spans, has_issue=True, label=("005",)):
        return score({"verdict": verdict, "p_issue": p, "suspicious_spans": spans}, has_issue, list(label))["total"]

    assert r(0.9, "issues_found", ["005"]) > r(0.9, "issues_found", ["001"])  # right span earns more
    assert r(0.9, "issues_found", ["005"]) > r(0.6, "issues_found", ["005"])  # confident and right beats hedging
    assert r(0.05, "ok", [], has_issue=False) > r(0.4, "ok", [], has_issue=False)
    assert r(0.95, "issues_found", [], has_issue=False) < r(
        0.6, "issues_found", [], has_issue=False
    )  # overconfident miss costs most
    assert r(0.9, "ok", ["005"]) < r(0.9, "issues_found", ["005"])  # verdict must match the probability
    assert score(None, True, ["005"])["total"] < r(0.0, "ok", [])  # unparseable is worst
    answer = [{"role": "assistant", "content": '{"verdict": "ok", "p_issue": 0.1, "suspicious_spans": []}'}]
    batch = reward([answer, "junk"], [False, True], [[], ["005"]])
    assert batch[0] > 0 > batch[1]


def test_calibration_and_threshold_curve():
    assert calibration([(0.9, True), (0.1, False)])["brier"] == 0.01
    assert calibration([(1.0, False), (1.0, False)])["ece"] == 1.0
    error = LabeledError(type=ErrorType.WRONG_ORDER, span_ids=["001"])
    labels = {"a": Label(trace_id="a", source="clean"), "b": Label(trace_id="b", source="injected", errors=[error])}

    def d(t, p):
        return Decision(t, "m", "issues_found" if p >= 0.5 else "ok", p, [], None, 0.1, {})

    confirm = {"a": {"report": {"verdict": "ok"}}, "b": {"report": {"verdict": "issues_found"}}}
    curve = {row["threshold"]: row for row in threshold_curve({"a": d("a", 0.2), "b": d("b", 0.7)}, labels, confirm)}
    assert curve[0.1]["escalated"] == 1.0 and curve[0.5]["escalated"] == 0.5 and curve[0.9]["escalated"] == 0.0
    assert curve[0.5]["balanced_acc"] == 1.0 and curve[0.9]["recall"] == 0.0
