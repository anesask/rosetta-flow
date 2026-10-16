"""Training data offline: which investigations are kept, and that kept ones become clean SFT examples."""

import json

from test_harness import CTX, GOOD_FINDING, POLICY, READ_ALL, TRACE, _report, _resp

from rosetta_flow import llm
from rosetta_flow.eval.metrics import investigation_matches
from rosetta_flow.harness.audit import audit
from rosetta_flow.trace import ErrorType, Label, LabeledError
from rosetta_flow.train.sft import build_example

ERROR = Label(
    trace_id=TRACE.trace_id,
    source="injected",
    errors=[LabeledError(type=ErrorType.CONTRADICTS_TOOL_RESULT, span_ids=["005", "006"])],
)
CLEAN = Label(trace_id=TRACE.trace_id, source="clean")


def _replay(monkeypatch, steps):
    steps = iter(steps)
    monkeypatch.setattr(llm, "chat", lambda *a, **k: next(steps))
    return audit(TRACE, POLICY, CTX)


def test_only_investigations_that_reach_the_label_are_kept(monkeypatch):
    hit = _replay(monkeypatch, [READ_ALL, _report(GOOD_FINDING)])
    assert investigation_matches(hit, ERROR) == (True, "")
    assert investigation_matches(hit, CLEAN)[0] is False  # the same report is a false alarm on a clean trace
    stray = dict(GOOD_FINDING, span_ids=["001"], evidence=["Look up the order, then check refund eligibility"])
    noisy = _replay(monkeypatch, [READ_ALL, _resp(None, [("read_spans", '["001"]')]), _report(GOOD_FINDING, stray)])
    assert investigation_matches(noisy, ERROR) == (False, "1 finding(s) on unlabelled spans")
    ok = _replay(monkeypatch, [READ_ALL, _report(verdict="ok")])
    assert investigation_matches(ok, CLEAN) == (True, "") and investigation_matches(ok, ERROR)[0] is False


def test_sft_example_is_the_clean_path_of_a_messy_investigation(monkeypatch):
    # First report cites unopened spans (rejected), then the model reads 005 twice, then reports again.
    messy = _replay(
        monkeypatch,
        [
            _resp("Looking around.", [("list_spans", '{"reason": "overview"}')]),
            _report(GOOD_FINDING),
            _resp("Reading.", [("read_spans", '{"span_ids": ["005"]}')]),
            _resp("Again.", [("read_spans", '{"span_ids": ["005"]}')]),
            _report(GOOD_FINDING),
            _report(GOOD_FINDING),
        ],
    )
    assert messy.report is not None and investigation_matches(messy, ERROR)[0]
    ex = build_example(messy.to_record(), TRACE, POLICY)
    msgs = ex["messages"]
    text = json.dumps(msgs, ensure_ascii=False)
    assert "not accepted" not in text and "Continue the audit" not in text  # no harness corrections
    calls = [(m["tool_calls"][0]["function"]["name"], m["tool_calls"][0]["function"]["arguments"])
             for m in msgs if m.get("tool_calls")]  # fmt: skip
    names = [c[0] for c in calls]
    assert names[0] == "list_spans" and names[-1] == "report" and names.count("report") == 1
    reads = [sid for n, a in calls if n == "read_spans" for sid in json.loads(a)["span_ids"]]
    assert sorted(reads) == ["005", "006"]  # each span once; 006 was only handed over, now opened explicitly
    ids = [m["tool_calls"][0]["id"] for m in msgs if m.get("tool_calls")]
    answered = [m["tool_call_id"] for m in msgs if m["role"] == "tool"]
    assert answered == ids[:-1]  # every investigation call answered, the final report ends the conversation
    assert json.loads(calls[-1][1])["verdict"] == "issues_found"


def test_qlora_loss_covers_only_the_auditors_own_moves():
    from rosetta_flow.train.qlora import token_labels, trainable_spans

    text = (
        "<s><|system_start|>sys<|system_end|><|user_start|>task<|user_end|><|assistant_start|>Reading."
        '<|tools_prefix|>[{"read_spans": {}}]<|tools_suffix|><|tool_output_start|>span text<|tool_output_end|>'
        '<|tools_prefix|>[{"report": {}}]<|tools_suffix|>'
    )
    trained = [text[a:b] for a, b in trainable_spans(text)]
    assert trained == ['Reading.<|tools_prefix|>[{"read_spans": {}}]<|tools_suffix|>',
                       '<|tools_prefix|>[{"report": {}}]<|tools_suffix|>']  # fmt: skip
    offsets = [(0, 3), (3, 10), (text.index("Reading."), text.index("Reading.") + 8), (text.index("span text"), 0)]
    assert token_labels(offsets, [1, 2, 3, 4], trainable_spans(text)) == [-100, -100, 3, -100]
