"""The live runner: explicit provider config, state → events, and clear failures."""

import time
from types import SimpleNamespace

import pytest
import requests

from tests.webui_helpers import make_run
from tradingagents.dataflows.symbols import safe_ticker_component
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.reporting import write_report_tree
from webui.events import set_active_run
from webui.runner import (
    RunRequest,
    build_config,
    graph_analysts,
    preflight,
    start_run,
    state_to_events,
)


def _req(**kw):
    base = {"ticker": "AAPL", "trade_date": "2026-11-06", "analysts": ["market"], "provider": "ollama",
                "quick_model": "qwen3:4b", "deep_model": "qwen3:4b",
                "ollama_url": "http://localhost:11434/v1", "debate_rounds": 1, "risk_rounds": 1}
    return RunRequest(**{**base, **kw})


CHUNKS = [
    ([], None),
    ([], {"market_report": "m"}),
    ([], {"investment_debate_state": {"bull_history": "b", "bear_history": ""},
          "investment_plan": "p"}),
    ([], {"trader_investment_plan": "t",
          "final_trade_decision": "**Rating**: Hold\n\nok"}),
]


class FakeGraph:
    def __init__(self, tmp, chunks=CHUNKS, fail=False):
        self.tmp, self.chunks, self.fail = tmp, chunks, fail
        self.propagator = SimpleNamespace(get_graph_args=lambda: {})
        self.recorded = False

    def __call__(self, selected_analysts, config):
        self.selected, self.config = selected_analysts, config
        return self

    def create_run_state(self, ticker, date):
        return {}

    def stream_run(self, state, **args):
        yield from self.chunks
        if self.fail:
            raise RuntimeError("model fell over")

    def record_decision(self, *a):
        self.recorded = True

    def default_report_path(self, ticker):
        return self.tmp / f"{safe_ticker_component(ticker)}_x"

    def save_reports(self, final_state, ticker, path, html=True):
        return write_report_tree(final_state, ticker, path, html=False)


def _drain(h, timeout=5):
    deadline = time.monotonic() + timeout
    while not h.finished and time.monotonic() < deadline:
        time.sleep(0.01)
    return h.events_since(0)


@pytest.fixture(autouse=True)
def _no_active_run():
    yield
    set_active_run(None)


@pytest.mark.unit
def test_config_provider_is_explicit(monkeypatch):
    monkeypatch.setitem(DEFAULT_CONFIG, "llm_provider", "openai")
    monkeypatch.setitem(DEFAULT_CONFIG, "deep_think_provider", "openai")
    monkeypatch.setitem(DEFAULT_CONFIG, "quick_think_backend_url", "https://api.openai.com/v1")
    cfg = build_config(_req(provider="ollama", debate_rounds=2, risk_rounds=3))
    assert cfg["llm_provider"] == "ollama" and cfg["deep_think_provider"] is None
    assert cfg["quick_think_backend_url"] is None
    assert cfg["backend_url"] == "http://localhost:11434/v1"
    assert (cfg["max_debate_rounds"], cfg["max_risk_discuss_rounds"]) == (2, 3)
    assert cfg["checkpoint_enabled"] is False and cfg["output_language"] == "English"
    assert DEFAULT_CONFIG["llm_provider"] == "openai"   # the shared default is untouched


@pytest.mark.unit
def test_openai_backend_url():
    assert build_config(_req(provider="openai"))["backend_url"] == "https://api.openai.com/v1"


@pytest.mark.unit
def test_ticker_normalized():
    assert _req(ticker=" aapl ").ticker == "AAPL"


@pytest.mark.unit
def test_sentiment_maps_to_social():
    assert graph_analysts(["market", "sentiment"]) == ["market", "social"]


@pytest.mark.unit
def test_state_to_events_dedupes():
    seen = {}
    state = {"market_report": "m", "investment_debate_state": {"bull_history": "b"}}
    assert [e.stage for e in state_to_events(state, seen)] == ["market", "bull"]
    assert state_to_events(state, seen) == []
    state["investment_debate_state"] = {"bull_history": "b2"}
    evs = state_to_events(state, seen)
    assert [(e.stage, e.title, e.content) for e in evs] == [("bull", "Bull Researcher", "b2")]


@pytest.mark.unit
def test_full_run_emits_reports_then_done(tmp_path):
    graph = FakeGraph(tmp_path)
    evs = _drain(start_run(_req(analysts=["market", "sentiment"]), graph_factory=graph))
    assert graph.selected == ["market", "social"] and graph.config["llm_provider"] == "ollama"
    assert [e.stage for e in evs if e.kind == "stage"] == ["market", "sentiment"]
    assert [e.stage for e in evs if e.kind == "report"] == ["market", "bull", "manager", "trader", "portfolio"]
    done = evs[-1]
    assert done.kind == "done" and done.rating == "Hold"
    assert (tmp_path / "AAPL_x" / "complete_report.md").is_file() and done.report_dir == str(tmp_path / "AAPL_x")
    assert graph.recorded


@pytest.mark.unit
def test_exception_becomes_error_event(tmp_path):
    evs = _drain(start_run(_req(), graph_factory=FakeGraph(tmp_path, fail=True)))
    assert evs[-1].kind == "error"
    assert evs[-1].content == "The run stopped: model fell over"
    assert "RuntimeError" in evs[-1].detail


@pytest.mark.unit
def test_bad_ticker_becomes_error_event(tmp_path):
    evs = _drain(start_run(_req(ticker="../x"), graph_factory=FakeGraph(tmp_path)))
    assert evs[-1].kind == "error" and evs[-1].content.startswith("The run stopped:")
    assert not any(p.name.startswith("..") for p in tmp_path.iterdir())


def _models(*ids):
    return lambda *a, **k: SimpleNamespace(json=lambda: {"data": [{"id": i} for i in ids]},
                                           raise_for_status=lambda: None)


@pytest.mark.unit
def test_preflight_ollama_down():
    def get(*a, **k):
        raise requests.ConnectionError()
    assert preflight(_req(), get=get) == "Ollama isn't running. Start it with `ollama serve`."


@pytest.mark.unit
def test_preflight_model_missing():
    assert preflight(_req(), get=_models("llama3.2:3b")) == (
        "Model `qwen3:4b` isn't installed. Run `ollama pull qwen3:4b`.")


@pytest.mark.unit
def test_preflight_ok():
    assert preflight(_req(), get=_models("qwen3:4b", "llama3.2:3b")) is None


@pytest.mark.unit
def test_preflight_openai_no_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    assert preflight(_req(provider="openai")) == "No OpenAI key in `.env`."
    monkeypatch.setenv("OPENAI_API_KEY", "placeholder")
    assert preflight(_req(provider="openai")) is None


@pytest.mark.unit
def test_saved_run_is_listed_in_history(tmp_path):
    # The saved report from a runner run is readable by History.
    from webui.history import list_runs
    make_run(tmp_path, "AAPL", "2026-11-06")
    _drain(start_run(_req(), graph_factory=FakeGraph(tmp_path)))
    assert {r.ticker for r in list_runs(tmp_path)[0]} == {"AAPL"}
