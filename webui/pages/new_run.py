"""Pick a stock and settings, start a run, and watch the agents work."""

from datetime import date

import streamlit as st

from webui.events import active_run
from webui.runner import RunRequest, analysts_for, asset_type
from webui.stages import ANALYSTS, STAGE_BY_KEY
from webui.ui_common import (
    advanced_inputs,
    cost_notice,
    get_prefs,
    llm_inputs,
    other_job_notice,
    portfolio_choice,
    render_progress,
    run_blocked,
    start,
)

st.title("New run")
prefs = get_prefs()
handle = active_run()

if other_job_notice(("analysis", "demo")):
    st.stop()
if handle is not None and handle.kind in ("analysis", "demo"):
    render_progress(handle)
    st.stop()

ticker = st.text_input("Ticker", key="run_ticker", placeholder="e.g. AAPL, NVDA, 0700.HK")
day = st.date_input("Analysis date", value=date.today(), max_value=date.today(), key="run_date")

st.markdown("**Analysts**")
cols = st.columns(len(ANALYSTS))
analysts = [name for col, name in zip(cols, ANALYSTS, strict=True)
            if col.checkbox(STAGE_BY_KEY[name].title, value=name in prefs.analysts,
                            key=f"analyst_{name}")]

crypto = bool(ticker.strip()) and asset_type(ticker) == "crypto"
if crypto:
    st.caption("A crypto ticker: the Fundamentals analyst doesn't apply to a coin and sits this run out.")
runnable = analysts_for(analysts, "crypto" if crypto else "stock")

choice = llm_inputs(prefs, "run_")
c3, c4 = st.columns(2)
debate = c3.number_input("Debate rounds", 1, 5, prefs.debate_rounds, key="run_debate")
risk = c4.number_input("Risk rounds", 1, 5, prefs.risk_rounds, key="run_risk")

book = portfolio_choice("run_portfolio")
advanced = advanced_inputs(prefs, "run_", choice)

paid = cost_notice(choice, prefs.demo_mode)
paid_ok = st.checkbox("I understand this run uses paid API credits", key="paid_ok") if paid else True

disabled = not ticker.strip() or not runnable or not paid_ok or run_blocked()
if st.button("Run", key="run", type="primary", disabled=disabled):
    req = RunRequest(ticker=ticker, trade_date=day.isoformat(), analysts=analysts,
                     **choice.request_fields(prefs.ollama_url), **advanced,
                     data_vendors=prefs.data_vendors,
                     debate_rounds=int(debate), risk_rounds=int(risk),
                     portfolio=book, checkpoint=prefs.checkpoint)
    problem = start(req, prefs.demo_mode)
    if problem:
        st.error(problem)
    else:
        st.rerun()
