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
    asset_type,
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

    resuming = False
    calls: list

    def create_run_state(self, ticker, date, asset_type="stock", portfolio=None):
        self.portfolio, self.asset_type = portfolio, asset_type
        return {"init": True}

    def begin_checkpoint(self, ticker, date, asset_type="stock", portfolio=None):
        self.calls = ["begin"]
        self.checkpoint_asset_type = asset_type
        if not self.config["checkpoint_enabled"]:
            return None
        self._resuming = self.resuming
        return "tid-1"

    def checkpoint_input(self, state):
        return None if getattr(self, "_resuming", False) else state

    def clear_checkpoint_on_success(self, *a, **k):
        self.calls.append("clear")

    def end_checkpoint(self):
        self.calls.append("end")

    def stream_run(self, state, **args):
        self.stream_input, self.stream_args = state, args
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
    assert preflight(_req(provider="openai")) == "No OpenAI key in `.env` (`OPENAI_API_KEY`)."
    monkeypatch.setenv("OPENAI_API_KEY", "placeholder")
    assert preflight(_req(provider="openai")) is None


@pytest.mark.unit
def test_saved_run_is_listed_in_history(tmp_path):
    # The saved report from a runner run is readable by History.
    from webui.history import list_runs
    make_run(tmp_path, "AAPL", "2026-11-06")
    _drain(start_run(_req(), graph_factory=FakeGraph(tmp_path)))
    assert {r.ticker for r in list_runs(tmp_path)[0]} == {"AAPL"}


@pytest.mark.unit
def test_ollama_models_lists_ids():
    from webui.runner import ollama_models
    assert ollama_models("http://x/v1", get=_models("a", "b")) == ["a", "b"]


@pytest.mark.unit
def test_no_portfolio_reaches_graph_as_none(tmp_path):
    fake = FakeGraph(tmp_path)
    _drain(start_run(_req(), graph_factory=fake))
    assert fake.portfolio is None


@pytest.mark.unit
def test_portfolio_reaches_graph(tmp_path):
    from tradingagents.portfolio import PortfolioContext
    book = PortfolioContext(cash=10, positions=[{"ticker": "AAPL", "quantity": 3}])
    fake = FakeGraph(tmp_path)
    h = start_run(_req(portfolio=book), graph_factory=fake)
    _drain(h)
    assert fake.portfolio is book and h.request.portfolio is book


@pytest.mark.unit
def test_checkpoint_flag_sets_config_and_thread(tmp_path):
    fake = FakeGraph(tmp_path)
    evs = _drain(start_run(_req(checkpoint=True), graph_factory=fake))
    assert fake.config["checkpoint_enabled"] is True
    assert fake.stream_args["config"]["configurable"]["thread_id"] == "tid-1"
    assert fake.stream_input == {"init": True}
    assert fake.calls == ["begin", "clear", "end"] and evs[-1].kind == "done"


@pytest.mark.unit
def test_checkpoint_off_by_default(tmp_path):
    fake = FakeGraph(tmp_path)
    _drain(start_run(_req(), graph_factory=fake))
    assert fake.config["checkpoint_enabled"] is False and "config" not in fake.stream_args


@pytest.mark.unit
def test_failure_keeps_checkpoint_and_tears_down(tmp_path):
    fake = FakeGraph(tmp_path, fail=True)
    evs = _drain(start_run(_req(checkpoint=True), graph_factory=fake))
    assert evs[-1].kind == "error" and fake.calls == ["begin", "end"]


@pytest.mark.unit
def test_resume_announced_and_streams_none(tmp_path):
    from webui.runner import RESUMING
    fake = FakeGraph(tmp_path)
    fake.resuming = True
    evs = _drain(start_run(_req(checkpoint=True), graph_factory=fake))
    assert any(e.status == "resuming" and e.content == RESUMING for e in evs)
    assert fake.stream_input is None


@pytest.mark.unit
@pytest.mark.parametrize("ticker", ["BTC-USD", "eth-usdt", "BTCUSD", "AAPL", "0700.HK", "SPY", "XAUUSD"])
def test_asset_type_matches_cli(ticker):
    """The UI classifies a ticker exactly as the CLI does."""
    from cli.prompts import detect_asset_type
    assert asset_type(ticker) == detect_asset_type(ticker).value


@pytest.mark.unit
def test_crypto_ticker_is_canonical_and_drops_fundamentals():
    req = _req(ticker="btcusd", analysts=["market", "news", "fundamentals"])
    assert req.ticker == "BTC-USD" and req.asset_type == "crypto"
    assert req.analysts == ["market", "news"]
    stock = _req(ticker="aapl", analysts=["market", "fundamentals"])
    assert stock.asset_type == "stock" and stock.analysts == ["market", "fundamentals"]


@pytest.mark.unit
def test_crypto_run_reaches_graph_as_crypto(tmp_path):
    graph = FakeGraph(tmp_path)
    _drain(start_run(_req(ticker="ETH-USD", analysts=["market", "fundamentals"], checkpoint=True),
                     graph_factory=graph))
    assert graph.asset_type == "crypto" and graph.checkpoint_asset_type == "crypto"
    assert graph.selected == ["market"]


@pytest.mark.unit
def test_stock_run_reaches_graph_as_stock(tmp_path):
    graph = FakeGraph(tmp_path)
    _drain(start_run(_req(), graph_factory=graph))
    assert graph.asset_type == "stock"


@pytest.mark.unit
@pytest.mark.parametrize("provider, kw, url", [
    ("ollama", {}, "http://localhost:11434/v1"),
    ("openai", {}, "https://api.openai.com/v1"),
    ("anthropic", {}, None),                   # each client's own endpoint
    ("deepseek", {}, None),
    ("openai_compatible", {"backend_url": " http://localhost:8000/v1 "}, "http://localhost:8000/v1"),
])
def test_endpoint_per_provider(provider, kw, url):
    assert build_config(_req(provider=provider, **kw))["backend_url"] == url


@pytest.mark.unit
def test_preflight_names_a_missing_provider_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert "GOOGLE_API_KEY" in preflight(_req(provider="google"))
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    assert preflight(_req(provider="google")) is None


@pytest.mark.unit
def test_preflight_needs_both_models():
    assert "model" in preflight(_req(provider="anthropic", deep_model=" "))


@pytest.mark.unit
def test_preflight_openai_compatible_needs_url():
    assert "URL" in preflight(_req(provider="openai_compatible"))


@pytest.mark.unit
def test_advanced_settings_reach_the_config():
    cfg = build_config(_req(provider="openai", output_language="Hindi", openai_reasoning_effort="high",
                            anthropic_effort="", temperature=0.3,
                            data_vendors={"news_data": "alpha_vantage,yfinance"}))
    assert cfg["output_language"] == "Hindi" and cfg["openai_reasoning_effort"] == "high"
    assert cfg["anthropic_effort"] is None and cfg["temperature"] == 0.3
    assert cfg["data_vendors"]["news_data"] == "alpha_vantage,yfinance"
    assert cfg["data_vendors"]["core_stock_apis"] == DEFAULT_CONFIG["data_vendors"]["core_stock_apis"]
    assert DEFAULT_CONFIG["data_vendors"]["news_data"] == "yfinance"     # the shared default untouched


@pytest.mark.unit
def test_defaults_leave_the_engine_alone():
    cfg = build_config(_req())
    assert cfg["temperature"] is None and cfg["google_thinking_level"] is None
    assert cfg["output_language"] == "English" and cfg["deep_think_provider"] is None


@pytest.mark.unit
def test_deep_tier_on_its_own_provider():
    req = _req(provider="ollama", deep_provider="anthropic", deep_model="claude-opus-5-5")
    cfg = build_config(req)
    assert (cfg["llm_provider"], cfg["deep_think_provider"]) == ("ollama", "anthropic")
    assert cfg["backend_url"] == "http://localhost:11434/v1" and cfg["deep_think_backend_url"] is None
    assert req.split_tiers and req.paid
    # The same provider named twice is no split at all.
    assert build_config(_req(deep_provider="ollama"))["deep_think_provider"] is None


@pytest.mark.unit
def test_deep_tier_on_an_openai_compatible_server():
    cfg = build_config(_req(provider="anthropic", deep_provider="openai_compatible",
                            deep_backend_url="http://localhost:8000/v1"))
    assert cfg["deep_think_backend_url"] == "http://localhost:8000/v1"


@pytest.mark.unit
def test_preflight_checks_each_tier(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def get(url, timeout):
        return SimpleNamespace(raise_for_status=lambda: None,
                               json=lambda: {"data": [{"id": "qwen3:4b"}]})

    req = _req(provider="ollama", quick_model="qwen3:4b", deep_provider="anthropic", deep_model="claude-x")
    assert "ANTHROPIC_API_KEY" in preflight(req, get=get)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert preflight(req, get=get) is None          # the Claude model is not looked for in Ollama
