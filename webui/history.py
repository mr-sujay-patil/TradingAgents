"""Past runs, read from the report folders the CLI and the UI both save.

There is no database: each run is a folder under ``<results_dir>/reports``
whose ``complete_report.md`` header (``tradingagents.reporting._header``)
says what ran. A folder that can't be read is skipped and counted, so one
half-written run never hides the rest.
"""

import functools
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from tradingagents.default_config import DEFAULT_CONFIG
from webui.stages import STAGES

TITLE = "# Trading Analysis Report: "
NO_RATING = "—"


@dataclass(frozen=True)
class RunSummary:
    path: Path
    ticker: str
    analysis_date: str
    rating: str
    generated: str
    models: str
    analysts: str


@dataclass
class RunDetail:
    summary: RunSummary
    sections: dict[str, str]


def reports_dir() -> Path:
    """Read at call time so a changed results_dir (or a test's) is honored."""
    return Path(DEFAULT_CONFIG["results_dir"]) / "reports"


def _field(lines: list[str], prefix: str) -> str:
    for line in lines:
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


@functools.lru_cache(maxsize=1024)
def _parse(path_str: str, _mtime_ns: int) -> RunSummary | None:
    path = Path(path_str)
    try:
        head = (path / "complete_report.md").read_text(encoding="utf-8").splitlines()[:20]
    except (OSError, UnicodeDecodeError):
        return None
    if not head or not head[0].startswith(TITLE):
        return None
    models_line = _field(head, "- TradingAgents ")
    return RunSummary(
        path=path,
        ticker=head[0][len(TITLE):].strip(),
        analysis_date=_field(head, "- Analysis date:"),
        rating=_field(head, "- Rating:") or NO_RATING,
        generated=_field(head, "- Generated:"),
        models=models_line.split(": ", 1)[1] if ": " in models_line else "",
        analysts=_field(head, "- Analysts:").split(";")[0].strip(),
    )


def _summary(path: Path) -> RunSummary | None:
    report = path / "complete_report.md"
    try:
        mtime = report.stat().st_mtime_ns
    except OSError:
        return None
    return _parse(str(path), mtime)


def list_runs(root: Path) -> tuple[list[RunSummary], int]:
    """Every readable run under ``root``, newest first, and how many folders were skipped."""
    root = Path(root)
    if not root.is_dir():
        return [], 0
    runs, skipped = [], 0
    for path in root.iterdir():
        if not path.is_dir():
            continue
        summary = _summary(path)
        if summary is None:
            skipped += 1
        else:
            runs.append(summary)
    runs.sort(key=lambda r: r.generated, reverse=True)
    return runs, skipped


def load_run(path: Path) -> RunDetail:
    path = Path(path)
    summary = _summary(path)
    if summary is None:
        raise ValueError(f"Not a readable report folder: {path}")
    sections = {}
    for stage in STAGES:
        file = path / stage.relpath
        if file.is_file():
            sections[stage.key] = file.read_text(encoding="utf-8")
    return RunDetail(summary=summary, sections=sections)


def filter_runs(runs, tickers: list[str] | None = None, start: date | None = None,
                end: date | None = None, ratings: list[str] | None = None) -> list[RunSummary]:
    """Runs matching every given filter; date bounds are inclusive."""
    out = []
    for r in runs:
        if tickers and r.ticker not in tickers:
            continue
        if ratings and r.rating not in ratings:
            continue
        if start or end:
            try:
                d = date.fromisoformat(r.analysis_date)
            except ValueError:
                continue
            if (start and d < start) or (end and d > end):
                continue
        out.append(r)
    return out
