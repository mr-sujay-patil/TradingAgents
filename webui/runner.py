"""A live run: the engine's own stream, on a background thread, as RunEvents.

The provider is always set from the UI's choice, never left to auto-detection,
so an OpenAI key sitting in ``.env`` is only used when OpenAI is picked. Common
setup failures (Ollama down, model not pulled, no key) are caught by
``preflight`` before a thread starts, rather than minutes into a run.
"""

import os
import threading
import traceback
from dataclasses import dataclass

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
        checkpoint_enabled=False,
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


def preflight(req: RunRequest, get=requests.get) -> str | None:
    """A plain-language reason the run can't start, or None."""
    if req.provider == "ollama":
        try:
            resp = get(f"{req.ollama_url.rstrip('/')}/models", timeout=3)
            resp.raise_for_status()
            installed = {m.get("id") for m in resp.json().get("data", [])}
        except (requests.ConnectionError, requests.Timeout):
            return "Ollama isn't running. Start it with `ollama serve`."
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


def start_run(req: RunRequest, graph_factory=None) -> RunHandle:
    if graph_factory is None:
        from tradingagents.graph.trading_graph import TradingAgentsGraph as graph_factory
    handle = RunHandle(f"{req.ticker} {req.trade_date}")
    set_active_run(handle)

    def run():
        try:
            graph = graph_factory(selected_analysts=graph_analysts(req.analysts),
                                  config=build_config(req))
            for name in req.analysts:
                handle.emit(RunEvent("stage", stage=name, status="running"))
            state = graph.create_run_state(req.ticker, req.trade_date)
            args = graph.propagator.get_graph_args()
            final_state, seen = {}, {}
            for _messages, chunk in graph.stream_run(state, **args):
                if chunk is None:
                    continue
                # Chunks are per-node deltas; merge as cli/run.py does.
                final_state.update(chunk)
                for event in state_to_events(final_state, seen):
                    handle.emit(event)
            graph.record_decision(req.ticker, req.trade_date, final_state)
            path = graph.default_report_path(req.ticker)
            graph.save_reports(final_state, req.ticker, path, html=True)
            handle.emit(RunEvent("done", rating=run_rating(final_state), report_dir=str(path)))
        except Exception as exc:
            handle.emit(RunEvent("error", content=f"The run stopped: {exc}",
                                 detail=traceback.format_exc()))

    threading.Thread(target=run, daemon=True).start()
    return handle
