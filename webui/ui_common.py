"""Pieces every page shares: the prefs in this session, the sidebar status, rating badges."""

import streamlit as st

from webui.events import active_run
from webui.prefs import UIPrefs, load_prefs

_COLORS = {"buy": "green", "overweight": "green", "hold": "gray",
           "underweight": "red", "sell": "red"}


def get_prefs() -> UIPrefs:
    if "prefs" not in st.session_state:
        st.session_state["prefs"] = load_prefs()
    return st.session_state["prefs"]


def provider_label(prefs: UIPrefs) -> str:
    if prefs.provider == "openai":
        return f"OpenAI · {prefs.quick_model} / {prefs.deep_model} (paid)"
    return f"Ollama · {prefs.quick_model} / {prefs.deep_model} (free)"


def sidebar_status(prefs: UIPrefs) -> None:
    with st.sidebar:
        st.markdown(f"**Mode: {'Demo' if prefs.demo_mode else 'Live'}**")
        st.markdown(f"LLM: {provider_label(prefs)}")
        run = active_run()
        if run is not None and not run.finished:
            st.markdown(f"⏳ Run in progress: {run.label}")


def rating_badge(rating: str) -> str:
    color = _COLORS.get((rating or "").strip().lower(), "gray")
    return f":{color}-badge[{rating or '—'}]"
