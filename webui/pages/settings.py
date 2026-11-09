"""Defaults for new runs, Ollama status, and which API keys are set (never their values)."""

import os

import requests
import streamlit as st

from webui import portfolio_store
from webui.prefs import save_prefs
from webui.runner import OLLAMA_DOWN, ollama_models
from webui.ui_common import get_prefs

st.title("Settings")
prefs = get_prefs()

PROVIDERS = {"Ollama": "ollama", "OpenAI": "openai"}
label = st.radio("Default provider", list(PROVIDERS), key="provider", horizontal=True,
                 index=list(PROVIDERS.values()).index(prefs.provider)
                 if prefs.provider in PROVIDERS.values() else 0)
if PROVIDERS[label] == "openai":
    st.caption("OpenAI runs use paid API credits.")
quick = st.text_input("Quick-thinking model", prefs.quick_model, key="quick_model")
deep = st.text_input("Deep-thinking model", prefs.deep_model, key="deep_model")
url = st.text_input("Ollama URL", prefs.ollama_url, key="ollama_url")

if st.button("Check Ollama", key="check_ollama"):
    try:
        models = ollama_models(url)
        st.success("Ollama is running. Installed models: " + (", ".join(models) or "none"))
    except (requests.ConnectionError, requests.Timeout):
        st.error(OLLAMA_DOWN)
    except requests.RequestException as exc:
        st.error(f"Ollama answered with an error: {exc}")

demo = st.toggle("Demo mode (replay a saved run; no model is called)", prefs.demo_mode, key="demo_mode")
checkpoint = st.toggle("Save checkpoints (a stopped live run can resume where it left off)",
                       prefs.checkpoint, key="checkpoint")

st.subheader("API keys")
st.caption("Edit `.env` to change keys. Only whether each key is set is shown here.")
for name, var in (("OpenAI", "OPENAI_API_KEY"), ("FRED", "FRED_API_KEY")):
    st.markdown(f"{name} key: {'set' if os.environ.get(var) else 'missing'}")

if st.button("Save", key="save", type="primary"):
    prefs.provider, prefs.quick_model, prefs.deep_model = PROVIDERS[label], quick.strip(), deep.strip()
    prefs.ollama_url, prefs.demo_mode, prefs.checkpoint = url.strip(), demo, checkpoint
    save_prefs(prefs)
    st.success("Saved.")

st.divider()
st.subheader("Portfolio")
st.caption("Holdings and cash the agents see at the analysis date, so they can tell adding to a "
           "position from opening one. Used by New run, Home and Backtest when ticked. "
           "Same format as the CLI's `--portfolio` file.")
book = portfolio_store.load()
rows = st.data_editor(
    portfolio_store.to_rows(book) or [{"ticker": None, "quantity": None, "average_price": None}],
    num_rows="dynamic", key="pf_rows", hide_index=True,
    column_config={
        "ticker": st.column_config.TextColumn("Ticker", help="e.g. AAPL, RELIANCE.NS"),
        "quantity": st.column_config.NumberColumn("Quantity", help="Negative for a short"),
        "average_price": st.column_config.NumberColumn("Average price"),
    },
)
p1, p2 = st.columns(2)
cash = p1.number_input("Cash available", value=book.cash if book and book.cash is not None else None,
                       min_value=0.0, key="pf_cash", placeholder="none")
currency = p2.text_input("Currency", value=(book.currency or "") if book else "", key="pf_currency",
                         placeholder="e.g. USD, INR")
b1, b2 = st.columns(2)
if b1.button("Save portfolio", key="pf_save", type="primary"):
    try:
        portfolio_store.save(portfolio_store.from_rows(list(rows), cash, currency))
        st.success("Portfolio saved.")
    except ValueError as exc:
        st.error(f"Not saved — {exc}")
if b2.button("Clear portfolio", key="pf_clear", disabled=book is None):
    portfolio_store.clear()
    st.success("Portfolio cleared. Runs now see no holdings.")
upload = st.file_uploader("Import a portfolio JSON", type=["json"], key="pf_upload")
if upload is not None and st.button("Import", key="pf_import"):
    try:
        portfolio_store.save(portfolio_store.parse_upload(upload.getvalue()))
        st.success("Portfolio imported.")
        st.rerun()
    except ValueError as exc:
        st.error(f"Not imported — {exc}")
