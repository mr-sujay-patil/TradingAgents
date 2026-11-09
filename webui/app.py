"""The web UI's entry point: `tradingagents-ui`, or `streamlit run webui/app.py`."""

import streamlit as st

from webui.ui_common import get_prefs, sidebar_status

st.set_page_config(page_title="TradingAgents", layout="wide")

nav = st.navigation([
    st.Page("pages/home.py", title="Home", default=True),
    st.Page("pages/new_run.py", title="New run"),
    st.Page("pages/history.py", title="History"),
    st.Page("pages/settings.py", title="Settings"),
])
sidebar_status(get_prefs())
nav.run()
