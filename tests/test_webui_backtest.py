"""Backtest from the UI: grid checks and cap, progress events, past sweeps."""

import time
from pathlib import Path

import pytest

from tradingagents.backtest import BacktestResult
from tradingagents.memory import TradingMemoryLog
from webui import backtest_runner as br
from webui.events import set_active_run


def _req(**kw):
    base = {"tickers": ["aapl", " msft ", "AAPL", ""], "start": "2026-01-05", "end": "2026-01-26",
            "every": 7, "analysts": ["market"], "provider": "ollama", "quick_model": "qwen3:4b",
            "deep_model": "qwen3:4b", "ollama_url": "http://localhost:11434/v1"}
    return br.BacktestRequest(**{**base, **kw})


@pytest.fixture(autouse=True)
def _clear():
    yield
    set_active_run(None)


@pytest.mark.unit
def test_tickers_cleaned_and_deduped():
    assert _req().tickers == ["AAPL", "MSFT"]
    assert br.parse_tickers("nvda, aapl;; tsla") == ["NVDA", "AAPL", "TSLA"]


@pytest.mark.unit
def test_plan_counts_cells():
    dates, cells, problem = br.plan_cells(_req())
    assert dates == ["2026-01-05", "2026-01-12", "2026-01-19", "2026-01-26"]
    assert (cells, problem) == (8, None)


@pytest.mark.unit
@pytest.mark.parametrize("kw, needle", [
    ({"tickers": []}, "ticker"),
    ({"analysts": []}, "analyst"),
    ({"end": "2025-12-01"}, "ends before it starts"),
    ({"start": "2026-1-5"}, "YYYY-MM-DD"),
    ({"every": 0}, "at least 1"),
    ({"start": "2025-01-01", "end": "2026-01-01", "every": 1}, "limit of 60"),
])
def test_plan_rejects(kw, needle):
    assert needle in br.plan_cells(_req(**kw))[2]


def _drain(h, timeout=5):
    deadline = time.monotonic() + timeout
    while not h.finished and time.monotonic() < deadline:
        time.sleep(0.01)
    return h.events_since(0)


@pytest.mark.unit
def test_sweep_emits_progress_failures_and_summary(tmp_path):
    seen = {}

    def fake(tickers, dates, config, portfolio=None, selected_analysts=(), run_id=None, progress=None):
        seen.update(tickers=tickers, dates=dates, config=config, portfolio=portfolio,
                    analysts=selected_analysts, run_id=run_id)
        log = tmp_path / "trading_memory.md"
        TradingMemoryLog({"memory_log_path": str(log)}).store_decision("AAPL", dates[0], "**Rating**: Buy")
        for i, (t, d) in enumerate([(t, d) for t in tickers for d in dates], 1):
            progress(i, len(tickers) * len(dates), t, d)
        return BacktestResult(run_id="20261109_120000", log_path=log, cells_run=7, skipped=0,
                              failures=[("MSFT", dates[1], "vendor down")])

    h = br.start_backtest(_req(analysts=["market", "sentiment"], run_id="old"), backtest=fake)
    evs = _drain(h)
    assert h.kind == "backtest"
    assert seen["analysts"] == ["market", "social"] and seen["run_id"] == "old"
    assert seen["config"]["llm_provider"] == "ollama" and seen["config"]["checkpoint_enabled"] is False
    progress = [e for e in evs if e.kind == "progress"]
    assert len(progress) == 8 and progress[0].total == 8 and progress[-1].content == "MSFT 2026-01-26"
    assert any(e.stage == "failed" and "vendor down" in e.content for e in evs)
    done = evs[-1]
    assert done.kind == "done" and done.title == "20261109_120000" and "Ran 7 of 8 runs" in done.content


@pytest.mark.unit
def test_sweep_error_is_event():
    def boom(*a, **k):
        raise RuntimeError("no key")
    evs = _drain(br.start_backtest(_req(), backtest=boom))
    assert evs[-1].kind == "error" and "no key" in evs[-1].content


@pytest.mark.unit
def test_past_sweeps(tmp_path):
    assert br.past_sweeps(tmp_path / "none") == []
    for run_id, ticker in (("20261101_100000", "AAPL"), ("20261105_100000", "NVDA")):
        log = TradingMemoryLog({"memory_log_path": str(tmp_path / run_id / "trading_memory.md")})
        log.store_decision(ticker, "2026-10-01", "**Rating**: Buy")
        log.update_with_outcome(ticker, "2026-10-01", 0.04, 0.01, 5, "ok", resolution_date="2026-10-08")
    (tmp_path / "empty").mkdir()
    sweeps = br.past_sweeps(tmp_path)
    assert [s.run_id for s in sweeps] == ["20261105_100000", "20261101_100000"]
    assert sweeps[0].tickers == ["NVDA"] and sweeps[0].summary.resolved == 1
    assert isinstance(sweeps[0].path, Path)
