import pytest

from rosetta_flow.llm import REQUIRED_VARS, LLMConfig


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("LLM_NAME", "swiss-ai/Apertus-v1.5-8B")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.ch/v1/")
    monkeypatch.setenv("LLM_API_KEY", "secret-key")
    cfg = LLMConfig.from_env()
    assert (cfg.name, cfg.base_url) == ("swiss-ai/Apertus-v1.5-8B", "https://example.ch/v1")
    assert "secret-key" not in repr(cfg)

    for v in REQUIRED_VARS:
        monkeypatch.delenv(v)
    with pytest.raises(RuntimeError, match="LLM_NAME, LLM_BASE_URL, LLM_API_KEY"):
        LLMConfig.from_env()


def test_lenient_json_repairs_broken_quotes_but_not_deep_nesting():
    import time

    from rosetta_flow.llm import loads_lenient

    # the 8B's typical slip: quoting a JSON tool result inside an evidence string, one bracket too many
    broken = (
        '{"verdict": "issues_found", "findings": [{"error_type": "x", '
        '"evidence": ["a", "{\\"status\\": \\"issued\\""]]}]}'
    )
    repaired = loads_lenient(broken)
    assert repaired["verdict"] == "issues_found" and repaired["findings"][0]["evidence"][0] == "a"
    assert loads_lenient('{"a": 1}') == {"a": 1} and loads_lenient("not json at all") is None
    t0 = time.perf_counter()
    assert loads_lenient("{" * 5000) is None and loads_lenient("x" * 50_000) is None
    assert time.perf_counter() - t0 < 0.1  # refused before the slow repair


def test_tool_names_lose_leaked_template_tokens():
    from types import SimpleNamespace as NS

    from rosetta_flow.llm import tool_calls_of

    leaked = NS(id="a", function=NS(name='tool_output_end|><|tools_prefix|>[{"report', arguments='{"verdict": "ok"}'))
    plain = NS(id="b", function=NS(name="read_spans", arguments="{}"))
    names = [c.name for c in tool_calls_of(NS(content=None, tool_calls=[leaked, plain]))]
    assert names == ["report", "read_spans"]
