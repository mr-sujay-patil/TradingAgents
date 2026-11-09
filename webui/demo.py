"""Demo mode: replay a saved run as if the agents were working now.

It drives the same ``RunHandle`` a live run does, so the progress view is
exercised for free and instantly. Nothing is written and no model is called.
"""

import threading
import time
from pathlib import Path

from webui import history
from webui.events import RunEvent, RunHandle, set_active_run
from webui.stages import STAGE_BY_KEY, STAGES

# Seconds between replayed stages; tests set it to 0.
DEMO_DELAY = 1.0

SAMPLE_REPORT = Path(__file__).with_name("sample_report") / "DEMO_20261106_000000"


def _pick(report_dir: Path | None, reports_root: Path | None) -> Path:
    if report_dir is not None:
        return Path(report_dir)
    runs, _ = history.list_runs(reports_root or history.reports_dir())
    return runs[0].path if runs else SAMPLE_REPORT


def start_demo(report_dir: Path | None = None, delay: float = 1.0,
               reports_root: Path | None = None) -> RunHandle:
    path = _pick(report_dir, reports_root)
    detail = history.load_run(path)
    handle = RunHandle(f"Demo · {detail.summary.ticker} {detail.summary.analysis_date}")
    set_active_run(handle)

    def replay():
        for key in detail.sections:
            if STAGE_BY_KEY[key].group == "analysts":
                handle.emit(RunEvent("stage", stage=key, status="running"))
        for stage in STAGES:
            if stage.key in detail.sections:
                time.sleep(delay)
                handle.emit(RunEvent("report", stage=stage.key, title=stage.title,
                                     content=detail.sections[stage.key]))
        handle.emit(RunEvent("done", rating=detail.summary.rating, report_dir=str(path)))

    threading.Thread(target=replay, daemon=True).start()
    return handle
