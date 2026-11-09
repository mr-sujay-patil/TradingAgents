# TradingAgents Web UI — Design

Date: 2026-11-09
Status: Draft, awaiting review

## 1. Goal

A simple local web UI over TradingAgents for a single user on their own Mac.
It covers the two things the user does equally often: running new analyses
and reviewing / comparing past decisions. It replaces typing CLI flags and
digging through `~/.tradingagents/logs/reports/` by hand.

**Success criteria**

- Start a run from the browser and watch each agent's progress live.
- Every past run (from the UI *or* the CLI) is listed, readable, and filterable.
- Two or three runs can be compared side by side.
- The whole UI can be developed and tested at zero LLM cost (demo mode + Ollama).
- No OpenAI call is ever made unless OpenAI is explicitly selected.

**Non-goals (v1)**

- Multi-user access, login, hosting on the internet.
- Backtest grids, memory-log settlement / outcome views, portfolio context,
  checkpoint resume, ChatGPT subscription login, output-language choice.
  These stay CLI-only for now.
- Any change to the trading engine in `tradingagents/`.

## 2. Technology

- **Streamlit** (pure Python, runs at `http://localhost:8501`).
- Shipped as an optional extra so the core install is unchanged:
  `pip install -e ".[ui]"`. CI's bare-install check (`import tradingagents`,
  `import cli.main`) is unaffected because nothing in those packages imports
  Streamlit.
- New console script `tradingagents-ui` that launches `streamlit run` on the
  app file.
- `webui*` added to `[tool.setuptools.packages.find] include`.

## 3. Screens

A sidebar with four pages, plus a status block that always shows the active
mode (Demo / Live) and LLM provider so a paid run is never a surprise.

### 3.1 Home
- **Quick run:** ticker + date, "Run with defaults" (uses Settings defaults).
- **Recent decisions:** the 5–10 newest runs with a colored rating badge;
  clicking one opens its report on the History page.

### 3.2 New run
- **Form:** ticker, analysis date, analysts (market / sentiment / news /
  fundamentals checkboxes), provider, quick model, deep model, research depth
  (debate rounds and risk rounds).
- **Pre-run summary:** provider, models, analysts, rounds, and a cost note
  ("Ollama — free" / "OpenAI — paid"). For a paid provider the user must tick a
  confirmation box before Run is enabled.
- **Live progress** replaces the form once running:
  - Pipeline: Analysts (one chip per selected analyst) → Bull/Bear debate →
    Research Manager → Trader → Risk debate → Portfolio Manager, each
    pending / running / done.
  - Elapsed time.
  - Each agent's report appears in an expander as soon as it is filed.
  - On finish: the rating badge, the Portfolio Manager's decision, and a link
    to the saved report in History.
  - On failure: a readable error message (see §6) and a "Back to form" button.

### 3.3 History
- **Table** of all saved runs: ticker, analysis date, rating, provider/models,
  generated time. Filters: ticker (multi-select), analysis-date range, rating.
- **Report view:** click a row → tabs Analysts / Research / Trader / Risk /
  Decision, rendering the saved markdown. Link to open `complete_report.html`.
- **Compare:** select 2–3 rows → side-by-side columns showing header (ticker,
  date, rating, models) and the Portfolio Manager decision, with an expander
  per column for the Trader plan and Research Manager decision.

### 3.4 Settings
- Default provider (Ollama / OpenAI) and default quick/deep models.
- Ollama base URL (default `http://localhost:11434/v1`) and a "Check Ollama"
  button that lists locally pulled models.
- API-key status for OpenAI and FRED: set / missing only. Key values are never
  displayed or written by the UI; the user edits `.env` themselves.
- Demo mode toggle.
- Settings persist to `~/.tradingagents/webui_prefs.json`. Defaults on first
  launch: provider **Ollama**, quick and deep model **`qwen3:4b`**, analysts
  market + news + fundamentals, 1 debate round, 1 risk round, demo mode on.

## 4. Architecture

```
webui/
  __init__.py
  app.py        entry point: page config, sidebar, navigation
  pages/        home.py, new_run.py, history.py, settings.py
  runner.py     background run + event stream
  demo.py       replays a saved report as events
  history.py    reads saved report folders
  prefs.py      load/save webui_prefs.json
  launch.py     `tradingagents-ui` console-script target
```

Each module has one job and no Streamlit import except `app.py` and `pages/`,
so `runner`, `demo`, `history` and `prefs` are unit-testable without a browser.

### 4.1 Events

The single interface between "something producing progress" and the screen:

```python
@dataclass
class RunEvent:
    kind: Literal["stage", "report", "done", "error"]
    stage: str | None = None     # e.g. "market", "bull", "trader", "portfolio"
    status: str | None = None    # "running" | "done"
    title: str | None = None     # e.g. "Market Analyst"
    content: str | None = None   # markdown report or error text
    report_dir: str | None = None  # on "done"
    rating: str | None = None      # on "done"
```

### 4.2 Runner (`runner.py`)

- `start_run(settings) -> RunHandle`. Builds a config from `DEFAULT_CONFIG`,
  then **explicitly** sets `llm_provider`, `backend_url`, `quick_think_llm`,
  `deep_think_llm`, round counts and analysts from the UI settings. Provider
  is never left to auto-detection, so the OpenAI key in `.env` cannot be used
  by accident.
- Runs `TradingAgentsGraph.stream_run()` in a daemon `threading.Thread`,
  mapping each `(messages, state)` pair to `RunEvent`s (same state keys the
  CLI reads in `cli/run.py`: `*_report`, `investment_debate_state`,
  `investment_plan`, `trader_investment_plan`, `risk_debate_state`,
  `final_trade_decision`).
- Events go into a thread-safe list on the `RunHandle`; the page reads new
  events by index.
- On completion, saves the report with `tradingagents.reporting.write_report_tree`
  into the same results directory and folder naming the CLI uses, and records
  the decision with `graph.record_decision(...)` as `cli/run.py` does, so UI runs and CLI
  runs are indistinguishable in History.
- The `RunHandle` lives in a process-wide registry (`st.cache_resource`), so
  navigating away or refreshing the page does not stop or lose the run.
  Only one run at a time: Run is disabled while a handle is active.

### 4.3 Demo mode (`demo.py`)

- `start_demo(report_dir) -> RunHandle` with the same interface as the runner.
- Reads a saved report folder (default: the newest one) and emits the same
  sequence of `RunEvent`s with short delays (≈1 s per stage), then `done`.
- No LLM, no network. Used for most UI development and testing.
- If no saved report exists, demo uses a small bundled sample report under
  `webui/sample_report/`.

### 4.4 History (`history.py`)

- `list_runs(results_dir) -> list[RunSummary]`: scans
  `<results_dir>/reports/*/complete_report.md` and parses the header lines
  written by `reporting._header` (ticker from the title; `Analysis date`,
  `Rating`, `Generated`, models line, analysts line).
- `load_run(path) -> RunDetail`: reads the section files
  (`1_analysts/*.md` … `5_portfolio/decision.md`).
- Folders with a missing or malformed `complete_report.md` are skipped, not
  fatal; the count of skipped folders is shown in small text.
- Cached by folder modification time so the table stays fast.

### 4.5 Page refresh

The live-progress area is a Streamlit fragment that re-runs every second
while a run is active, drawing events it hasn't drawn yet. It stops refreshing
when a `done` or `error` event arrives.

## 5. Data flow

```
Form ──► runner.start_run ──► thread: graph.stream_run ──► RunEvents ──► progress fragment
                                         │
                                         └─► write_report_tree ──► reports/  ◄── history.list_runs ◄── History / Home
Demo toggle ──► demo.start_demo ──► RunEvents (same path)
```

## 6. Error handling

Errors become an `error` event with a plain-language message; the raw
traceback goes into an expander.

| Situation | Message |
|---|---|
| Ollama not reachable | "Ollama isn't running. Start it with `ollama serve`." |
| Model not pulled | "Model `X` isn't installed. Run `ollama pull X`." |
| OpenAI key missing | "No OpenAI key in `.env`." |
| Invalid ticker / no market data | The router's `NO_DATA_AVAILABLE` text, shown as is. |
| Anything else | "The run stopped: <exception message>." |

Ollama reachability and the model's presence are checked **before** starting
the thread, so the common failures appear instantly instead of minutes in.

## 7. Testing

**Automated (pytest, no network, no LLM)** in `tests/test_webui_*.py`,
skipped via `pytest.importorskip("streamlit")` only where Streamlit is needed:

- `history`: parses a fixture report folder; skips malformed folders; filters.
- `demo`: replays a fixture folder into the expected event sequence.
- `runner`: with a stubbed graph whose `stream_run` yields canned
  `(messages, state)` pairs, produces the expected events; config always has
  an explicit `llm_provider`; an exception becomes an `error` event.
- `prefs`: round-trips the JSON; missing file gives the documented defaults.
- Tests must pass under `TZ=America/New_York` (CI runs it).

**Manual**

1. Demo mode end to end in the browser (all four pages, compare view).
2. One real run on Ollama `qwen3:4b`, single analyst, 1/1 rounds.
3. OpenAI only when the user explicitly asks for it.

## 8. Housekeeping

- `CHANGELOG.md` "Added" entry for the web UI and the `[ui]` extra.
- README short section: install the extra, run `tradingagents-ui`.
- `ruff check .` clean.

## 9. Open questions

None at this time.
