"""A live run: the engine's own stream, on a background thread, as RunEvents.

The provider is always set from the UI's choice, never left to auto-detection,
so a key sitting in ``.env`` is only used when its provider is picked. Common
setup failures (Ollama down, model not pulled, no key, no endpoint) are caught
by ``preflight`` before a thread starts, rather than minutes into a run.
"""

import contextlib
import threading
import traceback
from dataclasses import dataclass, field
from typing import Any

import requests

from tradingagents.agents.rating import run_rating
from tradingagents.dataflows.symbols import normalize_symbol
from tradingagents.default_config import DEFAULT_CONFIG
from webui import providers
from webui.events import RunEvent, RunHandle, set_active_run
from webui.stages import STAGE_BY_KEY

OPENAI_URL = "https://api.openai.com/v1"

# Where each stage's text sits in the graph state (as cli/run.py reads it).
_STATE_PATHS = {
    "market": ("market_report",),
    "sentiment": ("sentiment_report",),
    "news": ("news_report",),
    "fundamentals": ("fundamentals_report",),
    "bull": ("investment_debate_state", "bull_history"),
    "bear": ("investment_debate_state", "bear_history"),
    "manager": ("investment_plan",),
    "trader": ("trader_investment_plan",),
    "aggressive": ("risk_debate_state", "aggressive_history"),
    "conservative": ("risk_debate_state", "conservative_history"),
    "neutral": ("risk_debate_state", "neutral_history"),
    "portfolio": ("final_trade_decision",),
}


# As cli/prompts.CRYPTO_SUFFIXES; tests/test_webui_runner.py keeps the two in step.
CRYPTO_SUFFIXES = ("-USD", "-USDT", "-USDC", "-BTC", "-ETH")


def asset_type(ticker: str) -> str:
    """"crypto" or "stock", classified on the canonical symbol as the CLI does."""
    return "crypto" if normalize_symbol(ticker).endswith(CRYPTO_SUFFIXES) else "stock"


def analysts_for(names: list[str], kind: str) -> list[str]:
    """A coin has no company filings, so the Fundamentals analyst sits out (as in the CLI)."""
    return [n for n in names if not (kind == "crypto" and n == "fundamentals")]


@dataclass
class RunRequest:
    ticker: str
    trade_date: str
    analysts: list[str]
    provider: str
    quick_model: str
    deep_model: str
    ollama_url: str
    debate_rounds: int
    risk_rounds: int
    # None is "no context", never a flat book (tradingagents.portfolio).
    portfolio: Any = None           # PortfolioContext | None
    checkpoint: bool = False        # save each step so a stopped run can resume
    backend_url: str = ""           # the endpoint, for an OpenAI-compatible server
    # Advanced (webui.prefs.RUN_SETTINGS); "" or None is the engine's default.
    deep_provider: str = ""         # the deep tier on a provider of its own; "" is the same one
    deep_backend_url: str = ""      # its endpoint, for Ollama or an OpenAI-compatible server
    output_language: str = "English"
    openai_reasoning_effort: str = ""
    anthropic_effort: str = ""
    google_thinking_level: str = ""
    temperature: float | None = None
    data_vendors: dict = field(default_factory=dict)   # category -> "vendor,vendor"

    def __post_init__(self):
        # The canonical symbol the data path prices (BTCUSD -> BTC-USD), as the CLI passes.
        self.ticker = normalize_symbol(self.ticker.strip()) if self.ticker.strip() else ""
        self.analysts = analysts_for(self.analysts, self.asset_type)

    @property
    def asset_type(self) -> str:
        return asset_type(self.ticker) if self.ticker else "stock"

    @property
    def split_tiers(self) -> bool:
        """Whether the deep tier runs on a provider of its own."""
        return bool(self.deep_provider) and self.deep_provider != self.provider

    @property
    def paid(self) -> bool:
        return providers.is_paid(self.provider) or (self.split_tiers and providers.is_paid(self.deep_provider))


def endpoint(provider: str, url: str = "") -> str | None:
    """The backend URL for ``provider``; None lets its client use its own.

    ``url`` is the one the user gave, for Ollama or an OpenAI-compatible server.
    """
    if provider == "openai":
        return OPENAI_URL
    if provider in ("ollama", "openai_compatible"):
        return url.strip() or None
    return None


def _main_url(req: RunRequest) -> str:
    return req.ollama_url if req.provider == "ollama" else req.backend_url


def _deep_url(req: RunRequest) -> str:
    return req.deep_backend_url or (req.ollama_url if req.deep_provider == "ollama" else "")


def build_config(req: RunRequest) -> dict:
    config = DEFAULT_CONFIG.copy()
    config.update(
        llm_provider=req.provider,
        backend_url=endpoint(req.provider, _main_url(req)),
        quick_think_llm=req.quick_model,
        deep_think_llm=req.deep_model,
        max_debate_rounds=req.debate_rounds,
        max_risk_discuss_rounds=req.risk_rounds,
        output_language=req.output_language.strip() or "English",
        checkpoint_enabled=req.checkpoint,
        # Only the tier split picked here: one from .env would route a tier
        # elsewhere, possibly to a paid provider the user didn't pick.
        quick_think_provider=None,
        deep_think_provider=req.deep_provider if req.split_tiers else None,
        quick_think_backend_url=None,
        deep_think_backend_url=endpoint(req.deep_provider, _deep_url(req)) if req.split_tiers else None,
        openai_reasoning_effort=req.openai_reasoning_effort or None,
        anthropic_effort=req.anthropic_effort or None,
        google_thinking_level=req.google_thinking_level or None,
        temperature=req.temperature,
        # A copy: the shared default dict must not change under a run.
        data_vendors={**DEFAULT_CONFIG["data_vendors"], **req.data_vendors},
    )
    return config


def graph_analysts(names: list[str]) -> list[str]:
    return ["social" if n == "sentiment" else n for n in names]


OLLAMA_DOWN = "Ollama isn't running. Start it with `ollama serve`."


def ollama_models(url: str, get=requests.get) -> list[str]:
    """The models pulled into the Ollama at ``url``; raises requests errors if it is down."""
    resp = get(f"{url.rstrip('/')}/models", timeout=3)
    resp.raise_for_status()
    return [m.get("id") for m in resp.json().get("data", [])]


def preflight(req: RunRequest, get=requests.get) -> str | None:
    """A plain-language reason the run can't start, or None."""
    if not req.quick_model.strip() or not req.deep_model.strip():
        return "Pick a quick-thinking and a deep-thinking model."
    tiers = ([(req.provider, _main_url(req), [req.quick_model]), (req.deep_provider, _deep_url(req), [req.deep_model])]
             if req.split_tiers else [(req.provider, _main_url(req), [req.quick_model, req.deep_model])])
    for provider, url, models in tiers:
        problem = _tier_problem(provider, url, models, get)
        if problem:
            return problem
    return None


def _tier_problem(provider: str, url: str, models: list[str], get) -> str | None:
    if provider == "ollama":
        try:
            installed = set(ollama_models(url, get=get))
        except (requests.ConnectionError, requests.Timeout):
            return OLLAMA_DOWN
        for model in models:
            if model not in installed:
                return f"Model `{model}` isn't installed. Run `ollama pull {model}`."
        return None
    return providers.missing_setup(provider, url)


def state_to_events(state: dict, seen: dict[str, str]) -> list[RunEvent]:
    """A report event for each stage whose text is new or changed since ``seen``."""
    events = []
    for key, path in _STATE_PATHS.items():
        value = state
        for part in path:
            value = value.get(part) if isinstance(value, dict) else None
        text = (value or "").strip() if isinstance(value, str) else ""
        if text and seen.get(key) != text:
            seen[key] = text
            events.append(RunEvent("report", stage=key, title=STAGE_BY_KEY[key].title, content=text))
    return events


RESUMING = "Resuming from the last saved step."


def start_run(req: RunRequest, graph_factory=None) -> RunHandle:
    """Run ``req`` on a background thread. With ``req.checkpoint`` each step is
    saved, so running the same request again after a failure resumes it."""
    if graph_factory is None:
        from tradingagents.graph.trading_graph import TradingAgentsGraph as graph_factory
    handle = RunHandle(f"{req.ticker} {req.trade_date}", kind="analysis", request=req)
    set_active_run(handle)

    def run():
        graph = None
        try:
            graph = graph_factory(selected_analysts=graph_analysts(req.analysts),
                                  config=build_config(req))
            state = graph.create_run_state(req.ticker, req.trade_date, req.asset_type,
                                           portfolio=req.portfolio)
            args = graph.propagator.get_graph_args()
            # As cli/run.py: a checkpointer when enabled, its thread id in the
            # stream config, and None as input when a saved run resumes.
            tid = graph.begin_checkpoint(req.ticker, req.trade_date, req.asset_type,
                                         portfolio=req.portfolio)
            if tid is not None:
                args.setdefault("config", {}).setdefault("configurable", {})["thread_id"] = tid
                if getattr(graph, "_resuming", False):
                    handle.emit(RunEvent("stage", stage="resume", status="resuming", content=RESUMING))
            for name in req.analysts:
                handle.emit(RunEvent("stage", stage=name, status="running"))
            final_state, seen = {}, {}
            for _messages, chunk in graph.stream_run(graph.checkpoint_input(state), **args):
                if chunk is None:
                    continue
                # Chunks are per-node deltas; merge as cli/run.py does.
                final_state.update(chunk)
                for event in state_to_events(final_state, seen):
                    handle.emit(event)
            graph.record_decision(req.ticker, req.trade_date, final_state)
            graph.clear_checkpoint_on_success(req.ticker, req.trade_date, req.asset_type,
                                              portfolio=req.portfolio)
            path = graph.default_report_path(req.ticker)
            graph.save_reports(final_state, req.ticker, path, html=True)
            handle.emit(RunEvent("done", rating=run_rating(final_state), report_dir=str(path)))
        except Exception as exc:
            handle.emit(RunEvent("error", content=f"The run stopped: {exc}",
                                 detail=traceback.format_exc()))
        finally:
            if graph is not None and hasattr(graph, "end_checkpoint"):
                # Tearing down must never mask the run's own outcome.
                with contextlib.suppress(Exception):
                    graph.end_checkpoint()

    threading.Thread(target=run, daemon=True).start()
    return handle
