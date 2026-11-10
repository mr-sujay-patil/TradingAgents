"""The UI offers every provider the engine serves, and knows what each one needs."""

import importlib.util

import pytest

from tradingagents.llm_clients.api_key_env import PROVIDER_API_KEY_ENV
from webui import providers


@pytest.mark.unit
def test_every_engine_provider_is_offered():
    """A provider added to the engine fails here until the UI gives it a label."""
    assert set(providers.KEYS) == set(PROVIDER_API_KEY_ENV) - providers.NOT_IN_UI
    assert len(providers.KEYS) == len(set(providers.KEYS))


@pytest.mark.unit
def test_only_local_servers_are_free():
    assert not providers.is_paid("ollama") and not providers.is_paid("openai_compatible")
    assert all(providers.is_paid(k) for k in providers.KEYS if k not in ("ollama", "openai_compatible"))
    assert providers.is_paid("something-new")


@pytest.mark.unit
def test_model_choices_come_from_the_catalog():
    assert "gpt-6-luna" in providers.model_choices("openai", "quick")
    assert "custom" not in providers.model_choices("openai", "deep")
    assert providers.model_choices("groq", "quick") == []          # custom-only provider
    assert providers.model_choices("azure", "quick") == []          # not in the catalog


@pytest.mark.unit
def test_missing_key_named(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert providers.missing_setup("anthropic") == "No Anthropic key in `.env` (`ANTHROPIC_API_KEY`)."
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert providers.missing_setup("anthropic") is None


@pytest.mark.unit
def test_openai_compatible_needs_an_endpoint():
    assert "URL" in providers.missing_setup("openai_compatible", "")
    assert providers.missing_setup("openai_compatible", "http://localhost:8000/v1") is None


@pytest.mark.unit
def test_azure_names_what_is_unset(monkeypatch):
    for var in providers.AZURE_ENV:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")
    problem = providers.missing_setup("azure")
    assert "AZURE_OPENAI_ENDPOINT" in problem and "AZURE_OPENAI_API_KEY" not in problem


@pytest.mark.unit
def test_bedrock_needs_its_extra(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    assert "tradingagents[bedrock]" in providers.missing_setup("bedrock")


@pytest.mark.unit
def test_key_status_never_holds_values(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-secret")
    rows = providers.key_status()
    assert ("Groq", "GROQ_API_KEY", True) in rows
    assert all(isinstance(is_set, bool) for _, _, is_set in rows)
    assert "gsk-secret" not in repr(rows)
