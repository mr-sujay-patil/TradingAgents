# TradingAgents Web UI v2 — Design

Builds on `2026-11-09-streamlit-web-ui-design.md` (v1). v1 left four engine
features CLI-only; v2 brings them into the UI. The engine (`tradingagents/`)
and `cli/` stay untouched.

## 1. Goals

1. **Portfolio context** — keep a standing book (holdings, cash, currency) in
   the UI and feed it to live runs and backtests, so the decision agents know
   what is already held.
2. **Checkpoint resume** — a live run that stops part-way can be resumed from
   its last finished step instead of starting over.
3. **Outcome tracking** — see how past decisions actually did: realized return
   and alpha vs the benchmark, hit rate by rating, and settle due decisions on
   demand.
4. **Backtest** — run a ticker × date grid from the UI, watch it progress,
   continue an earlier sweep, and read each sweep's scores.

**Non-goals:** a portfolio simulator (the engine forbids one in
`backtest.py`), editing the memory log, ChatGPT login, output-language choice,
multi-user hosting.

## 2. Portfolio context

- Stored at `~/.tradingagents/webui_portfolio.json` in exactly the
  `PortfolioContext` JSON shape (`cash`, `currency`, `positions[ticker,
  quantity, average_price]`), so the same file also works with the CLI's
  `--portfolio`.
- **Settings → Portfolio:** an editable table of positions, cash and currency
  inputs, Save (validated with `PortfolioContext.model_validate`; a bad row
  shows the validation error and nothing is saved), Clear, and an Import JSON
  uploader.
- **New run / Backtest:** a "Use my portfolio" checkbox, shown only when a
  portfolio is saved, defaulting to on. Off means *no context* (not a flat
  book), matching the engine's three-state rule.
- Home quick run uses the saved portfolio when one exists.

## 3. Checkpoint resume

- New pref `checkpoint` (default **on**). The live runner calls
  `begin_checkpoint` → injects the thread id → streams
  `graph.checkpoint_input(state)` → `clear_checkpoint_on_success` →
  `end_checkpoint` in `finally`, as `cli/run.py` does.
- When the engine reports it is resuming, the run shows
  "Resuming from the last saved step."
- On an error, the progress view offers **Resume** (same request again: the
  checkpoint picks up where it stopped) next to "Back to form". The handle
  keeps its `RunRequest` so Resume works after a refresh too.
- The checkpoint signature includes provider/models/analysts/rounds/portfolio,
  so changing any of them starts fresh; that is engine behavior and is stated
  in the Resume help text.

## 4. Outcome tracking

- **Outcomes page** reads the live memory log
  (`DEFAULT_CONFIG["memory_log_path"]`): one row per decision — date, ticker,
  rating, status (Pending / Settled / Unscored), return, alpha, holding window,
  resolved date. Filters by ticker and status.
- Score tiles from `tradingagents.backtest.summarize(log_path)`: resolved,
  pending, and per rating `n`, hit rate, mean alpha. Selecting a settled row
  shows its reflection.
- **Settle due decisions now** runs `graph.settle_all_pending()` on a
  background thread through the same active-run registry (one job at a time).
  It fetches prices and asks the chosen model for one reflection per decision,
  so: disabled in demo mode; with OpenAI it needs the paid-credits checkbox;
  preflight (Ollama up, model pulled, key present) runs first.
- **History** gains an *Outcome* column (alpha, or "pending") joined on
  (ticker, analysis date) from the same log.

## 5. Backtest

- **Backtest page** form: tickers (comma-separated), start and end dates (max
  today), every N days, analysts, provider/models from prefs, "Use my
  portfolio", and "Continue sweep" (pick an existing run id; its finished cells
  are skipped). A live line shows the cell count:
  `N tickers × M dates = K runs`.
- Disabled in demo mode. OpenAI needs the paid-credits checkbox. Preflight
  first. Hard cap of 60 cells per sweep from the UI (the CLI has none) so a
  typo can't queue hundreds of runs.
- Runs `run_backtest` on a background thread, with its `progress` callback
  emitting `progress` events (`done`/`total`, current ticker and date).
  The page shows a progress bar, the current cell, elapsed time, and failures
  as they are known. On `done`: the summary table, failures, unsettled cells,
  and the run id.
- **Past sweeps:** every folder under `<results_dir>/backtest/` with a
  `trading_memory.md`, newest first, each expandable to its summary and cells.
- While a backtest runs, New run and Outcomes show it in the sidebar and stay
  disabled (one job at a time, shared registry).

## 6. Shared mechanics

- `RunHandle` gains `kind` (`analysis`, `demo`, `settle`, `backtest`) and an
  optional `request`. `RunEvent` gains kind `progress` with `done`/`total`.
- Pages that start jobs check `run_blocked()`; each page renders progress only
  for its own job kind and otherwise links to the page that owns the job.
- All new non-UI modules (`portfolio_store`, `outcomes`, `backtest_runner`)
  are pure Python, unit-tested with fakes; no network in tests.

## 7. Review focus

1. Portfolio toggle off → `portfolio=None` reaches the engine (not an empty
   book); invalid holdings never get saved.
2. A failed live run → Resume restarts with checkpointing on and the same
   request; a successful run clears its checkpoint.
3. Outcomes with no log, an empty log, or only pending entries → no crash,
   clear empty states.
4. Backtest grid over 60 cells, end before start, or zero tickers → Run
   disabled with the reason shown; per-cell failures don't end the sweep.
5. Demo mode → Backtest and Settle disabled; no network or model call.

## 8. Open questions

None.
