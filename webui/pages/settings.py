"""Defaults for new runs, Ollama status, and which API keys are set (never their values)."""

import os

import requests
import streamlit as st

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

st.subheader("API keys")
st.caption("Edit `.env` to change keys. Only whether each key is set is shown here.")
for name, var in (("OpenAI", "OPENAI_API_KEY"), ("FRED", "FRED_API_KEY")):
    st.markdown(f"{name} key: {'set' if os.environ.get(var) else 'missing'}")

if st.button("Save", key="save", type="primary"):
    prefs.provider, prefs.quick_model, prefs.deep_model = PROVIDERS[label], quick.strip(), deep.strip()
    prefs.ollama_url, prefs.demo_mode = url.strip(), demo
    save_prefs(prefs)
    st.success("Saved.")
