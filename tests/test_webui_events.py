"""Run events and the one active run every browser tab shares."""

import pytest

import webui.events as ev
from webui.events import RunEvent, RunHandle, active_run, set_active_run


@pytest.mark.unit
def test_events_since_returns_only_new():
    h = RunHandle("x")
    h.emit(RunEvent("stage", stage="market", status="running"))
    h.emit(RunEvent("report", stage="market", content="m"))
    assert [e.kind for e in h.events_since(1)] == ["report"]
    assert len(h.events_since(0)) == 2


@pytest.mark.unit
def test_finished_after_done_or_error():
    h = RunHandle("x")
    h.emit(RunEvent("report", stage="market", content="m"))
    assert not h.finished
    h.emit(RunEvent("error", content="boom"))
    assert h.finished
    d = RunHandle("y")
    d.emit(RunEvent("done", rating="Hold"))
    assert d.finished


@pytest.mark.unit
def test_registry_survives_across_callers():
    h = RunHandle("x")
    set_active_run(h)
    try:
        assert ev.active_run() is h and active_run() is h
    finally:
        set_active_run(None)
    assert active_run() is None
