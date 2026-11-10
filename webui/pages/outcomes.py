"""How past decisions did against their benchmark, and settling the ones now due."""

import streamlit as st

from webui import outcomes, providers
from webui.events import active_run, set_active_run
from webui.prefs import run_settings
from webui.runner import RunRequest, preflight
from webui.ui_common import get_prefs, other_job_notice, rating_badge, run_blocked

st.title("Outcomes")
st.caption("Every decision is scored once its holding window has traded: the return from the "
           "first close after the analysis date, and alpha against the market's benchmark. "
           "Indicative, not repeatable — one model sampling per decision.")
prefs = get_prefs()


@st.fragment(run_every=1)
def _settle_progress(handle):
    events = handle.events_since(0)
    if not handle.finished:
        st.info(f"Settling past decisions… {len(events)} done so far.")
        return
    st.rerun()


def _settle_result(handle):
    events = handle.events_since(0)
    last = events[-1]
    if last.kind == "error":
        st.error(last.content)
        if last.detail:
            with st.expander("Details"):
                st.code(last.detail)
    else:
        st.success(last.content)
    for e in events:
        if e.kind == "report" and e.stage == "failed":
            st.warning(f"{e.title}: {e.content}")
    if st.button("Dismiss", key="settle_dismiss"):
        set_active_run(None)
        st.rerun()


handle = active_run()
other_job_notice(("settle",))
if handle is not None and handle.kind == "settle":
    if handle.finished:
        _settle_result(handle)
    else:
        _settle_progress(handle)

rows = outcomes.load_outcomes()
if not rows:
    st.caption("No decisions recorded yet. Each finished live run adds one here.")
    st.stop()

summary = outcomes.scores()
due = sum(1 for r in rows if r.status == outcomes.PENDING)
m1, m2, m3 = st.columns(3)
m1.metric("Decisions", len(rows))
m2.metric("Settled", summary.resolved if summary else 0)
m3.metric("Pending", due)

if summary and summary.by_rating:
    st.subheader("By rating")
    st.dataframe(
        [{"Rating": rating, "Settled": score.count,
          "Called the direction": f"{score.hit_rate:.0%}" if score.hit_rate is not None else "n/a (no direction)",
          "Mean alpha": f"{score.mean_alpha:+.2%}"}
         for rating, score in summary.by_rating.items()],
        hide_index=True,
    )
    if summary.holding:
        st.caption(f"Measured over {summary.holding}.")

st.subheader("Settle due decisions")
paid = providers.run_paid(prefs.provider, prefs.deep_provider)
if prefs.demo_mode:
    st.caption("Off in demo mode: settling fetches real prices and asks the model for a reflection "
               "on each decision. Turn demo mode off in Settings.")
st.caption(f"{due} pending. Settling uses {providers.cost_note(prefs.provider)} · "
           f"{prefs.quick_model} for one reflection per decision whose window has traded.")
paid_ok = st.checkbox("I understand this uses paid API credits", key="settle_paid") if paid else True
if st.button("Settle now", key="settle", type="primary",
             disabled=prefs.demo_mode or not due or not paid_ok or run_blocked()):
    req = RunRequest(ticker="", trade_date="", analysts=["market"], provider=prefs.provider,
                     quick_model=prefs.quick_model, deep_model=prefs.deep_model,
                     ollama_url=prefs.ollama_url, debate_rounds=1, risk_rounds=1,
                     backend_url=prefs.backend_url, **run_settings(prefs))
    problem = preflight(req)
    if problem:
        st.error(problem)
    else:
        outcomes.start_settle(req)
        st.rerun()

st.subheader("Decisions")
f1, f2 = st.columns(2)
tickers = f1.multiselect("Ticker", sorted({r.ticker for r in rows}), key="o_ticker")
statuses = f2.multiselect("Status", [outcomes.SETTLED, outcomes.PENDING, outcomes.UNSCORED], key="o_status")
shown = [r for r in rows if (not tickers or r.ticker in tickers) and (not statuses or r.status in statuses)]
st.dataframe(
    [{"Date": r.date, "Ticker": r.ticker, "Rating": r.rating, "Status": r.status,
      "Return": r.raw, "Alpha": r.alpha, "Holding": r.holding, "Resolved": r.resolved}
     for r in shown],
    hide_index=True,
)
settled = [r for r in shown if r.status == outcomes.SETTLED]
if settled:
    pick = st.selectbox("Read a settled decision's reflection", range(len(settled)), key="o_pick",
                        index=None, format_func=lambda i: f"{settled[i].ticker} · {settled[i].date}")
    if pick is not None:
        r = settled[pick]
        st.markdown(f"### {r.ticker} · {r.date} {rating_badge(r.rating)}")
        st.caption(f"Return {r.raw} · alpha {r.alpha} over {r.holding} · resolved {r.resolved}")
        st.markdown("#### Reflection")
        st.markdown(r.reflection or "_None recorded._")
        with st.expander("Decision"):
            st.markdown(r.decision)
