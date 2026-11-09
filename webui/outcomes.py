"""How past decisions did: the live memory log, read and scored.

Every run records its decision in the memory log as pending; once its holding
window has traded it is settled with the realized return, alpha against the
regional benchmark, and a reflection. This module reads that log for the
Outcomes page and the History column, and starts a settlement pass on demand.
Scores come from the engine's own ``tradingagents.backtest.summarize``.
"""

import threading
import traceback
from dataclasses import dataclass
from pathlib import Path

from tradingagents.agents.rating import RATING_REVIEW
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.memory import TradingMemoryLog
from webui.events import RunEvent, RunHandle, set_active_run

PENDING, SETTLED, UNSCORED = "Pending", "Settled", "Unscored"


@dataclass(frozen=True)
class Outcome:
    date: str
    ticker: str
    rating: str
    status: str                 # Pending / Settled / Unscored
    raw: str                    # "+2.3%", or "" while pending
    alpha: str
    holding: str                # "5d"
    resolved: str
    decision: str
    reflection: str


def log_path() -> Path:
    """Read at call time so a changed memory_log_path (or a test's) is honored."""
    return Path(DEFAULT_CONFIG["memory_log_path"]).expanduser()


def _status(entry: dict) -> str:
    if entry["rating"] == RATING_REVIEW:
        return UNSCORED
    return PENDING if entry["pending"] else SETTLED


def load_outcomes(path: Path | None = None) -> list[Outcome]:
    """Every decision in the log, newest analysis date first. No log → []."""
    path = Path(path or log_path())
    if not path.is_file():
        return []
    entries = TradingMemoryLog({"memory_log_path": str(path)}).load_entries()
    rows = [Outcome(date=e["date"], ticker=e["ticker"], rating=e["rating"], status=_status(e),
                    raw=e.get("raw") or "", alpha=e.get("alpha") or "", holding=e.get("holding") or "",
                    resolved=e.get("resolved") or "", decision=e.get("decision") or "",
                    reflection=e.get("reflection") or "")
            for e in entries]
    return sorted(rows, key=lambda o: (o.date, o.ticker), reverse=True)


def scores(path: Path | None = None):
    """The engine's per-rating summary of the log, or None when there is no log."""
    from tradingagents.backtest import summarize

    path = Path(path or log_path())
    if not path.is_file():
        return None
    return summarize(path)


def outcome_index(path: Path | None = None) -> dict[tuple[str, str], str]:
    """(ticker, analysis date) → what History shows: the alpha, or 'pending'."""
    index = {}
    for o in load_outcomes(path):
        if o.status == SETTLED:
            index[(o.ticker.upper(), o.date)] = f"α {o.alpha}" if o.alpha else "settled"
        elif o.status == PENDING:
            index[(o.ticker.upper(), o.date)] = "pending"
    return index


def due_count(path: Path | None = None) -> int:
    return sum(1 for o in load_outcomes(path) if o.status == PENDING)


def start_settle(req, graph_factory=None) -> RunHandle:
    """Settle every due decision on a background thread, with ``req``'s model
    writing the reflections. ``req`` is a ``runner.RunRequest``; only its
    provider and model fields are used."""
    from webui.runner import build_config

    if graph_factory is None:
        from tradingagents.graph.trading_graph import TradingAgentsGraph as graph_factory
    handle = RunHandle("past decisions", kind="settle", request=req)
    set_active_run(handle)

    def run():
        try:
            graph = graph_factory(selected_analysts=["market"], config=build_config(req))
            result = graph.settle_all_pending()
            for ticker, date in result.settled:
                handle.emit(RunEvent("report", stage="settled", title=f"{ticker} {date}"))
            for ticker, date, reason in result.failed:
                handle.emit(RunEvent("report", stage="failed", title=f"{ticker} {date}", content=reason))
            n, f = len(result.settled), len(result.failed)
            summary = f"Settled {n} decision{'s' if n != 1 else ''}."
            if f:
                summary += f" {f} could not be settled and stay pending."
            if not n and not f:
                summary = "Nothing was due: no pending decision's holding window has traded yet."
            handle.emit(RunEvent("done", content=summary))
        except Exception as exc:
            handle.emit(RunEvent("error", content=f"Settling stopped: {exc}",
                                 detail=traceback.format_exc()))

    threading.Thread(target=run, daemon=True).start()
    return handle
