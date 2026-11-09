"""The Streamlit pages render, and show what they promise, without a browser."""

from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402

from tradingagents.default_config import DEFAULT_CONFIG  # noqa: E402
from webui import (
    portfolio_store,  # noqa: E402
    prefs as prefs_mod,  # noqa: E402
)
from webui.events import set_active_run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "webui" / "app.py")


def page(name):
    return str(ROOT / "webui" / "pages" / f"{name}.py")


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs_mod, "PREFS_PATH", tmp_path / "webui_prefs.json")
    monkeypatch.setitem(DEFAULT_CONFIG, "results_dir", str(tmp_path / "logs"))
    monkeypatch.setitem(DEFAULT_CONFIG, "memory_log_path", str(tmp_path / "memory" / "trading_memory.md"))
    monkeypatch.setitem(DEFAULT_CONFIG, "data_cache_dir", str(tmp_path / "cache"))
    monkeypatch.setattr(portfolio_store, "PORTFOLIO_PATH", tmp_path / "webui_portfolio.json")
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


def _reports_with(*specs):
    from tests.webui_helpers import make_run
    reports = Path(DEFAULT_CONFIG["results_dir"]) / "reports"
    return [make_run(reports, t, d, stamp=s) for t, d, s in specs]


THREE = (("AAPL", "2026-11-03", "100000"), ("NVDA", "2026-11-05", "110000"),
         ("MSFT", "2026-11-06", "120000"))


@pytest.mark.unit
def test_history_lists_runs():
    _reports_with(*THREE)
    at = AppTest.from_file(page("history")).run()
    assert not at.exception
    assert len(at.dataframe[0].value) == 3


@pytest.mark.unit
def test_open_report_shows_tabs():
    path = _reports_with(THREE[0])[0]
    at = AppTest.from_file(page("history"))
    at.session_state["open_report"] = str(path)
    at.run()
    assert not at.exception
    assert [t.label for t in at.tabs] == ["Analysts", "Research", "Trader", "Risk", "Decision"]
    assert "Hold" in _text(at)


@pytest.mark.unit
def test_compare_two():
    _reports_with(*THREE)
    at = AppTest.from_file(page("history")).run()
    pick = at.multiselect(key="pick")
    pick.set_value(pick.options[:2]).run()
    assert not at.exception
    headers = [m.value for m in at.markdown if m.value.startswith("### ")]
    assert len(headers) == 2


@pytest.mark.unit
def test_compare_four_warns():
    _reports_with(*THREE, ("TSLA", "2026-11-04", "130000"))
    at = AppTest.from_file(page("history")).run()
    pick = at.multiselect(key="pick")
    pick.set_value(pick.options[:4]).run()
    assert "Select up to 3 runs to compare." in at.warning[0].value


@pytest.mark.unit
def test_filter_narrows_table():
    _reports_with(*THREE)
    at = AppTest.from_file(page("history")).run()
    at.multiselect(key="f_ticker").set_value(["NVDA"]).run()
    assert list(at.dataframe[0].value["Ticker"]) == ["NVDA"]


@pytest.mark.unit
def test_skipped_caption():
    _reports_with(THREE[0])
    (Path(DEFAULT_CONFIG["results_dir"]) / "reports" / "BROKEN").mkdir()
    at = AppTest.from_file(page("history")).run()
    assert "Skipped 1" in _text(at)


@pytest.mark.unit
def test_history_empty():
    at = AppTest.from_file(page("history")).run()
    assert not at.exception and "No saved runs yet" in _text(at)


# --- v2: portfolio and resume ---------------------------------------------


@pytest.mark.unit
def test_settings_saves_portfolio():
    at = AppTest.from_file(page("settings")).run()
    at.text_input(key="pf_currency").input("inr")
    at.number_input(key="pf_cash").set_value(5000.0)
    at.button(key="pf_save").click().run()
    assert not at.exception
    book = portfolio_store.load()
    assert book is not None and book.currency == "INR" and book.cash == 5000.0


@pytest.mark.unit
def test_settings_saves_checkpoint_toggle():
    at = AppTest.from_file(page("settings")).run()
    at.toggle(key="checkpoint").set_value(False)
    at.button(key="save").click().run()
    assert prefs_mod.load_prefs().checkpoint is False


@pytest.mark.unit
def test_new_run_portfolio_toggle_only_when_saved():
    at = AppTest.from_file(page("new_run")).run()
    assert not [c for c in at.checkbox if c.key == "run_portfolio"]
    assert "No portfolio saved" in _text(at)
    portfolio_store.save(portfolio_store.from_rows([{"ticker": "AAPL", "quantity": 2}]))
    at = AppTest.from_file(page("new_run")).run()
    assert at.checkbox(key="run_portfolio").value is True


@pytest.mark.unit
def test_new_run_passes_portfolio_and_checkpoint(monkeypatch):
    from webui import runner
    prefs_mod.save_prefs(prefs_mod.UIPrefs(demo_mode=False))
    portfolio_store.save(portfolio_store.from_rows([{"ticker": "AAPL", "quantity": 2}]))
    seen = []
    monkeypatch.setattr(runner, "preflight", lambda req: None)
    monkeypatch.setattr(runner, "start_run", lambda req: seen.append(req))
    at = AppTest.from_file(page("new_run")).run()
    at.text_input(key="run_ticker").input("aapl").run()
    at.button(key="run").click().run()
    assert seen and seen[0].portfolio.positions[0].ticker == "AAPL" and seen[0].checkpoint is True
    seen.clear()
    at.checkbox(key="run_portfolio").uncheck().run()
    at.button(key="run").click().run()
    assert seen and seen[0].portfolio is None


@pytest.mark.unit
def test_failed_run_offers_resume(monkeypatch):
    from webui import runner
    from webui.events import RunEvent, RunHandle
    req = runner.RunRequest("AAPL", "2026-11-06", ["market"], "ollama", "q", "q",
                            "http://x/v1", 1, 1, checkpoint=True)
    h = RunHandle("AAPL 2026-11-06", kind="analysis", request=req)
    h.emit(RunEvent("error", content="The run stopped: boom"))
    set_active_run(h)
    restarted = []
    monkeypatch.setattr(runner, "start_run", lambda r: restarted.append(r))
    at = AppTest.from_file(page("new_run")).run()
    assert at.button(key="resume").label == "Resume"
    at.button(key="resume").click().run()
    assert restarted == [req]


@pytest.mark.unit
def test_other_job_blocks_new_run():
    from webui.events import RunHandle
    set_active_run(RunHandle("Backtest · AAPL", kind="backtest"))
    at = AppTest.from_file(page("new_run")).run()
    assert not at.exception
    assert any("Backtest in progress" in i.value for i in at.info)


# --- v2: outcomes and backtest ---------------------------------------------


def _memory(tmp_path):
    from tradingagents.memory import TradingMemoryLog
    return TradingMemoryLog({"memory_log_path": DEFAULT_CONFIG["memory_log_path"]})


@pytest.mark.unit
def test_outcomes_empty_state(tmp_path):
    at = AppTest.from_file(page("outcomes")).run()
    assert not at.exception and "No decisions recorded yet" in _text(at)


@pytest.mark.unit
def test_outcomes_lists_and_scores(tmp_path):
    log = _memory(tmp_path)
    log.store_decision("AAPL", "2026-10-01", "**Rating**: Buy\n\nup")
    log.store_decision("NVDA", "2026-11-05", "**Rating**: Hold\n\nwait")
    log.update_with_outcome("AAPL", "2026-10-01", 0.05, 0.02, 5, "Right call.", resolution_date="2026-10-08")
    at = AppTest.from_file(page("outcomes")).run()
    assert not at.exception
    assert [m.value for m in at.metric] == ["2", "1", "1"]
    assert at.button(key="settle").disabled   # demo mode on by default
    at.selectbox(key="o_pick").set_value(0).run()
    assert "Right call." in _text(at)


@pytest.mark.unit
def test_outcomes_settle_starts_job(tmp_path, monkeypatch):
    from webui import outcomes, runner
    prefs_mod.save_prefs(prefs_mod.UIPrefs(demo_mode=False))
    _memory(tmp_path).store_decision("AAPL", "2026-10-01", "**Rating**: Buy")
    started = []
    monkeypatch.setattr(runner, "preflight", lambda req: None)
    monkeypatch.setattr(outcomes, "start_settle", lambda req: started.append(req))
    at = AppTest.from_file(page("outcomes")).run()
    assert not at.button(key="settle").disabled
    at.button(key="settle").click().run()
    assert not at.exception and started and started[0].provider == "ollama"


@pytest.mark.unit
def test_history_shows_outcome_column(tmp_path):
    from tests.webui_helpers import make_run
    root = Path(DEFAULT_CONFIG["results_dir"]) / "reports"
    make_run(root, "AAPL", "2026-10-01")
    log = _memory(tmp_path)
    log.store_decision("AAPL", "2026-10-01", "**Rating**: Hold")
    log.update_with_outcome("AAPL", "2026-10-01", 0.05, 0.02, 5, "ok", resolution_date="2026-10-08")
    at = AppTest.from_file(page("history")).run()
    assert not at.exception
    assert list(at.dataframe[0].value["Outcome"]) == ["α +2.0%"]


@pytest.mark.unit
def test_backtest_disabled_in_demo_mode():
    at = AppTest.from_file(page("backtest")).run()
    at.text_input(key="bt_tickers").input("AAPL").run()
    assert not at.exception and at.button(key="bt_run").disabled
    assert any("off in demo mode" in w.value for w in at.warning)


@pytest.mark.unit
def test_backtest_counts_and_caps():
    prefs_mod.save_prefs(prefs_mod.UIPrefs(demo_mode=False))
    at = AppTest.from_file(page("backtest")).run()
    at.text_input(key="bt_tickers").input("aapl, msft").run()
    assert "= **" in " ".join(i.value for i in at.info) and not at.button(key="bt_run").disabled
    at.number_input(key="bt_every").set_value(1).run()
    at.text_input(key="bt_tickers").input("A, B, C").run()
    assert at.button(key="bt_run").disabled and any("limit of 60" in e.value for e in at.error)


@pytest.mark.unit
def test_backtest_starts_and_lists_past(tmp_path, monkeypatch):
    from tradingagents.memory import TradingMemoryLog
    from webui import backtest_runner
    prefs_mod.save_prefs(prefs_mod.UIPrefs(demo_mode=False))
    log = Path(DEFAULT_CONFIG["results_dir"]) / "backtest" / "20261101_100000" / "trading_memory.md"
    TradingMemoryLog({"memory_log_path": str(log)}).store_decision("NVDA", "2026-10-01", "**Rating**: Buy")
    started = []
    monkeypatch.setattr("webui.runner.preflight", lambda req: None)
    monkeypatch.setattr(backtest_runner, "start_backtest", lambda req: started.append(req))
    at = AppTest.from_file(page("backtest")).run()
    assert any("20261101_100000" in e.label for e in at.expander)
    at.text_input(key="bt_tickers").input("AAPL").run()
    at.selectbox(key="bt_continue").set_value("20261101_100000").run()
    at.button(key="bt_run").click().run()
    assert not at.exception and started and started[0].run_id == "20261101_100000"


@pytest.mark.unit
def test_backtest_progress_view():
    from webui.events import RunEvent, RunHandle
    h = RunHandle("AAPL · 2026-01-05 → 2026-01-26", kind="backtest")
    h.emit(RunEvent("progress", done=2, total=4, content="AAPL 2026-01-19"))
    set_active_run(h)
    at = AppTest.from_file(page("backtest")).run()
    assert not at.exception and not [t for t in at.text_input if t.key == "bt_tickers"]
    h.emit(RunEvent("done", title="20261109_1", content="Resolved cells: 0", report_dir="/x"))
    at.run()
    assert any("Sweep 20261109_1 finished" in s.value for s in at.success)
