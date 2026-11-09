"""Outcomes: the live memory log read back, scored, and settled on demand."""

import time
from types import SimpleNamespace

import pytest

from tradingagents.memory import TradingMemoryLog
from webui import outcomes
from webui.events import set_active_run
from webui.runner import RunRequest


def make_log(path):
    log = TradingMemoryLog({"memory_log_path": str(path)})
    log.store_decision("AAPL", "2026-10-01", "**Rating**: Buy\n\nup")
    log.store_decision("MSFT", "2026-10-02", "**Rating**: Sell\n\ndown")
    log.store_decision("NVDA", "2026-11-05", "**Rating**: Hold\n\nwait")
    log.update_with_outcome("AAPL", "2026-10-01", 0.05, 0.02, 5, "Right call.", resolution_date="2026-10-08")
    log.update_with_outcome("MSFT", "2026-10-02", 0.01, 0.03, 5, "Wrong call.", resolution_date="2026-10-09")
    return path


@pytest.fixture(autouse=True)
def _clear():
    yield
    set_active_run(None)


@pytest.mark.unit
def test_missing_log_is_empty(tmp_path):
    assert outcomes.load_outcomes(tmp_path / "none.md") == []
    assert outcomes.scores(tmp_path / "none.md") is None
    assert outcomes.outcome_index(tmp_path / "none.md") == {}


@pytest.mark.unit
def test_rows_newest_first_with_status(tmp_path):
    rows = outcomes.load_outcomes(make_log(tmp_path / "m.md"))
    assert [(r.ticker, r.status) for r in rows] == [("NVDA", "Pending"), ("MSFT", "Settled"),
                                                     ("AAPL", "Settled")]
    aapl = rows[2]
    assert (aapl.raw, aapl.alpha, aapl.holding, aapl.resolved) == ("+5.0%", "+2.0%", "5d", "2026-10-08")
    assert aapl.reflection == "Right call."


@pytest.mark.unit
def test_scores_use_engine_summary(tmp_path):
    s = outcomes.scores(make_log(tmp_path / "m.md"))
    assert (s.resolved, s.pending) == (2, 1)
    assert s.by_rating["Buy"].hit_rate == 1.0 and s.by_rating["Sell"].hit_rate == 0.0


@pytest.mark.unit
def test_index_for_history(tmp_path):
    idx = outcomes.outcome_index(make_log(tmp_path / "m.md"))
    assert idx[("AAPL", "2026-10-01")] == "α +2.0%" and idx[("NVDA", "2026-11-05")] == "pending"
    assert outcomes.due_count(tmp_path / "m.md") == 1


def _req():
    return RunRequest("", "", ["market"], "ollama", "qwen3:4b", "qwen3:4b",
                      "http://localhost:11434/v1", 1, 1)


def _drain(h, timeout=5):
    deadline = time.monotonic() + timeout
    while not h.finished and time.monotonic() < deadline:
        time.sleep(0.01)
    return h.events_since(0)


class FakeGraph:
    def __init__(self, result=None, fail=False):
        self.result, self.fail = result, fail

    def __call__(self, selected_analysts, config):
        self.config = config
        return self

    def settle_all_pending(self):
        if self.fail:
            raise RuntimeError("no prices")
        return self.result


@pytest.mark.unit
def test_settle_reports_settled_and_failed():
    fake = FakeGraph(SimpleNamespace(settled=[("AAPL", "2026-10-01")],
                                     failed=[("MSFT", "2026-10-02", "prices unavailable")]))
    h = outcomes.start_settle(_req(), graph_factory=fake)
    evs = _drain(h)
    assert h.kind == "settle" and fake.config["llm_provider"] == "ollama"
    assert evs[-1].kind == "done" and "Settled 1 decision." in evs[-1].content
    assert "1 could not be settled" in evs[-1].content


@pytest.mark.unit
def test_settle_nothing_due():
    evs = _drain(outcomes.start_settle(_req(), graph_factory=FakeGraph(SimpleNamespace(settled=[], failed=[]))))
    assert "Nothing was due" in evs[-1].content


@pytest.mark.unit
def test_settle_error_is_event():
    evs = _drain(outcomes.start_settle(_req(), graph_factory=FakeGraph(fail=True)))
    assert evs[-1].kind == "error" and evs[-1].content.startswith("Settling stopped:")
