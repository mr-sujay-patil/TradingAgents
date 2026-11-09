"""Every saved run (from the UI or the CLI): filter, read one, or compare two or three."""


import streamlit as st

from webui import history, outcomes
from webui.stages import STAGE_BY_KEY
from webui.ui_common import rating_badge

st.title("History")
runs, skipped = history.list_runs(history.reports_dir())
if skipped:
    st.caption(f"Skipped {skipped} unreadable folder{'s' if skipped != 1 else ''}.")
if not runs:
    st.caption("No saved runs yet. Start one from New run.")
    st.stop()

f1, f2, f3 = st.columns(3)
tickers = f1.multiselect("Ticker", sorted({r.ticker for r in runs}), key="f_ticker")
ratings = f2.multiselect("Rating", sorted({r.rating for r in runs}), key="f_rating")
span = f3.date_input("Analysis dates", value=(), key="f_dates")
start = span[0] if len(span) > 0 else None
end = span[1] if len(span) > 1 else None
shown = history.filter_runs(runs, tickers=tickers, start=start, end=end, ratings=ratings)

result = outcomes.outcome_index()
st.dataframe(
    [{"Ticker": r.ticker, "Analysis date": r.analysis_date, "Rating": r.rating,
      "Outcome": result.get((r.ticker.upper(), r.analysis_date), "—"),
      "Models": r.models, "Generated": r.generated} for r in shown],
    hide_index=True,
)

by_path = {str(r.path): r for r in shown}
opened = st.session_state.pop("open_report", None)
if opened is not None and opened not in by_path:
    try:   # a run opened from Home or a finished run, even if filtered out
        by_path[opened] = history.load_run(opened).summary
    except ValueError:
        opened = None
picked = st.multiselect(
    "Open one run, or pick 2–3 to compare", list(by_path), key="pick",
    default=[opened] if opened else None,
    format_func=lambda p: f"{by_path[p].ticker} · {by_path[p].analysis_date} · "
                          f"{by_path[p].rating} · {by_path[p].generated}",
)

TABS = {"Analysts": ("market", "sentiment", "news", "fundamentals"),
        "Research": ("bull", "bear", "manager"),
        "Trader": ("trader",),
        "Risk": ("aggressive", "conservative", "neutral"),
        "Decision": ("portfolio",)}


def show_report(path: str) -> None:
    detail = history.load_run(path)
    s = detail.summary
    st.markdown(f"## {s.ticker} · {s.analysis_date}  {rating_badge(s.rating)}")
    st.caption(f"{s.models} · analysts: {s.analysts} · generated {s.generated}")
    for tab, keys in zip(st.tabs(list(TABS)), TABS.values(), strict=True):
        with tab:
            present = [k for k in keys if k in detail.sections]
            if not present:
                st.caption("Not part of this run.")
            for key in present:
                st.markdown(f"#### {STAGE_BY_KEY[key].title}")
                st.markdown(detail.sections[key])
    page = s.path / "complete_report.html"
    if page.is_file():
        st.caption(f"Full page: {page}")
        st.download_button("Download HTML report", page.read_bytes(), file_name=f"{s.ticker}_report.html",
                           mime="text/html", key="dl_html")


def compare(paths: list[str]) -> None:
    for col, path in zip(st.columns(len(paths)), paths, strict=True):
        detail = history.load_run(path)
        s = detail.summary
        with col:
            st.markdown(f"### {s.ticker} · {s.analysis_date}")
            st.markdown(rating_badge(s.rating))
            st.caption(f"{s.models} · generated {s.generated}")
            st.markdown(detail.sections.get("portfolio", "_No final decision saved._"))
            for title, key in (("Trader plan", "trader"), ("Research Manager", "manager")):
                with st.expander(title):
                    st.markdown(detail.sections.get(key, "_Not saved._"))


if len(picked) == 1:
    show_report(picked[0])
elif 2 <= len(picked) <= 3:
    compare(picked)
elif len(picked) > 3:
    st.warning("Select up to 3 runs to compare.")
