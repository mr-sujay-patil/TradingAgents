"""A backtest sweep from the UI: the engine's ``run_backtest`` on a background thread.

Each (ticker, date) cell is a full analysis, so the UI caps a sweep at
``MAX_CELLS`` (the CLI has no cap) to keep a typo from queueing hundreds of
runs. A sweep writes its own memory log under ``<results_dir>/backtest/<id>``
and leaves the live log alone; continuing a sweep by its id skips its finished
cells. Scores come from the engine's ``summarize``.
"""

import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tradingagents.dataflows.symbols import normalize_symbol
from tradingagents.default_config import DEFAULT_CONFIG
from webui.events import RunEvent, RunHandle, set_active_run
from webui.runner import RunRequest, analysts_for, asset_type, build_config, graph_analysts

MAX_CELLS = 60


@dataclass
class BacktestRequest:
    tickers: list[str]
    start: str
    end: str
    every: int
    analysts: list[str]
    provider: str
    quick_model: str
    deep_model: str
    ollama_url: str
    debate_rounds: int = 1
    risk_rounds: int = 1
    portfolio: Any = None
    run_id: str | None = None
    backend_url: str = ""
    settings: dict = field(default_factory=dict)   # webui.prefs.run_settings

    def __post_init__(self):
        cleaned = (normalize_symbol(t.strip()) for t in self.tickers if t.strip())
        self.tickers = list(dict.fromkeys(cleaned))

    @property
    def asset_types(self) -> set[str]:
        return {asset_type(t) for t in self.tickers}

    @property
    def asset_type(self) -> str:
        """The sweep's one asset type; ``plan_cells`` refuses a mix."""
        return "crypto" if self.asset_types == {"crypto"} else "stock"

    @property
    def run_analysts(self) -> list[str]:
        return analysts_for(self.analysts, self.asset_type)

    def run_request(self) -> RunRequest:
        """The single-run settings each cell uses, for config and preflight."""
        return RunRequest(ticker=self.tickers[0] if self.tickers else "", trade_date=self.start,
                          analysts=self.analysts, provider=self.provider, quick_model=self.quick_model,
                          deep_model=self.deep_model, ollama_url=self.ollama_url,
                          debate_rounds=self.debate_rounds, risk_rounds=self.risk_rounds,
                          backend_url=self.backend_url, **self.settings)


def parse_tickers(text: str) -> list[str]:
    return [t for t in (part.strip().upper() for part in text.replace(";", ",").split(",")) if t]


def plan_cells(req: BacktestRequest) -> tuple[list[str], int, str | None]:
    """(analysis dates, cell count, a reason the sweep can't run or None)."""
    from tradingagents.backtest import iter_grid

    if not req.tickers:
        return [], 0, "Enter at least one ticker."
    if not req.analysts:
        return [], 0, "Pick at least one analyst."
    if len(req.asset_types) > 1:
        # The engine runs a sweep under one asset type.
        return [], 0, "Crypto and stock tickers can't share a sweep; run them separately."
    if not req.run_analysts:
        return [], 0, "The Fundamentals analyst doesn't apply to crypto; pick another analyst."
    try:
        dates = iter_grid(req.start, req.end, req.every)
    except ValueError as exc:
        return [], 0, str(exc)
    if not dates:
        return [], 0, "No analysis dates in that range."
    cells = len(req.tickers) * len(dates)
    if cells > MAX_CELLS:
        return dates, cells, (f"{cells} runs is over the UI's limit of {MAX_CELLS}. "
                              "Widen the step, shorten the range, or use fewer tickers.")
    return dates, cells, None


def start_backtest(req: BacktestRequest, backtest=None) -> RunHandle:
    """Run the sweep on a background thread; ``progress`` events per cell, then
    ``done`` with the summary text (``content``), run id (``title``) and log path."""
    from tradingagents.backtest import run_backtest, summarize

    backtest = backtest or run_backtest
    dates, total, _problem = plan_cells(req)
    handle = RunHandle(f"{', '.join(req.tickers)} · {req.start} → {req.end}", kind="backtest", request=req)
    set_active_run(handle)

    def progress(done, total_, ticker, date):
        handle.emit(RunEvent("progress", done=done - 1, total=total_, content=f"{ticker} {date}"))

    def run():
        try:
            result = backtest(req.tickers, dates, build_config(req.run_request()),
                              asset_type=req.asset_type, portfolio=req.portfolio,
                              selected_analysts=graph_analysts(req.run_analysts),
                              run_id=req.run_id or None, progress=progress)
            for ticker, date, reason in result.failures:
                handle.emit(RunEvent("report", stage="failed", title=f"{ticker} {date}", content=reason))
            for ticker, reason in result.settlement_failures:
                handle.emit(RunEvent("report", stage="unsettled", title=ticker, content=reason))
            text = summarize(result).render()
            text += (f"\n\nRan {result.cells_run} of {total} runs"
                     + (f", skipped {result.skipped} already done" if result.skipped else "") + ".")
            handle.emit(RunEvent("done", title=result.run_id, content=text, report_dir=str(result.log_path),
                                 done=result.cells_run, total=total))
        except Exception as exc:
            handle.emit(RunEvent("error", content=f"The backtest stopped: {exc}",
                                 detail=traceback.format_exc()))

    threading.Thread(target=run, daemon=True).start()
    return handle


@dataclass
class Sweep:
    run_id: str
    path: Path
    tickers: list[str]
    cells: int
    summary: Any                      # tradingagents.backtest.BacktestSummary
    entries: list[dict] = field(default_factory=list)


def backtest_root() -> Path:
    return Path(DEFAULT_CONFIG["results_dir"]) / "backtest"


def past_sweeps(root: Path | None = None) -> list[Sweep]:
    """Every sweep with a memory log, newest first. Unreadable ones are skipped."""
    from tradingagents.backtest import summarize
    from tradingagents.memory import TradingMemoryLog

    root = Path(root or backtest_root())
    if not root.is_dir():
        return []
    sweeps = []
    for folder in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
        log = folder / "trading_memory.md"
        if not log.is_file():
            continue
        try:
            entries = TradingMemoryLog({"memory_log_path": str(log)}).load_entries()
            summary = summarize(log)
        except (OSError, ValueError):
            continue
        sweeps.append(Sweep(run_id=folder.name, path=folder, cells=len(entries), summary=summary,
                            tickers=list(dict.fromkeys(e["ticker"] for e in entries)), entries=entries))
    return sweeps
