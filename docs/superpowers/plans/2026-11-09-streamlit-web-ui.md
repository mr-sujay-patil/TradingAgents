# TradingAgents Web UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local Streamlit UI (Home, New run with live progress, History with compare, Settings) over the existing TradingAgents engine.

**Architecture:** A new `webui/` package. Non-UI modules (`stages`, `events`, `prefs`, `history`, `demo`, `runner`) are pure Python and unit-tested; only `app.py` and `pages/` import Streamlit. A run executes `TradingAgentsGraph.stream_run()` in a background thread and publishes `RunEvent`s to a `RunHandle`; demo mode replays a saved report through the same handle.

**Tech Stack:** Python 3.11+, Streamlit ≥ 1.40 (`st.navigation`, `st.fragment(run_every=...)`, `streamlit.testing.v1.AppTest`), `requests` (already a dependency), pytest.

**Spec:** `docs/superpowers/specs/2026-11-09-streamlit-web-ui-design.md`

## Global Constraints

- No edits under `tradingagents/`. `cli/` is read-only too.
- Streamlit is imported only in `webui/app.py`, `webui/pages/*`, `webui/launch.py`. `import tradingagents` and `import cli.main` must keep working without Streamlit installed.
- Optional extra: `ui = ["streamlit>=1.40"]` in `pyproject.toml`; add `"webui*"` to `[tool.setuptools.packages.find] include`; console script `tradingagents-ui = "webui.launch:main"`.
- The run config always sets `llm_provider` explicitly from the UI choice; never rely on provider auto-detection.
- Prefs file: `Path(_TRADINGAGENTS_HOME) / "webui_prefs.json"` (`from tradingagents.default_config import _TRADINGAGENTS_HOME`).
- Defaults: provider `ollama`, quick and deep model `qwen3:4b`, Ollama URL `http://localhost:11434/v1`, analysts `market, news, fundamentals`, 1 debate round, 1 risk round, demo mode on.
- OpenAI backend URL: `https://api.openai.com/v1`.
- Reports are read from and written to `Path(DEFAULT_CONFIG["results_dir"]) / "reports"`, saved via `graph.default_report_path(ticker)` + `graph.save_reports(final_state, ticker, path, html=True)`.
- UI analyst name `sentiment` maps to the graph key `social` (`tradingagents.reporting.analyst_names` is the reverse map).
- Error copy, verbatim: `Ollama isn't running. Start it with \`ollama serve\`.` · `Model \`{model}\` isn't installed. Run \`ollama pull {model}\`.` · `No OpenAI key in \`.env\`.` · `The run stopped: {exc}`.
- Tests: no network (conftest blocks sockets), pass under `TZ=America/New_York`, Streamlit tests use `pytest.importorskip("streamlit")`. Use tmp dirs, never the user's `~/.tradingagents`.
- `ruff check .` clean; never run `ruff format` repo-wide.
- Manual testing uses demo mode and Ollama only. **No OpenAI calls** unless the user says so.

## Review Focus

1. **Ticker typed with spaces or lowercase (` aapl `)** → run as `AAPL`; a ticker with path characters (`../x`) gives an error event, not a crash. (Task 5)
2. **Browser refresh or a second tab during a run** → the run continues and the new view shows the same progress; Run stays disabled. (Tasks 2, 7)
3. **A report folder from an older version with no `Rating:` line, or a half-written folder** → listed with rating `—`, or skipped and counted; History never crashes. (Task 3)
4. **No analysts ticked / future date** → Run disabled; the date picker's max is today. (Task 7)
5. **Paid provider selected while demo mode is off** → Run stays disabled until the "I understand this run uses paid API credits" box is ticked. (Task 7)

---

## File Structure

```
webui/
  __init__.py        empty
  stages.py          STAGES table shared by history, demo, runner, pages
  events.py          RunEvent, RunHandle, active-run registry
  prefs.py           UIPrefs + load/save
  history.py         RunSummary, RunDetail, list_runs, load_run, filter_runs
  demo.py            start_demo
  runner.py          RunRequest, build_config, preflight, state_to_events, start_run
  ui_common.py       sidebar status, rating badge, render_progress (Streamlit)
  app.py             st.navigation entry point
  launch.py          tradingagents-ui → streamlit run app.py
  pages/home.py, new_run.py, history.py, settings.py
  sample_report/     a small bundled report tree for demo fallback
tests/
  test_webui_prefs.py, test_webui_history.py, test_webui_demo.py,
  test_webui_events.py, test_webui_runner.py, test_webui_pages.py, webui_helpers.py
```

---

### Task 1: Package skeleton, stages, prefs

**Files:**
- Modify: `pyproject.toml` (optional-dependencies, scripts, packages.find)
- Create: `webui/__init__.py`, `webui/stages.py`, `webui/prefs.py`
- Test: `tests/test_webui_prefs.py`

**Interfaces:**
- Produces:
  - `webui.stages.Stage = NamedTuple(key: str, title: str, group: str, relpath: str)`
  - `webui.stages.STAGES: tuple[Stage, ...]`, in this order:
    `market/Market Analyst/analysts/1_analysts/market.md`, `sentiment/Sentiment Analyst/analysts/1_analysts/sentiment.md`, `news/News Analyst/analysts/1_analysts/news.md`, `fundamentals/Fundamentals Analyst/analysts/1_analysts/fundamentals.md`, `bull/Bull Researcher/debate/2_research/bull.md`, `bear/Bear Researcher/debate/2_research/bear.md`, `manager/Research Manager/manager/2_research/manager.md`, `trader/Trader/trader/3_trading/trader.md`, `aggressive/Aggressive Analyst/risk/4_risk/aggressive.md`, `conservative/Conservative Analyst/risk/4_risk/conservative.md`, `neutral/Neutral Analyst/risk/4_risk/neutral.md`, `portfolio/Portfolio Manager/portfolio/5_portfolio/decision.md`
  - `webui.stages.GROUPS = ("analysts", "debate", "manager", "trader", "risk", "portfolio")`
  - `webui.stages.ANALYSTS = ("market", "sentiment", "news", "fundamentals")`
  - `webui.prefs.UIPrefs` dataclass: `provider: str`, `quick_model: str`, `deep_model: str`, `ollama_url: str`, `analysts: list[str]`, `debate_rounds: int`, `risk_rounds: int`, `demo_mode: bool` with the Global Constraints defaults
  - `webui.prefs.PREFS_PATH: Path`; `load_prefs(path: Path = PREFS_PATH) -> UIPrefs`; `save_prefs(prefs: UIPrefs, path: Path = PREFS_PATH) -> None`

- [ ] **Step 1: Write the failing tests** in `tests/test_webui_prefs.py`

```python
def test_missing_file_gives_defaults(tmp_path):
    p = load_prefs(tmp_path / "none.json")
    assert p.provider == "ollama" and p.quick_model == "qwen3:4b" and p.deep_model == "qwen3:4b"
    assert p.analysts == ["market", "news", "fundamentals"]
    assert (p.debate_rounds, p.risk_rounds, p.demo_mode) == (1, 1, True)

def test_round_trip(tmp_path): ...            # save with provider="openai", load → equal
def test_corrupt_json_gives_defaults(tmp_path): ...  # file "{not json" → UIPrefs()
def test_unknown_keys_ignored(tmp_path): ...  # {"provider":"openai","bogus":1} → provider openai
def test_stages_cover_every_report_file():
    from tradingagents.reporting import _SECTIONS
    files = {f"{folder}/{f}" for _h, folder, agents in _SECTIONS for _a, f, _p in agents}
    assert {s.relpath for s in STAGES} == files
```

- [ ] **Step 2:** `pytest tests/test_webui_prefs.py -v` → FAIL (`ModuleNotFoundError: webui`)
- [ ] **Step 3: Implement** `stages.py`, `prefs.py` (JSON via `dataclasses.asdict`; load keeps only known fields; any `OSError`/`ValueError` → defaults), and the `pyproject.toml` changes. Then `pip install -e ".[ui,dev]"`.
- [ ] **Step 4:** `pytest tests/test_webui_prefs.py -v` → PASS; `python -c "import tradingagents, cli.main"` → no error
- [ ] **Step 5: Commit** `feat(webui): package skeleton, stage table and prefs`

---

### Task 2: Events and run registry

**Files:**
- Create: `webui/events.py`
- Test: `tests/test_webui_events.py`

**Interfaces:**
- Produces:
  - `RunEvent` dataclass exactly as in spec §4.1 (`kind: Literal["stage", "report", "done", "error"]`, `stage`, `status`, `title`, `content`, `report_dir`, `rating`, all optional except `kind`). Add `detail: str | None = None` for the error traceback.
  - `class RunHandle`: `__init__(self, label: str)`; `emit(event: RunEvent) -> None` (thread-safe, `threading.Lock`); `events_since(index: int) -> list[RunEvent]`; property `finished -> bool` (a `done` or `error` event was emitted); `label: str`; `started_at: float` (`time.monotonic()`).
  - `active_run() -> RunHandle | None` and `set_active_run(handle: RunHandle | None) -> None`, backed by a module-level variable guarded by a lock. Module state is per-process in Streamlit, so every tab and every refresh sees the same run (Review Focus 2).

- [ ] **Step 1: Write the failing tests**

```python
def test_events_since_returns_only_new():
    h = RunHandle("x"); h.emit(RunEvent("stage", stage="market", status="running"))
    h.emit(RunEvent("report", stage="market", content="m"))
    assert [e.kind for e in h.events_since(1)] == ["report"]

def test_finished_after_done_or_error(): ...   # False, then True after RunEvent("error", content="boom")
def test_registry_survives_across_callers():
    h = RunHandle("x"); set_active_run(h)
    import webui.events as ev
    assert ev.active_run() is h
    set_active_run(None)
```

- [ ] **Step 2:** run → FAIL; **Step 3:** implement; **Step 4:** run → PASS
- [ ] **Step 5: Commit** `feat(webui): run events and active-run registry`

---

### Task 3: History reader

**Files:**
- Create: `webui/history.py`, `tests/webui_helpers.py` (holds `make_run`, shared by Tasks 3–8)
- Test: `tests/test_webui_history.py`

**Interfaces:**
- Consumes: `STAGES` (Task 1)
- Produces:
  - `RunSummary` dataclass: `path: Path`, `ticker: str`, `analysis_date: str`, `rating: str` (`"—"` when absent), `generated: str`, `models: str`, `analysts: str`
  - `RunDetail` dataclass: `summary: RunSummary`, `sections: dict[str, str]` (stage key → markdown; absent files omitted)
  - `REPORTS_DIR: Path` = `Path(DEFAULT_CONFIG["results_dir"]) / "reports"`, read at call time via a `reports_dir()` function so tests can monkeypatch the config.
  - `list_runs(reports_dir: Path) -> tuple[list[RunSummary], int]`: (runs newest-`generated` first, count of skipped folders)
  - `load_run(path: Path) -> RunDetail`
  - `filter_runs(runs, tickers: list[str] | None = None, start: date | None = None, end: date | None = None, ratings: list[str] | None = None) -> list[RunSummary]` (bounds inclusive)

Header parsing reads the lines `reporting._header` writes: title `# Trading Analysis Report: {ticker}`, `- Analysis date: `, `- Rating: `, `- Generated: `, the `- TradingAgents {version}: {models}` line (models = text after the first `: `), `- Analysts: ` (text up to `;`). A folder with no `complete_report.md`, or whose title line doesn't match, is skipped. Cache parsing with `functools.lru_cache` keyed on `(path, mtime)`.

- [ ] **Step 1: Write the failing tests.** Build fixtures with the real writer so the parser tracks the real format:

```python
def make_run(root, ticker, date, decision="**Rating**: Hold\n\nok", name=None):
    from tradingagents.reporting import write_report_tree
    state = {"trade_date": date, "market_report": "m", "news_report": "n",
             "investment_debate_state": {"bull_history": "b", "bear_history": "r"},
             "investment_plan": "p", "trader_investment_plan": "t",
             "risk_debate_state": {"aggressive_history": "a", "conservative_history": "c",
                                   "neutral_history": "u"},
             "final_trade_decision": decision}
    settings = {"llm_provider": "ollama", "deep_think_llm": "qwen3:4b",
                "quick_think_llm": "qwen3:4b", "version": "0.7.1",
                "analysts": ["market", "news"], "max_debate_rounds": 1,
                "max_risk_discuss_rounds": 1}
    path = root / (name or f"{ticker}_{date.replace('-', '')}_120000")
    write_report_tree(state, ticker, path, settings=settings, html=False)
    return path

def test_lists_and_parses_header(tmp_path):
    make_run(tmp_path, "AAPL", "2026-11-06")
    runs, skipped = list_runs(tmp_path)
    r = runs[0]
    assert (r.ticker, r.analysis_date, r.rating, skipped) == ("AAPL", "2026-11-06", "Hold", 0)
    assert "qwen3:4b" in r.models and r.analysts == "market, news"

def test_missing_rating_shows_dash(tmp_path): ...   # strip the "- Rating:" line from complete_report.md → "—"
def test_half_written_folder_is_skipped(tmp_path): ... # empty dir + garbage complete_report.md → skipped == 2, no exception
def test_missing_reports_dir(tmp_path): ...        # list_runs(tmp_path/"nope") == ([], 0)
def test_load_run_sections(tmp_path): ...          # sections["market"] == "m", "sentiment" not in sections, "portfolio" present
def test_filter_by_ticker_date_rating(tmp_path): ... # 3 runs; each filter narrows as expected; date bounds inclusive
```

- [ ] **Step 2:** run → FAIL; **Step 3:** implement; **Step 4:** run → PASS (also under `TZ=America/New_York pytest tests/test_webui_history.py`)
- [ ] **Step 5: Commit** `feat(webui): read saved reports for history`

---

### Task 4: Demo replay

**Files:**
- Create: `webui/demo.py`, `webui/sample_report/` (generate once with `make_run`-style data using realistic short text; commit the `.md` files, `html=False`)
- Modify: `pyproject.toml` package-data: `webui = ["sample_report/**/*.md"]`
- Test: `tests/test_webui_demo.py`

**Interfaces:**
- Consumes: `RunEvent`, `RunHandle`, `set_active_run` (Task 2); `list_runs`, `load_run` (Task 3); `STAGES`
- Produces: `SAMPLE_REPORT: Path`; `start_demo(report_dir: Path | None = None, delay: float = 1.0, reports_root: Path | None = None) -> RunHandle`. With `report_dir=None` it uses the newest run in `reports_root` (default `history.reports_dir()`), else `SAMPLE_REPORT`. It registers the handle with `set_active_run`, then a daemon thread emits: one `stage/running` per analyst present; one `report` per present section in `STAGES` order (`title` from the stage), sleeping `delay` between; then `done` with `rating` and `report_dir=str(report_dir)`. It writes nothing to disk.

- [ ] **Step 1: Write the failing tests**

```python
def _drain(h, timeout=5):
    deadline = time.monotonic() + timeout
    while not h.finished and time.monotonic() < deadline: time.sleep(0.01)
    return h.events_since(0)

def test_replays_sections_in_stage_order(tmp_path):
    path = make_run(tmp_path, "AAPL", "2026-11-06")   # from tests.webui_helpers
    evs = _drain(start_demo(path, delay=0))
    reports = [e.stage for e in evs if e.kind == "report"]
    assert reports == ["market", "news", "bull", "bear", "manager", "trader",
                       "aggressive", "conservative", "neutral", "portfolio"]
    assert evs[-1].kind == "done" and evs[-1].rating == "Hold"

def test_falls_back_to_sample_when_no_reports(tmp_path): ...  # reports_root empty → done.report_dir == str(SAMPLE_REPORT)
def test_sample_report_is_parseable(): ...  # list_runs(SAMPLE_REPORT.parent) includes it, skipped == 0
```

- [ ] **Step 2:** run → FAIL; **Step 3:** implement; **Step 4:** run → PASS
- [ ] **Step 5: Commit** `feat(webui): demo mode replays a saved report`

---

### Task 5: Live runner

**Files:**
- Create: `webui/runner.py`
- Test: `tests/test_webui_runner.py`

**Interfaces:**
- Consumes: Task 1–3 types.
- Produces:
  - `RunRequest` dataclass: `ticker: str`, `trade_date: str` (YYYY-MM-DD), `analysts: list[str]` (UI names), `provider: str`, `quick_model: str`, `deep_model: str`, `ollama_url: str`, `debate_rounds: int`, `risk_rounds: int`. `__post_init__` does `ticker = ticker.strip().upper()`.
  - `build_config(req: RunRequest) -> dict`: copy of `DEFAULT_CONFIG` with `llm_provider` = `req.provider`, `backend_url` = `req.ollama_url` for ollama or `https://api.openai.com/v1` for openai, `quick_think_llm`, `deep_think_llm`, `max_debate_rounds`, `max_risk_discuss_rounds`, `output_language="English"`, `checkpoint_enabled=False`; also clears any `quick_think_provider` / `deep_think_provider` / `*_backend_url` tier overrides to `None` so a `.env` override can't route a tier to OpenAI.
  - `graph_analysts(names: list[str]) -> list[str]`: `sentiment` → `social`, order kept.
  - `preflight(req: RunRequest, get=requests.get) -> str | None`: ollama → `get(f"{url}/models", timeout=3)`; `requests.ConnectionError`/`Timeout` → the Ollama-not-running copy; each of quick/deep model not in the returned `data[].id` → the model-not-installed copy for the first missing one. openai → `os.environ.get("OPENAI_API_KEY")` empty → the no-key copy. Otherwise `None`.
  - `state_to_events(state: dict, seen: dict[str, str]) -> list[RunEvent]`: for each stage, read its content (`market_report`, `sentiment_report`, `news_report`, `fundamentals_report`, `investment_debate_state.bull_history` / `.bear_history`, `investment_plan`, `trader_investment_plan`, `risk_debate_state.aggressive_history` / `.conservative_history` / `.neutral_history`, `final_trade_decision`); emit `RunEvent("report", stage=..., title=..., content=...)` when the stripped content is non-empty and differs from `seen[key]`, updating `seen`.
  - `start_run(req: RunRequest, graph_factory=None) -> RunHandle` (`graph_factory` defaults to `TradingAgentsGraph`, imported lazily). Registers the handle; daemon thread:
    1. `graph = graph_factory(selected_analysts=graph_analysts(req.analysts), config=build_config(req))`
    2. emit `stage/running` per analyst
    3. `state = graph.create_run_state(req.ticker, req.trade_date)`; `args = graph.propagator.get_graph_args()`
    4. `for _messages, chunk in graph.stream_run(state, **args)`: skip `None`; merge into `final_state` (the same `dict.update` merge as `cli/run.py:340-344`); emit `state_to_events`
    5. `graph.record_decision(req.ticker, req.trade_date, final_state)`; `path = graph.default_report_path(req.ticker)`; `graph.save_reports(final_state, req.ticker, path, html=True)`
    6. emit `done(rating=run_rating(final_state), report_dir=str(path))`
    Any exception → `RunEvent("error", content=f"The run stopped: {exc}", detail=traceback.format_exc())`.

- [ ] **Step 1: Write the failing tests**

```python
class FakeGraph:
    def __init__(self, selected_analysts, config, chunks=None, fail=False): ...
    def create_run_state(self, t, d): return {}
    propagator = SimpleNamespace(get_graph_args=lambda: {})
    def stream_run(self, state, **a): yield from self.chunks  # raise if fail
    def record_decision(self, *a): self.recorded = True
    def default_report_path(self, t): return self.tmp / f"{t}_x"
    def save_reports(self, fs, t, p, html=True): write_report_tree(fs, t, p, html=False)

def test_config_provider_is_explicit(monkeypatch):
    monkeypatch.setitem(DEFAULT_CONFIG, "llm_provider", "openai")
    monkeypatch.setitem(DEFAULT_CONFIG, "deep_think_provider", "openai")
    cfg = build_config(_req(provider="ollama"))
    assert cfg["llm_provider"] == "ollama" and cfg["deep_think_provider"] is None
    assert cfg["backend_url"] == "http://localhost:11434/v1"

def test_ticker_normalized(): assert RunRequest(" aapl ", ...).ticker == "AAPL"
def test_sentiment_maps_to_social(): assert graph_analysts(["market", "sentiment"]) == ["market", "social"]
def test_state_to_events_dedupes(): ...  # same state twice → events once; changed bull_history → one new bull event
def test_full_run_emits_reports_then_done(tmp_path): ...  # FakeGraph with 3 chunks → report events, done.rating == "Hold", saved folder exists, recorded
def test_exception_becomes_error_event(tmp_path): ...    # fail=True → last event kind "error", content startswith "The run stopped:"
def test_bad_ticker_becomes_error_event(tmp_path): ...    # FakeGraph.default_report_path raises ValueError for "../X" → error event, no crash
def test_preflight_ollama_down():
    def get(*a, **k): raise requests.ConnectionError()
    assert preflight(_req(), get=get) == "Ollama isn't running. Start it with `ollama serve`."
def test_preflight_model_missing(): ...  # data ids ["llama3.2:3b"] → "Model `qwen3:4b` isn't installed. Run `ollama pull qwen3:4b`."
def test_preflight_openai_no_key(monkeypatch): ...  # OPENAI_API_KEY="" → "No OpenAI key in `.env`."
```

- [ ] **Step 2:** run → FAIL; **Step 3:** implement; **Step 4:** run → PASS
- [ ] **Step 5: Commit** `feat(webui): background runner over stream_run`

---

### Task 6: App shell, launcher, sidebar, Settings page

**Files:**
- Create: `webui/app.py`, `webui/launch.py`, `webui/ui_common.py`, `webui/pages/settings.py`, placeholder `home.py`, `new_run.py`, `history.py` (title only)
- Test: `tests/test_webui_pages.py`

**Interfaces:**
- Consumes: `load_prefs`, `save_prefs`, `active_run`.
- Produces:
  - `ui_common.sidebar_status(prefs: UIPrefs) -> None`: shows `Mode: Demo` or `Mode: Live`, `LLM: Ollama · qwen3:4b` or `LLM: OpenAI · <model> (paid)`, and `Run in progress: <label>` when `active_run()` is unfinished.
  - `ui_common.rating_badge(rating: str) -> str`: markdown badge; green for Buy/Overweight, gray for Hold and `—`, red for Underweight/Sell.
  - `launch.main()`: `sys.argv = ["streamlit", "run", str(Path(__file__).with_name("app.py"))]` then `streamlit.web.cli.main()`.
  - `app.py`: `st.set_page_config(page_title="TradingAgents", layout="wide")`, `st.navigation([...4 pages...])`, prefs loaded into `st.session_state["prefs"]` once, `sidebar_status`.
  - Settings page: provider radio (Ollama / OpenAI), model text inputs, Ollama URL, "Check Ollama" button (lists `/models` ids or shows the not-running copy, reusing the `preflight` request code), key status lines `OpenAI key: set` / `missing` and `FRED key: set` / `missing` (from `os.environ`, never the value), demo-mode toggle, Save button → `save_prefs`.

- [ ] **Step 1: Write the failing tests** (`pytest.importorskip("streamlit")`; monkeypatch `webui.prefs.PREFS_PATH` and `DEFAULT_CONFIG["results_dir"]` to tmp)

```python
def test_app_renders_without_error(): at = AppTest.from_file("webui/app.py").run(); assert not at.exception
def test_settings_shows_key_status_not_value(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret123")
    at = AppTest.from_file("webui/pages/settings.py").run()
    text = " ".join(m.value for m in at.markdown)
    assert "OpenAI key: set" in text and "sk-secret123" not in text
def test_rating_badge_colors(): ...  # "Buy" contains green, "Sell" red, "—" gray
```

- [ ] **Step 2:** run → FAIL; **Step 3:** implement; **Step 4:** run → PASS
- [ ] **Step 5: Manual:** `tradingagents-ui` opens `localhost:8501`, all four pages navigable, Settings save persists across restart.
- [ ] **Step 6: Commit** `feat(webui): app shell, launcher and settings`

---

### Task 7: New run page with live progress, and Home

**Files:**
- Modify: `webui/pages/new_run.py`, `webui/pages/home.py`, `webui/ui_common.py`
- Test: `tests/test_webui_pages.py` (append)

**Interfaces:**
- Consumes: `RunRequest`, `preflight`, `start_run` (Task 5); `start_demo` (Task 4); `active_run` (Task 2); `list_runs` (Task 3); `GROUPS`, `STAGES`.
- Produces: `ui_common.render_progress(handle: RunHandle) -> None`, decorated `@st.fragment(run_every=1)`. It reads all events; it shows the pipeline (one chip per group: done if any report in the group arrived and a later group has started or the run finished; running = the first not-done group; analysts shown as individual chips), elapsed seconds, one expander per report event (title, markdown), and on `done` the rating badge, the portfolio report, and a button that sets `st.session_state["open_report"] = report_dir` and `st.switch_page("pages/history.py")`. On `error` it shows `st.error(content)`, the traceback in an expander, and "Back to form" (clears the active run). It stops re-running once `handle.finished` (call `st.rerun()` once to leave fragment mode).

**New run form:** ticker text input; `st.date_input` with `max_value=date.today()` (Review Focus 4); analyst checkboxes (defaults from prefs); provider/model/round fields prefilled from prefs; summary line `Ollama — free` or `OpenAI — paid`. If provider is openai and demo mode is off, a checkbox `I understand this run uses paid API credits` must be ticked (Review Focus 5). Run is disabled when: no ticker, no analyst, a paid confirmation is required but unticked, or `active_run()` exists and is unfinished (Review Focus 2). On Run: demo mode → `start_demo()`; else `preflight` → show the message and stop on error, otherwise `start_run`. While a run is active (including after refresh or from a second tab), the page shows `render_progress(active_run())` instead of the form.

**Home:** quick-run form (ticker + date, uses prefs for everything else, same disabled rules, starts via the same helper and then `st.switch_page("pages/new_run.py")`); "Recent decisions": the 10 newest `list_runs` entries with `rating_badge`, each with an "Open" button that sets `open_report` and switches to History.

- [ ] **Step 1: Write the failing tests**

```python
def test_run_disabled_without_analysts(): ...   # uncheck all analyst boxes → Run button disabled
def test_paid_requires_confirmation(): ...      # prefs provider=openai, demo_mode=False → Run disabled until checkbox ticked
def test_demo_run_shows_progress(tmp_path): ... # demo on, click Run, at.run() a few times → an expander titled "Portfolio Manager" appears; no exception
def test_active_run_shown_after_refresh(): ...  # set_active_run(unfinished handle); fresh AppTest of new_run.py shows progress, not the form
def test_home_lists_recent(tmp_path): ...       # two fixture runs in tmp reports dir → both tickers in the page text
```

- [ ] **Step 2:** run → FAIL; **Step 3:** implement; **Step 4:** run → PASS
- [ ] **Step 5: Manual (demo mode):** run from Home and New run; refresh mid-run; open a second tab mid-run; Run stays disabled until the run finishes.
- [ ] **Step 6: Commit** `feat(webui): new-run page with live progress, and home`

---

### Task 8: History page with compare

**Files:**
- Modify: `webui/pages/history.py`
- Test: `tests/test_webui_pages.py` (append)

**Interfaces:**
- Consumes: `list_runs`, `filter_runs`, `load_run` (Task 3); `rating_badge`; `st.session_state["open_report"]` (set by Task 7).
- Produces: the page only.

**Behavior:** filters (ticker multiselect, date range, rating multiselect) above a `st.dataframe` with `on_select="rerun", selection_mode="multi-row"`: ticker, analysis date, rating, models, generated. `Skipped N unreadable folders` in caption text when N > 0. One row selected (or `open_report` set) → a report view with tabs `Analysts | Research | Trader | Risk | Decision` that render each stage's markdown under its title, plus the file path of `complete_report.html` and a download button for it. Two or three rows selected → compare: one column per run with the header fields, rating badge, and the `portfolio` section; under each, expanders "Trader plan" and "Research Manager". More than three selected → `st.warning("Select up to 3 runs to compare.")`.

- [ ] **Step 1: Write the failing tests**

```python
def test_history_lists_runs(tmp_path): ...       # 3 fixture runs → 3 table rows
def test_open_report_shows_tabs(tmp_path): ...    # session_state open_report = path → tabs labelled as above, "Decision" content present
def test_compare_two(tmp_path): ...               # select 2 rows → 2 columns each containing its ticker
def test_compare_four_warns(tmp_path): ...        # select 4 → warning text
def test_skipped_caption(tmp_path): ...           # add a broken folder → caption mentions "Skipped 1"
```

- [ ] **Step 2:** run → FAIL; **Step 3:** implement; **Step 4:** run → PASS
- [ ] **Step 5: Manual:** the existing `AAPL_20261109_113102` OpenAI run appears; compare it with a demo-generated and an Ollama run.
- [ ] **Step 6: Commit** `feat(webui): history browser with side-by-side compare`

---

### Task 9: Docs, full check, real Ollama run

**Files:**
- Modify: `CHANGELOG.md` (Unreleased → Added: web UI, `[ui]` extra, `tradingagents-ui`), `README.md` (short "Web UI" section: `pip install -e ".[ui]"`, `tradingagents-ui`, demo mode, Ollama default)

- [ ] **Step 1:** `pytest -q` → all pass; `TZ=America/New_York pytest -q` → all pass; `ruff check .` → clean
- [ ] **Step 2:** Bare-install check: in a throwaway venv, `pip install .` then `python -c "import tradingagents, cli.main"` → OK (Streamlit absent)
- [ ] **Step 3: Real Ollama run** (Ollama running, demo mode off): AAPL, latest weekday, analysts = market only, 1/1 rounds, `qwen3:4b` both tiers. Expected: progress through all groups, `done` with a rating, new folder in History. If `qwen3:4b` can't finish (tool-call or structured-output failure), retry with `llama3.2:3b`; if both fail, **stop and ask the user** before using OpenAI.
- [ ] **Step 4: Commit** `docs: web UI in README and changelog`
