"""Pieces every page shares: the prefs in this session, the sidebar status, rating badges."""

from dataclasses import dataclass

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
    from webui import providers

    cost = "paid" if providers.run_paid(prefs.provider, prefs.deep_provider) else "free"
    if prefs.deep_provider and prefs.deep_provider != prefs.provider:
        return (f"{providers.label(prefs.provider)} · {prefs.quick_model} / "
                f"{providers.label(prefs.deep_provider)} · {prefs.deep_model} ({cost})")
    return f"{providers.label(prefs.provider)} · {prefs.quick_model} / {prefs.deep_model} ({cost})"


CUSTOM_MODEL = "Other model ID…"


@st.cache_data(ttl=30, show_spinner=False)
def _installed_ollama(url: str) -> list[str]:
    import requests

    from webui.runner import ollama_models

    try:
        return [m for m in ollama_models(url) if m]
    except (requests.RequestException, OSError, ValueError):
        return []


def _model_input(col, title: str, provider: str, tier: str, current: str, key: str, url: str) -> str:
    """A pick from the provider's models (installed ones, for Ollama), or any model ID."""
    from webui import providers

    choices = _installed_ollama(url) if provider == "ollama" and url else []
    choices = choices or providers.model_choices(provider, tier)
    if not choices:
        return col.text_input(title, current, key=key, placeholder="model ID").strip()
    options = ([current] if current and current not in choices else []) + choices + [CUSTOM_MODEL]
    pick = col.selectbox(title, options, index=options.index(current) if current in options else 0,
                         key=key)
    if pick == CUSTOM_MODEL:
        return col.text_input(f"{title} ID", key=f"{key}_custom", placeholder="model ID").strip()
    return pick


def _provider_input(title: str, current: str, key: str, exclude: str = "") -> str:
    from webui import providers

    keys = [k for k in providers.KEYS if k != exclude]
    return st.selectbox(title, keys, format_func=providers.label, key=key,
                        index=keys.index(current) if current in keys else 0)


def _url_input(provider: str, current_ollama: str, current_server: str, key: str) -> str:
    """The endpoint a local provider needs; "" for a hosted one (its client knows its own)."""
    if provider == "ollama":
        return st.text_input("Ollama URL", current_ollama, key=f"{key}ollama_url").strip()
    if provider == "openai_compatible":
        return st.text_input("Server URL", current_server, key=f"{key}backend_url",
                             placeholder="e.g. http://localhost:8000/v1 for vLLM").strip()
    return ""


@dataclass
class LLMChoice:
    provider: str
    quick: str
    deep: str
    url: str                # the main provider's endpoint, when it takes one
    deep_provider: str = ""  # "" when the deep tier shares the main provider
    deep_url: str = ""

    @property
    def tiers(self) -> list[tuple[str, str]]:
        """(provider, endpoint) for each provider the run uses."""
        return [(self.provider, self.url)] + ([(self.deep_provider, self.deep_url)] if self.deep_provider else [])

    def request_fields(self, ollama_url: str) -> dict:
        """The RunRequest fields this choice sets; ``ollama_url`` is kept when Ollama isn't picked."""
        return {"provider": self.provider, "quick_model": self.quick, "deep_model": self.deep,
                "ollama_url": self.url if self.provider == "ollama" else ollama_url,
                "backend_url": self.url if self.provider == "openai_compatible" else "",
                "deep_provider": self.deep_provider, "deep_backend_url": self.deep_url}


def llm_inputs(prefs: UIPrefs, prefix: str) -> LLMChoice:
    """Provider, models and endpoints; optionally the deep tier on a provider of its own."""
    provider = _provider_input("Provider", prefs.provider, f"{prefix}provider")
    url = _url_input(provider, prefs.ollama_url, prefs.backend_url, prefix)
    split_saved = bool(prefs.deep_provider) and prefs.deep_provider != prefs.provider
    split = st.checkbox("Run the deep-thinking tier (Research and Portfolio Managers) on another "
                        "provider", value=split_saved, key=f"{prefix}split")
    # The saved models belong to the saved providers; another one starts at its own defaults.
    c1, c2 = st.columns(2)
    # Keyed by provider, so each keeps its own pick while the user switches around.
    quick = _model_input(c1, "Quick-thinking model", provider, "quick",
                         prefs.quick_model if provider == prefs.provider else "",
                         f"{prefix}quick_{provider}", url)
    if not split:
        deep = _model_input(c2, "Deep-thinking model", provider, "deep",
                            prefs.deep_model if provider == prefs.provider and not split_saved else "",
                            f"{prefix}deep_{provider}", url)
        return LLMChoice(provider, quick, deep, url)
    with c2:
        deep_provider = _provider_input("Deep-thinking provider", prefs.deep_provider,
                                        f"{prefix}deep_provider", exclude=provider)
        deep_url = _url_input(deep_provider, prefs.deep_backend_url or prefs.ollama_url,
                              prefs.deep_backend_url, f"{prefix}deep_")
    deep = _model_input(c2, "Deep-thinking model", deep_provider, "deep",
                        prefs.deep_model if deep_provider == prefs.deep_provider else "",
                        f"{prefix}deep_{deep_provider}_split", deep_url)
    return LLMChoice(provider, quick, deep, url, deep_provider, deep_url)


def cost_notice(choice: LLMChoice, demo_mode: bool) -> bool:
    """Say what the run costs and what it still needs; True when it bills an account."""
    from webui import providers

    if demo_mode:
        st.info("Demo mode — replays a saved run. Free; no model is called. Turn it off in Settings.")
        return False
    paid = providers.run_paid(choice.provider, choice.deep_provider)
    names = " + ".join(providers.label(p) for p, _ in choice.tiers)
    if paid:
        st.warning(f"{names} — paid.")
    else:
        st.info(f"{names} — free; runs on your own server.")
    for provider, url in choice.tiers:
        if provider != "ollama" and (setup := providers.missing_setup(provider, url)):
            st.caption(f"Before this can run: {setup}")
    return paid


LANGUAGES = ["English", "Chinese", "Japanese", "Korean", "Hindi", "Spanish", "Portuguese",
             "French", "German", "Arabic", "Russian"]
OTHER_LANGUAGE = "Other language…"
# config key -> (label, the providers that read it, [(value, label)]); "" is the provider's default.
EFFORTS = {
    "openai_reasoning_effort": ("OpenAI reasoning effort", ("openai",),
                                [("", "Provider default"), ("low", "Low (faster)"), ("medium", "Medium"),
                                 ("high", "High (more thorough)")]),
    "anthropic_effort": ("Anthropic effort", ("anthropic",),
                         [("", "Provider default"), ("low", "Low (faster, cheaper)"),
                          ("medium", "Medium"), ("high", "High")]),
    "google_thinking_level": ("Gemini thinking", ("google",),
                              [("", "Provider default"), ("high", "On"), ("minimal", "Minimal")]),
}


def advanced_inputs(prefs: UIPrefs, prefix: str, choice: LLMChoice) -> dict:
    """Language, reasoning effort and temperature: RunRequest fields, prefilled from ``prefs``.

    An effort knob shows only when a provider the run uses reads it; the others keep
    their saved value, so switching providers doesn't lose them.
    """
    used = {p for p, _ in choice.tiers}
    with st.expander("Advanced"):
        options = LANGUAGES + [OTHER_LANGUAGE]
        saved = prefs.output_language or "English"
        pick = st.selectbox("Report language", options, key=f"{prefix}language",
                            index=options.index(saved) if saved in options else len(LANGUAGES),
                            help="The agents debate in English; the reports are written in this language.")
        language = (st.text_input("Language", "" if saved in LANGUAGES else saved, key=f"{prefix}language_other",
                                  placeholder="e.g. Turkish, Vietnamese").strip() or "English"
                    if pick == OTHER_LANGUAGE else pick)
        fields = {"output_language": language}
        for name, (title, readers, levels) in EFFORTS.items():
            current = getattr(prefs, name) or ""
            if not used & set(readers):
                fields[name] = current
                continue
            values = [v for v, _ in levels]
            fields[name] = st.selectbox(title, values, format_func=dict(levels).get, key=f"{prefix}{name}",
                                        index=values.index(current) if current in values else 0)
        set_temp = st.checkbox("Set the sampling temperature", value=prefs.temperature is not None,
                               key=f"{prefix}set_temp",
                               help="Off leaves each provider at its own default. Reasoning models largely "
                                    "ignore it, and no setting makes runs identical.")
        fields["temperature"] = (st.slider("Temperature", 0.0, 2.0, float(prefs.temperature or 0.7), 0.05,
                                           key=f"{prefix}temp") if set_temp else None)
    return fields


def sidebar_status(prefs: UIPrefs) -> None:
    with st.sidebar:
        st.markdown(f"**Mode: {'Demo' if prefs.demo_mode else 'Live'}**")
        st.markdown(f"LLM: {provider_label(prefs)}")
        run = active_run()
        if run is not None and not run.finished:
            st.markdown(f"⏳ {_KIND_NAMES.get(run.kind, 'Run')} in progress: {run.label}")


_KIND_NAMES = {"analysis": "Run", "demo": "Demo run", "settle": "Settling", "backtest": "Backtest"}
# The page that shows each kind of job's progress.
JOB_PAGES = {"analysis": "pages/new_run.py", "demo": "pages/new_run.py",
             "settle": "pages/outcomes.py", "backtest": "pages/backtest.py"}


def other_job_notice(kinds: tuple[str, ...]) -> bool:
    """When a job this page doesn't own is running, say so and link to it. True if one is."""
    run = active_run()
    if run is None or run.finished or run.kind in kinds:
        return False
    st.info(f"{_KIND_NAMES.get(run.kind, 'A job')} in progress ({run.label}). "
            "One job runs at a time; this page is available when it finishes.")
    if st.button("Go to it", key="goto_job"):
        st.switch_page(JOB_PAGES.get(run.kind, "pages/home.py"))
    return True


def portfolio_choice(key: str):
    """'Use my portfolio' when one is saved: the book, or None (no context at all)."""
    from webui import portfolio_store

    book = portfolio_store.load()
    if book is None:
        st.caption("No portfolio saved — runs see no holdings. Add one in Settings.")
        return None
    use = st.checkbox(f"Use my portfolio ({portfolio_store.describe(book)})", value=True, key=key)
    return book if use else None


def rating_badge(rating: str) -> str:
    color = _COLORS.get((rating or "").strip().lower(), "gray")
    return f":{color}-badge[{rating or '—'}]"


def start(req, demo_mode: bool) -> str | None:
    """Start a demo or live run; a reason it can't start, or None."""
    from webui import demo, runner

    if demo_mode:
        demo.start_demo(delay=demo.DEMO_DELAY)
        return None
    problem = runner.preflight(req)
    if problem:
        return problem
    runner.start_run(req)
    return None


def run_blocked() -> bool:
    run = active_run()
    return run is not None and not run.finished


_GROUP_NAMES = {"debate": "Bull/Bear debate", "manager": "Research Manager", "trader": "Trader",
                "risk": "Risk debate", "portfolio": "Portfolio Manager"}


def _pipeline(events) -> str:
    """One chip per analyst, then one per later group: ✅ done, ⏳ running, ○ pending.

    A group is done once a later group has reported (or the run finished);
    the analysts are done once each has filed. The first group not done is running.
    """
    from webui.stages import GROUPS, STAGE_BY_KEY

    finished = any(e.kind == "done" for e in events)
    reported = {e.stage for e in events if e.kind == "report"}
    analysts = [e.stage for e in events if e.kind == "stage" and e.status != "resuming"]
    reached = [GROUPS.index(STAGE_BY_KEY[k].group) for k in reported]
    furthest = max(reached, default=-1)

    def done(i, group):
        if finished:
            return True
        if group == "analysts":
            return all(k in reported for k in analysts)
        return i < furthest

    chips, running = [], None
    for i, group in enumerate(GROUPS):
        is_done = done(i, group)
        if not is_done and running is None and not finished:
            running = group
        if group == "analysts":
            chips += [("✅ " if k in reported or finished else "⏳ ") + STAGE_BY_KEY[k].title
                      for k in analysts]
            continue
        mark = "✅ " if is_done else "⏳ " if running == group else "○ "
        chips.append(mark + _GROUP_NAMES[group])
    return "  →  ".join(chips)


def _render(handle) -> None:
    import time

    events = handle.events_since(0)
    st.markdown(f"**{handle.label}**")
    st.markdown(_pipeline(events))
    if not handle.finished:
        st.caption(f"Elapsed: {int(time.monotonic() - handle.started_at)} s")
    for e in events:
        if e.kind == "stage" and e.status == "resuming":
            st.info(e.content)
    for e in events:
        if e.kind == "report":
            with st.expander(e.title or e.stage, expanded=e.stage == "portfolio"):
                st.markdown(e.content or "")
    last = events[-1] if events else None
    if last is not None and last.kind == "done":
        st.markdown(f"### Final rating: {rating_badge(last.rating or '—')}")
        if st.button("Open in History", key="open_done"):
            st.session_state["open_report"] = last.report_dir
            st.switch_page("pages/history.py")
        if st.button("Start a new run", key="new_after_done"):
            from webui.events import set_active_run
            set_active_run(None)
            st.rerun()
    elif last is not None and last.kind == "error":
        st.error(last.content)
        if last.detail:
            with st.expander("Details"):
                st.code(last.detail)
        req = getattr(handle, "request", None)
        if handle.kind == "analysis" and req is not None:
            label = "Resume" if req.checkpoint else "Run again"
            help_ = ("Continues from the last saved step. Same settings only: a changed "
                     "model, analyst, round count or portfolio starts fresh."
                     if req.checkpoint else "Checkpoints are off in Settings, so this starts over.")
            if st.button(label, key="resume", type="primary", help=help_):
                from webui import runner
                runner.start_run(req)
                st.rerun()
        if st.button("Back to form", key="back"):
            from webui.events import set_active_run
            set_active_run(None)
            st.rerun()


@st.fragment(run_every=1)
def _live(handle) -> None:
    _render(handle)
    if handle.finished:
        st.rerun()   # leave refresh mode once; the finished view is static


def render_progress(handle) -> None:
    if handle.finished:
        _render(handle)
    else:
        _live(handle)
