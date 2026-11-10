"""Settings' data-vendor chains: offered from the engine's router, checked before they're saved."""

import pytest

from tradingagents.default_config import DEFAULT_CONFIG
from webui import vendors


@pytest.mark.unit
def test_options_come_from_the_router():
    assert vendors.options("fundamental_data") == ["alpha_vantage", "yfinance", "sec_edgar"]
    assert "macro_data" not in vendors.choosable()          # one vendor: nothing to choose


@pytest.mark.unit
def test_a_chain_must_serve_every_tool_in_its_category():
    """SEC EDGAR files statements but has no company overview."""
    assert "get_fundamentals" in vendors.chain_problem("fundamental_data", ["sec_edgar"])
    assert vendors.chain_problem("fundamental_data", ["sec_edgar", "yfinance"]) is None
    assert vendors.chain_problem("news_data", []) == "Pick at least one vendor."


@pytest.mark.unit
def test_only_changed_chains_are_saved():
    chains = {"fundamental_data": vendors.default_chain("fundamental_data"),
              "news_data": ["alpha_vantage", "yfinance"]}
    assert vendors.overrides(chains) == {"news_data": "alpha_vantage,yfinance"}
    saved = {"news_data": "alpha_vantage,yfinance"}
    assert vendors.chain_for(saved, "news_data") == ["alpha_vantage", "yfinance"]
    default = DEFAULT_CONFIG["data_vendors"]["fundamental_data"].split(",")
    assert vendors.chain_for({}, "fundamental_data") == default


@pytest.mark.unit
def test_missing_vendor_key_is_noted(monkeypatch):
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    assert any("ALPHA_VANTAGE_API_KEY" in n for n in vendors.key_notes(["alpha_vantage", "yfinance"]))
    assert vendors.key_notes(["yfinance"]) == []
