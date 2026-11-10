# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

TradingAgents is a multi-agent LLM trading-research framework built on LangGraph: analysts → bull/bear debate → trader → risk debate → portfolio manager, producing a five-tier rating. Research use only; not trading advice.

## Commands

```bash
pip install -e ".[dev]"          # dev install (ruff, pytest); add ",ui" for Streamlit, ",bedrock" for AWS
pytest -q                        # full suite (integration tests excluded by default via addopts)
pytest tests/test_backtest.py::test_name -q   # single test
pytest -m integration            # tests that hit real services (only when asked)
ruff check .                     # lint — CI runs this on the whole repo and it must stay clean

tradingagents                    # interactive CLI (or: python -m cli.main)
tradingagents --ticker NVDA --date 2026-09-23 --analysts market,news,fundamentals --save --no-show
tradingagents-ui                 # Streamlit web UI at localhost:8501 (or: streamlit run webui/app.py)
python main.py                   # minimal programmatic example
```

CI (`.github/workflows/ci.yml`) runs pytest on Python 3.11–3.14, plus one run with `TZ=America/New_York` — tests must not assume UTC. It also checks that a bare `pip install .` (no dev extras) can `import tradingagents, cli.main`, so every runtime import must be a declared dependency. Ruff: line length 100, `E501` ignored, `ruff format` is intentionally *not* applied repo-wide.

## Test-suite guarantees (tests/conftest.py)

- **No network.** An autouse fixture makes socket connect, DNS, and yfinance's `curl_cffi` sessions raise `OSError("test tried to reach the network")`. Mock vendors; mark a test `integration` only if it truly needs the network.
- **No user state.** Before the package is imported, all `TRADINGAGENTS_*` env vars are blanked and results/cache/memory-log dirs are redirected to a temp dir, so a contributor's `.env` cannot change the defaults tests assert on.
- Markers are strict (`unit`, `integration`, `smoke`); tests are usually tagged `@pytest.mark.unit`.

## Architecture

**Entry point:** `tradingagents/graph/trading_graph.py::TradingAgentsGraph`. `propagate(ticker, date)` builds the graph, runs it, writes the memory log, and returns `(final_state, decision)`. The CLI (`cli/`) and web UI (`webui/runner.py`) both drive this same class via its stream — the UI is a thin layer over the engine, not a separate implementation.

**Graph** (`tradingagents/graph/setup.py`): each selected analyst runs as its own subgraph with a private message history and returns only its report key, so analysts execute in parallel without clobbering shared state. After `max_tool_rounds` tool rounds an analyst is forced to wrap up (and `2*max_tool_rounds+2` must stay below `max_recur_limit`). Debate routing lives in `conditional_logic.py`; every conditional edge maps *all* possible router targets (`DEBATE_PATH_MAP`, `RISK_ANALYSIS_PATH_MAP`) so a stray return value can't crash LangGraph. Checkpoint/resume (`checkpointer.py`, SQLite) keys on a run signature that includes graph shape.

**Two LLM tiers:** `quick_think_llm` serves analysts, researchers, debaters and trader; `deep_think_llm` serves the Research and Portfolio Managers. Each tier may have its own provider/backend URL (`quick_think_provider`, etc.). Clients are built by `llm_clients/factory.py` (provider SDKs imported lazily). Per-model API quirks belong in the declarative table in `llm_clients/capabilities.py`, not in `if` ladders inside clients; selectable models live in `llm_clients/model_catalog.py`.

**Structured agents:** Research Manager, Trader, Portfolio Manager (and Sentiment Analyst) use `with_structured_output` with Pydantic schemas in `agents/schemas.py`, rendered back to markdown, with a free-text fallback — the shared pattern is in `agents/structured.py`. Rating parsing is in `agents/rating.py`.

**Config:** `tradingagents/default_config.py` is the source of defaults. `_ENV_OVERRIDES` maps `TRADINGAGENTS_*` env vars to config keys (coerced to the default's type; bad values raise) — to make a new key env-configurable, add a row there. `.env` is loaded on package import. A graph binds its config into a `ContextVar` (`dataflows/config.py`) for the run so concurrent graphs read their own vendor settings.

**Data layer** (`tradingagents/dataflows/`):
- Agents call tools in `agents/tools.py`; tools call `router.route_to_vendor(tool_name, ...)`, which dispatches by `data_vendors` (category) / `tool_vendors` (per-tool) config. The configured value is the exact ordered vendor chain — never silently route to an unconfigured vendor.
- Vendors live under `dataflows/vendors/` and signal failure with the `VendorError` hierarchy in `dataflows/errors.py` (`NoMarketDataError`, `VendorUnavailableError`, `VendorNotConfiguredError`); the router reacts by exception type, so new vendors should raise these rather than add new `except` branches.
- **Only the data layer may import vendor libraries** (e.g. `yfinance`) — enforced by `tests/test_layering.py`.

**Point-in-time integrity is a core invariant.** Dated tools take `trade_date` from graph state via `InjectedState` and clamp requests with `dataflows/date_window.py` (`as_of`, `as_of_window`) so no data published after the analysis date reaches a model, whatever date the model asks for. Many tests (`*_lookahead`, `test_tool_date_enforcement`, `test_statement_knowledge_time`, `test_memory_pointintime`) guard this; any new data path must respect it.

**Memory & outcomes** (`tradingagents/memory/`): `log.py` is an append-only markdown decision log (`~/.tradingagents/memory/trading_memory.md`); `settlement.py` scores pending decisions against a benchmark (`benchmark_map` by exchange suffix) over `holding_period_days` from the first close after the decision; `reflection.py` writes reflections. `backtest.py` runs ticker × date grids; `portfolio.py` supplies holdings context; `reporting.py` / `report_html.py` save reports (markdown + single-page HTML).

**Invariant tests to keep in mind when editing agents:** every report-producing agent must call `agents/context.get_language_instruction()` (listed in `tests/test_i18n_coverage.py` — add new agents there); analyst briefs must be plain strings and absent reports must not be shown as empty sections (`tests/test_prompt_integrity.py`).

**Web UI** (`webui/`): Streamlit multipage app (`app.py` → `pages/*.py`). `runner.py` runs the engine on a background thread emitting `RunEvent`s, always sets the provider explicitly from the UI choice (clearing any `.env` tier overrides), and does preflight checks (Ollama reachable, key present) per model tier. The provider list (`providers.py`) and data-vendor options (`vendors.py`) are derived from the engine's own registries, and tests fail when the engine gains a provider the UI doesn't label. Advanced settings live in `UIPrefs`/`RunRequest` under the same field names (`prefs.RUN_SETTINGS`). Starts in demo mode replaying `webui/sample_report/`. Design specs/plans are in `docs/superpowers/`.

Runtime data (logs, cache, memory, CLI prefs, ChatGPT auth) defaults to `~/.tradingagents/`, overridable via `TRADINGAGENTS_RESULTS_DIR`, `TRADINGAGENTS_CACHE_DIR`, `TRADINGAGENTS_MEMORY_LOG_PATH`.
