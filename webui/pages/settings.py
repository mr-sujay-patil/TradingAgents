"""Defaults for new runs, Ollama status, and which API keys are set (never their values)."""

import requests
import streamlit as st

from tradingagents.dataflows.router import TOOLS_CATEGORIES
from webui import portfolio_store, providers, vendors
from webui.prefs import save_prefs
from webui.runner import OLLAMA_DOWN, ollama_models
from webui.ui_common import advanced_inputs, get_prefs, llm_inputs

st.title("Settings")
prefs = get_prefs()

choice = llm_inputs(prefs, "")
for tier_provider, tier_url in choice.tiers:
    if providers.is_paid(tier_provider):
        st.caption(f"{providers.label(tier_provider)} runs bill your account.")
    if tier_provider != "ollama" and (setup := providers.missing_setup(tier_provider, tier_url)):
        st.caption(f"Before this can run: {setup}")
advanced = advanced_inputs(prefs, "", choice)

ollama_url = next((u for p, u in choice.tiers if p == "ollama"), "")
if ollama_url and st.button("Check Ollama", key="check_ollama"):
    try:
        models = ollama_models(ollama_url)
        st.success("Ollama is running. Installed models: " + (", ".join(models) or "none"))
    except (requests.ConnectionError, requests.Timeout):
        st.error(OLLAMA_DOWN)
    except requests.RequestException as exc:
        st.error(f"Ollama answered with an error: {exc}")

demo = st.toggle("Demo mode (replay a saved run; no model is called)", prefs.demo_mode, key="demo_mode")
checkpoint = st.toggle("Save checkpoints (a stopped live run can resume where it left off)",
                       prefs.checkpoint, key="checkpoint")

st.subheader("Data vendors")
st.caption("Where each kind of data comes from, tried in the order listed: when one can't serve a "
           "request, the next is asked. Only vendors listed are ever used.")
chains, vendor_problems = {}, []
for category in vendors.choosable():
    picked = st.multiselect(TOOLS_CATEGORIES[category]["description"], vendors.options(category),
                            default=vendors.chain_for(prefs.data_vendors, category),
                            format_func=vendors.label, key=f"vendors_{category}")
    chains[category] = picked
    if problem := vendors.chain_problem(category, picked):
        st.error(problem)
        vendor_problems.append(problem)
    for note in vendors.key_notes(picked):
        st.caption(note)

st.subheader("API keys")
st.caption("Edit `.env` (or `.env.enterprise` for Azure) and restart to change keys. "
           "Only whether each key is set is shown here.")
st.markdown("  \n".join(f"{name} key: {'set' if is_set else 'missing'} (`{var}`)"
                        for name, var, is_set in providers.key_status()))

if st.button("Save", key="save", type="primary", disabled=bool(vendor_problems)):
    prefs.provider, prefs.quick_model, prefs.deep_model = choice.provider, choice.quick, choice.deep
    for tier_provider, tier_url in choice.tiers:
        if tier_provider == "ollama":
            prefs.ollama_url = tier_url
        elif tier_provider == "openai_compatible" and tier_provider == choice.provider:
            prefs.backend_url = tier_url
    prefs.deep_provider, prefs.deep_backend_url = choice.deep_provider, choice.deep_url
    for name, value in advanced.items():
        setattr(prefs, name, value)
    prefs.data_vendors = vendors.overrides(chains)
    prefs.demo_mode, prefs.checkpoint = demo, checkpoint
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
