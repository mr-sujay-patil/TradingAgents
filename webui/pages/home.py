"""Start a run with your defaults, or open a recent decision."""

from datetime import date

import streamlit as st

from webui import history, portfolio_store, providers
from webui.prefs import run_settings
from webui.runner import RunRequest
from webui.ui_common import get_prefs, rating_badge, run_blocked, start

st.title("TradingAgents")
prefs = get_prefs()
left, right = st.columns(2)

with left:
    st.subheader("Quick run")
    ticker = st.text_input("Ticker", key="q_ticker", placeholder="e.g. AAPL")
    day = st.date_input("Analysis date", value=date.today(), max_value=date.today(), key="q_date")
    paid = providers.run_paid(prefs.provider, prefs.deep_provider) and not prefs.demo_mode
    book = portfolio_store.load()
    note = "Uses your defaults from Settings"
    note += f" and your portfolio ({portfolio_store.describe(book)})." if book else "."
    if paid:
        note += " A paid provider; use New run to confirm."
    st.caption(note)
    if st.button("Run with defaults", key="q_run", type="primary",
                 disabled=not ticker.strip() or not prefs.analysts or paid or run_blocked()):
        req = RunRequest(ticker=ticker, trade_date=day.isoformat(), analysts=prefs.analysts,
                         provider=prefs.provider, quick_model=prefs.quick_model,
                         deep_model=prefs.deep_model, ollama_url=prefs.ollama_url,
                         backend_url=prefs.backend_url, **run_settings(prefs),
                         debate_rounds=prefs.debate_rounds, risk_rounds=prefs.risk_rounds,
                         portfolio=book, checkpoint=prefs.checkpoint)
        problem = start(req, prefs.demo_mode)
        if problem:
            st.error(problem)
        else:
            st.switch_page("pages/new_run.py")

with right:
    st.subheader("Recent decisions")
    runs, _ = history.list_runs(history.reports_dir())
    if not runs:
        st.caption("No saved runs yet.")
    for i, run in enumerate(runs[:10]):
        a, b = st.columns([4, 1])
        a.markdown(f"**{run.ticker}** · {run.analysis_date} · {rating_badge(run.rating)}")
        if b.button("Open", key=f"open_{i}"):
            st.session_state["open_report"] = str(run.path)
            st.switch_page("pages/history.py")
