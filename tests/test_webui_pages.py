"""The Streamlit pages render, and show what they promise, without a browser."""

from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402

from tradingagents.default_config import DEFAULT_CONFIG  # noqa: E402
from webui import prefs as prefs_mod  # noqa: E402
from webui.events import set_active_run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "webui" / "app.py")


def page(name):
    return str(ROOT / "webui" / "pages" / f"{name}.py")


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs_mod, "PREFS_PATH", tmp_path / "webui_prefs.json")
    monkeypatch.setitem(DEFAULT_CONFIG, "results_dir", str(tmp_path / "logs"))
    yield
    set_active_run(None)


def _text(at):
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption]
    parts += [m.value for m in at.sidebar.markdown]
    return " ".join(parts)


@pytest.mark.unit
def test_app_renders_without_error():
    at = AppTest.from_file(APP).run()
    assert not at.exception
    assert "Mode: Demo" in _text(at) and "Ollama" in _text(at)


@pytest.mark.unit
def test_settings_shows_key_status_not_value(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret123")
    monkeypatch.setenv("FRED_API_KEY", "")
    at = AppTest.from_file(page("settings")).run()
    assert not at.exception
    text = _text(at)
    assert "OpenAI key: set" in text and "FRED key: missing" in text
    assert "sk-secret123" not in text


@pytest.mark.unit
def test_settings_save_persists(tmp_path):
    at = AppTest.from_file(page("settings")).run()
    at.radio(key="provider").set_value("OpenAI")
    at.button(key="save").click().run()
    assert not at.exception
    assert prefs_mod.load_prefs().provider == "openai"


@pytest.mark.unit
def test_rating_badge_colors():
    from webui.ui_common import rating_badge
    assert "green" in rating_badge("Buy") and "green" in rating_badge("Overweight")
    assert "red" in rating_badge("Sell") and "red" in rating_badge("Underweight")
    assert "gray" in rating_badge("Hold") and "gray" in rating_badge("—")


def _run_until(at, predicate, timeout=10):
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        at.run()
        if predicate(at):
            return True
        time.sleep(0.05)
    return False


@pytest.mark.unit
def test_run_disabled_without_analysts():
    at = AppTest.from_file(page("new_run")).run()
    at.text_input(key="run_ticker").input("AAPL").run()
    assert not at.button(key="run").disabled
    for name in ("market", "sentiment", "news", "fundamentals"):
        at.checkbox(key=f"analyst_{name}").uncheck()
    at.run()
    assert at.button(key="run").disabled


@pytest.mark.unit
def test_run_disabled_without_ticker():
    at = AppTest.from_file(page("new_run")).run()
    assert at.button(key="run").disabled


@pytest.mark.unit
def test_date_cannot_be_in_the_future():
    from datetime import date
    at = AppTest.from_file(page("new_run")).run()
    assert at.date_input(key="run_date").proto.max == date.today().isoformat()


@pytest.mark.unit
def test_paid_requires_confirmation():
    prefs_mod.save_prefs(prefs_mod.UIPrefs(provider="openai", quick_model="gpt-6-luna",
                                           deep_model="gpt-6-sol", demo_mode=False))
    at = AppTest.from_file(page("new_run")).run()
    at.text_input(key="run_ticker").input("AAPL").run()
    assert at.button(key="run").disabled
    at.checkbox(key="paid_ok").check().run()
    assert not at.button(key="run").disabled


@pytest.mark.unit
def test_demo_run_shows_progress(monkeypatch):
    from webui import demo
    monkeypatch.setattr(demo, "DEMO_DELAY", 0)
    at = AppTest.from_file(page("new_run")).run()
    at.text_input(key="run_ticker").input("AAPL").run()
    at.button(key="run").click().run()
    assert _run_until(at, lambda a: any(e.label == "Portfolio Manager" for e in a.expander))
    assert not at.exception
    assert "Hold" in _text(at)


@pytest.mark.unit
def test_active_run_shown_after_refresh():
    from webui.events import RunEvent, RunHandle
    h = RunHandle("AAPL 2026-11-06")
    h.emit(RunEvent("stage", stage="market", status="running"))
    set_active_run(h)
    at = AppTest.from_file(page("new_run")).run()
    assert not at.exception
    assert not [t for t in at.text_input if t.key == "run_ticker"]
    assert "AAPL 2026-11-06" in _text(at)


@pytest.mark.unit
def test_error_event_shows_message_and_back_button():
    from webui.events import RunEvent, RunHandle
    h = RunHandle("AAPL 2026-11-06")
    h.emit(RunEvent("error", content="Ollama isn't running. Start it with `ollama serve`.", detail="tb"))
    set_active_run(h)
    at = AppTest.from_file(page("new_run")).run()
    assert "Ollama isn't running" in at.error[0].value
    at.button(key="back").click().run()
    assert [t for t in at.text_input if t.key == "run_ticker"]


@pytest.mark.unit
def test_home_lists_recent(tmp_path):
    from tests.webui_helpers import make_run
    reports = Path(DEFAULT_CONFIG["results_dir"]) / "reports"
    make_run(reports, "AAPL", "2026-11-06")
    make_run(reports, "NVDA", "2026-11-05")
    at = AppTest.from_file(page("home")).run()
    assert not at.exception
    text = _text(at)
    assert "AAPL" in text and "NVDA" in text


@pytest.mark.unit
def test_pipeline_marks_done_running_pending():
    from webui.events import RunEvent
    from webui.ui_common import _pipeline
    evs = [RunEvent("stage", stage="market"), RunEvent("stage", stage="news"),
           RunEvent("report", stage="market")]
    assert _pipeline(evs).split("  →  ")[:3] == ["✅ Market Analyst", "⏳ News Analyst", "○ Bull/Bear debate"]
    evs += [RunEvent("report", stage="news")]
    assert "⏳ Bull/Bear debate" in _pipeline(evs) and "○ Research Manager" in _pipeline(evs)
    evs += [RunEvent("report", stage="bull"), RunEvent("report", stage="manager")]
    p = _pipeline(evs)
    assert "✅ Bull/Bear debate" in p and "⏳ Research Manager" in p and "○ Trader" in p
    evs += [RunEvent("report", stage="portfolio"), RunEvent("done", rating="Hold")]
    assert "⏳" not in _pipeline(evs) and "○" not in _pipeline(evs)
