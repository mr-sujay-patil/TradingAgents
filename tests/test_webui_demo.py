"""Demo mode replays a saved report through the same events a live run emits."""

import time

import pytest

from tests.webui_helpers import make_run
from webui.demo import SAMPLE_REPORT, start_demo
from webui.events import active_run, set_active_run
from webui.history import list_runs


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
def test_replays_sections_in_stage_order(tmp_path):
    path = make_run(tmp_path, "AAPL", "2026-11-06")
    h = start_demo(path, delay=0)
    assert active_run() is h
    evs = _drain(h)
    assert [e.stage for e in evs if e.kind == "stage"] == ["market", "news"]
    reports = [e.stage for e in evs if e.kind == "report"]
    assert reports == ["market", "news", "bull", "bear", "manager", "trader",
                       "aggressive", "conservative", "neutral", "portfolio"]
    assert evs[-1].kind == "done" and evs[-1].rating == "Hold"
    assert evs[-1].report_dir == str(path)


@pytest.mark.unit
def test_uses_newest_saved_run_by_default(tmp_path):
    make_run(tmp_path, "AAPL", "2026-11-06")
    evs = _drain(start_demo(delay=0, reports_root=tmp_path))
    assert evs[-1].report_dir.endswith("AAPL_20261106_120000")


@pytest.mark.unit
def test_falls_back_to_sample_when_no_reports(tmp_path):
    evs = _drain(start_demo(delay=0, reports_root=tmp_path))
    assert evs[-1].kind == "done" and evs[-1].report_dir == str(SAMPLE_REPORT)


@pytest.mark.unit
def test_sample_report_is_parseable():
    runs, skipped = list_runs(SAMPLE_REPORT.parent)
    assert SAMPLE_REPORT in [r.path for r in runs] and skipped == 0
