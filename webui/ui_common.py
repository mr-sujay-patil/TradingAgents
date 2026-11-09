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
