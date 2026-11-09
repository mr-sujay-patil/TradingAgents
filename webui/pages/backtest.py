"""Run the agents over a grid of tickers and past dates, and score the calls they made."""

import time
from datetime import date, timedelta

import streamlit as st

from webui import backtest_runner as br
from webui.events import active_run, set_active_run
from webui.runner import preflight
from webui.stages import ANALYSTS, STAGE_BY_KEY
from webui.ui_common import get_prefs, other_job_notice, portfolio_choice, run_blocked

st.title("Backtest")
st.caption("Each cell is a full analysis on a past date, scored later against the benchmark over "
           "the holding window. This measures decision quality; it is not a portfolio simulator. "
           "Sweeps keep their own memory log, so your live Outcomes are untouched.")
prefs = get_prefs()


def _scores_table(summary):
    if not summary.by_rating:
        st.caption("Nothing settled yet — cells settle once their holding window has traded.")
        return
    st.dataframe(
        [{"Rating": rating, "Settled": s.count,
          "Called the direction": f"{s.hit_rate:.0%}" if s.hit_rate is not None else "n/a (no direction)",
          "Mean alpha": f"{s.mean_alpha:+.2%}"} for rating, s in summary.by_rating.items()],
        hide_index=True,
    )
    st.caption(f"Settled {summary.resolved} · pending {summary.pending}"
               + (f" · unscored {summary.unscored}" if summary.unscored else ""))


def _issues(events):
    for e in events:
        if e.kind == "report" and e.stage == "failed":
            st.warning(f"Failed {e.title}: {e.content}")
        elif e.kind == "report" and e.stage == "unsettled":
            st.caption(f"Unsettled {e.title}: {e.content}")


@st.fragment(run_every=1)
def _live(handle):
    events = handle.events_since(0)
    if handle.finished:
        st.rerun()
    progress = [e for e in events if e.kind == "progress"]
    last = progress[-1] if progress else None
    st.markdown(f"**{handle.label}**")
    if last is not None:
        st.progress(last.done / last.total if last.total else 0.0,
                    text=f"Run {last.done + 1} of {last.total}: {last.content}")
    else:
        st.progress(0.0, text="Starting…")
    st.caption(f"Elapsed: {int(time.monotonic() - handle.started_at)} s")
    _issues(events)


def _finished(handle):
    events = handle.events_since(0)
    last = events[-1]
    st.markdown(f"**{handle.label}**")
    if last.kind == "error":
        st.error(last.content)
        if last.detail:
            with st.expander("Details"):
                st.code(last.detail)
    else:
        st.success(f"Sweep {last.title} finished.")
        st.text(last.content)
        st.caption(f"Log: {last.report_dir} — continue or settle it later with run id {last.title}.")
    _issues(events)
    if st.button("New backtest", key="bt_dismiss"):
        set_active_run(None)
        st.rerun()


handle = active_run()
if other_job_notice(("backtest",)):
    st.stop()
if handle is not None and handle.kind == "backtest":
    if handle.finished:
        _finished(handle)
    else:
        _live(handle)
    st.stop()

if prefs.demo_mode:
    st.warning("Backtests run real analyses, so they are off in demo mode. Turn demo mode off in Settings.")

sweeps = br.past_sweeps()
tickers_text = st.text_input("Tickers (comma-separated)", key="bt_tickers", placeholder="e.g. AAPL, NVDA")
today = date.today()
c1, c2, c3 = st.columns(3)
start = c1.date_input("First date", value=today - timedelta(days=56), max_value=today, key="bt_start")
end = c2.date_input("Last date", value=today - timedelta(days=7), max_value=today, key="bt_end")
every = c3.number_input("Every N days", 1, 90, 7, key="bt_every")

st.markdown("**Analysts**")
cols = st.columns(len(ANALYSTS))
analysts = [name for col, name in zip(cols, ANALYSTS, strict=True)
            if col.checkbox(STAGE_BY_KEY[name].title, value=name in prefs.analysts, key=f"bt_{name}")]
book = portfolio_choice("bt_portfolio")
if book is not None:
    st.caption("The same book is used for every cell; positions are not carried forward.")
continue_id = st.selectbox("Continue an earlier sweep (its finished cells are skipped)",
                           [s.run_id for s in sweeps], index=None, key="bt_continue",
                           placeholder="Start a new sweep")

req = br.BacktestRequest(tickers=br.parse_tickers(tickers_text), start=start.isoformat(), end=end.isoformat(),
                         every=int(every), analysts=analysts, provider=prefs.provider,
                         quick_model=prefs.quick_model, deep_model=prefs.deep_model,
                         ollama_url=prefs.ollama_url, debate_rounds=prefs.debate_rounds,
                         risk_rounds=prefs.risk_rounds, portfolio=book, run_id=continue_id)
dates, cells, problem = br.plan_cells(req)
paid = prefs.provider == "openai"
if req.tickers and not problem:
    st.info(f"{len(req.tickers)} ticker{'s' if len(req.tickers) != 1 else ''} × {len(dates)} "
            f"date{'s' if len(dates) != 1 else ''} = **{cells} runs** on "
            f"{'OpenAI (paid)' if paid else 'Ollama (free)'} · {prefs.deep_model}.")
elif problem and (req.tickers or tickers_text.strip()):
    st.error(problem)
paid_ok = st.checkbox("I understand every run uses paid API credits", key="bt_paid") if paid else True

if st.button("Run backtest", key="bt_run", type="primary",
             disabled=prefs.demo_mode or problem is not None or not paid_ok or run_blocked()):
    reason = preflight(req.run_request())
    if reason:
        st.error(reason)
    else:
        br.start_backtest(req)
        st.rerun()

st.divider()
st.subheader("Past sweeps")
if not sweeps:
    st.caption("No sweeps yet.")
for sweep in sweeps:
    with st.expander(f"{sweep.run_id} · {', '.join(sweep.tickers) or '—'} · {sweep.cells} cells"):
        _scores_table(sweep.summary)
        st.dataframe(
            [{"Date": e["date"], "Ticker": e["ticker"], "Rating": e["rating"],
              "Return": e.get("raw") or "pending", "Alpha": e.get("alpha") or ""} for e in sweep.entries],
            hide_index=True,
        )
