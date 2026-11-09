"""History reads the report folders the CLI and the UI both save."""

from datetime import date

import pytest

from tests.webui_helpers import make_run
from webui.history import filter_runs, list_runs, load_run


@pytest.mark.unit
def test_lists_and_parses_header(tmp_path):
    make_run(tmp_path, "AAPL", "2026-11-06")
    runs, skipped = list_runs(tmp_path)
    r = runs[0]
    assert (r.ticker, r.analysis_date, r.rating, skipped) == ("AAPL", "2026-11-06", "Hold", 0)
    assert "qwen3:4b" in r.models and r.analysts == "market, news"
    assert r.generated


@pytest.mark.unit
def test_missing_rating_shows_dash(tmp_path):
    path = make_run(tmp_path, "AAPL", "2026-11-06")
    report = path / "complete_report.md"
    lines = [ln for ln in report.read_text(encoding="utf-8").splitlines() if not ln.startswith("- Rating:")]
    report.write_text("\n".join(lines), encoding="utf-8")
    runs, _ = list_runs(tmp_path)
    assert runs[0].rating == "—"


@pytest.mark.unit
def test_half_written_folder_is_skipped(tmp_path):
    make_run(tmp_path, "AAPL", "2026-11-06")
    (tmp_path / "EMPTY_1").mkdir()
    (tmp_path / "BROKEN_1").mkdir()
    (tmp_path / "BROKEN_1" / "complete_report.md").write_text("garbage", encoding="utf-8")
    runs, skipped = list_runs(tmp_path)
    assert [r.ticker for r in runs] == ["AAPL"] and skipped == 2


@pytest.mark.unit
def test_missing_reports_dir(tmp_path):
    assert list_runs(tmp_path / "nope") == ([], 0)


@pytest.mark.unit
def test_newest_first(tmp_path):
    import os
    old = make_run(tmp_path, "OLD", "2026-11-01")
    new = make_run(tmp_path, "NEW", "2026-11-02")
    # "Generated" is the write time; age the old one's report explicitly.
    rep = old / "complete_report.md"
    rep.write_text(rep.read_text(encoding="utf-8").replace("- Generated: ", "- Generated: 2000-"), encoding="utf-8")
    os.utime(new)
    assert [r.ticker for r in list_runs(tmp_path)[0]] == ["NEW", "OLD"]


@pytest.mark.unit
def test_load_run_sections(tmp_path):
    path = make_run(tmp_path, "AAPL", "2026-11-06")
    detail = load_run(path)
    assert detail.sections["market"] == "m"
    assert "sentiment" not in detail.sections
    assert "Hold" in detail.sections["portfolio"]
    assert detail.summary.ticker == "AAPL"


@pytest.mark.unit
def test_filter_by_ticker_date_rating(tmp_path):
    make_run(tmp_path, "AAPL", "2026-11-03")
    make_run(tmp_path, "NVDA", "2026-11-05", decision="**Rating**: Buy\n\nok")
    make_run(tmp_path, "AAPL", "2026-11-06", decision="**Rating**: Sell\n\nok")
    runs, _ = list_runs(tmp_path)
    assert {r.ticker for r in filter_runs(runs, tickers=["NVDA"])} == {"NVDA"}
    dated = filter_runs(runs, start=date(2026, 11, 3), end=date(2026, 11, 5))
    assert sorted(r.analysis_date for r in dated) == ["2026-11-03", "2026-11-05"]
    assert [r.rating for r in filter_runs(runs, ratings=["Sell"])] == ["Sell"]
    assert len(filter_runs(runs)) == 3
