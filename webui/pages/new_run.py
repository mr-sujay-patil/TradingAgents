"""Pick a stock and settings, start a run, and watch the agents work."""

from datetime import date

import streamlit as st

from webui.events import active_run
from webui.runner import RunRequest
from webui.stages import ANALYSTS, STAGE_BY_KEY
from webui.ui_common import get_prefs, render_progress, run_blocked, start

st.title("New run")
prefs = get_prefs()
handle = active_run()

if handle is not None:
    render_progress(handle)
    st.stop()

ticker = st.text_input("Ticker", key="run_ticker", placeholder="e.g. AAPL, NVDA, 0700.HK")
day = st.date_input("Analysis date", value=date.today(), max_value=date.today(), key="run_date")

st.markdown("**Analysts**")
cols = st.columns(len(ANALYSTS))
analysts = [name for col, name in zip(cols, ANALYSTS, strict=True)
            if col.checkbox(STAGE_BY_KEY[name].title, value=name in prefs.analysts,
                            key=f"analyst_{name}")]

PROVIDERS = {"Ollama": "ollama", "OpenAI": "openai"}
label = st.radio("Provider", list(PROVIDERS), horizontal=True, key="run_provider",
                 index=list(PROVIDERS.values()).index(prefs.provider)
                 if prefs.provider in PROVIDERS.values() else 0)
provider = PROVIDERS[label]
c1, c2 = st.columns(2)
quick = c1.text_input("Quick-thinking model", prefs.quick_model, key="run_quick")
deep = c2.text_input("Deep-thinking model", prefs.deep_model, key="run_deep")
c3, c4 = st.columns(2)
debate = c3.number_input("Debate rounds", 1, 5, prefs.debate_rounds, key="run_debate")
risk = c4.number_input("Risk rounds", 1, 5, prefs.risk_rounds, key="run_risk")

paid = provider == "openai" and not prefs.demo_mode
if prefs.demo_mode:
    st.info("Demo mode — replays a saved run. Free; no model is called. Turn it off in Settings.")
elif paid:
    st.warning("OpenAI — paid.")
else:
    st.info("Ollama — free.")
paid_ok = st.checkbox("I understand this run uses paid API credits", key="paid_ok") if paid else True

disabled = not ticker.strip() or not analysts or not paid_ok or run_blocked()
if st.button("Run", key="run", type="primary", disabled=disabled):
    req = RunRequest(ticker=ticker, trade_date=day.isoformat(), analysts=analysts,
                     provider=provider, quick_model=quick.strip(), deep_model=deep.strip(),
                     ollama_url=prefs.ollama_url, debate_rounds=int(debate), risk_rounds=int(risk))
    problem = start(req, prefs.demo_mode)
    if problem:
        st.error(problem)
    else:
        st.rerun()
