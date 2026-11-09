"""A live run: the engine's own stream, on a background thread, as RunEvents.

The provider is always set from the UI's choice, never left to auto-detection,
so an OpenAI key sitting in ``.env`` is only used when OpenAI is picked. Common
setup failures (Ollama down, model not pulled, no key) are caught by
``preflight`` before a thread starts, rather than minutes into a run.
"""

import contextlib
import os
import threading
import traceback
from dataclasses import dataclass
from typing import Any

import requests

from tradingagents.agents.rating import run_rating
from tradingagents.default_config import DEFAULT_CONFIG
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

    def __post_init__(self):
        self.ticker = self.ticker.strip().upper()


def build_config(req: RunRequest) -> dict:
    config = DEFAULT_CONFIG.copy()
    config.update(
        llm_provider=req.provider,
        backend_url=req.ollama_url if req.provider == "ollama" else OPENAI_URL,
        quick_think_llm=req.quick_model,
        deep_think_llm=req.deep_model,
        max_debate_rounds=req.debate_rounds,
        max_risk_discuss_rounds=req.risk_rounds,
        output_language="English",
        checkpoint_enabled=req.checkpoint,
        # A per-tier override from .env would route that tier elsewhere,
        # possibly to a paid provider the user didn't pick here.
        quick_think_provider=None,
        deep_think_provider=None,
        quick_think_backend_url=None,
        deep_think_backend_url=None,
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
    if req.provider == "ollama":
        try:
            installed = set(ollama_models(req.ollama_url, get=get))
        except (requests.ConnectionError, requests.Timeout):
            return OLLAMA_DOWN
        for model in (req.quick_model, req.deep_model):
            if model not in installed:
                return f"Model `{model}` isn't installed. Run `ollama pull {model}`."
    elif req.provider == "openai" and not os.environ.get("OPENAI_API_KEY"):
        return "No OpenAI key in `.env`."
    return None


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
            state = graph.create_run_state(req.ticker, req.trade_date, portfolio=req.portfolio)
            args = graph.propagator.get_graph_args()
            # As cli/run.py: a checkpointer when enabled, its thread id in the
            # stream config, and None as input when a saved run resumes.
            tid = graph.begin_checkpoint(req.ticker, req.trade_date, portfolio=req.portfolio)
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
            graph.clear_checkpoint_on_success(req.ticker, req.trade_date, portfolio=req.portfolio)
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
