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
