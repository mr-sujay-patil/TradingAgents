"""The web UI's saved preferences and the stage table the UI is built on."""

import ast
import json
from pathlib import Path

import pytest

from webui.prefs import UIPrefs, load_prefs, save_prefs
from webui.stages import ANALYSTS, GROUPS, STAGES

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.unit
def test_missing_file_gives_defaults(tmp_path):
    p = load_prefs(tmp_path / "none.json")
    assert p.provider == "ollama" and p.quick_model == "qwen3:4b" and p.deep_model == "qwen3:4b"
    assert p.ollama_url == "http://localhost:11434/v1"
    assert p.analysts == ["market", "news", "fundamentals"]
    assert (p.debate_rounds, p.risk_rounds, p.demo_mode) == (1, 1, True)


@pytest.mark.unit
def test_round_trip(tmp_path):
    path = tmp_path / "prefs.json"
    prefs = UIPrefs(provider="openai", quick_model="gpt-6-luna", analysts=["market"], demo_mode=False)
    save_prefs(prefs, path)
    assert load_prefs(path) == prefs


@pytest.mark.unit
def test_corrupt_json_gives_defaults(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_prefs(path) == UIPrefs()


@pytest.mark.unit
def test_unknown_keys_ignored(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text(json.dumps({"provider": "openai", "bogus": 1}), encoding="utf-8")
    assert load_prefs(path).provider == "openai"


@pytest.mark.unit
def test_stages_cover_every_report_file():
    from tradingagents.reporting import _SECTIONS

    files = {f"{folder}/{f}" for _h, folder, agents in _SECTIONS for _a, f, _p in agents}
    assert {s.relpath for s in STAGES} == files
    assert {s.group for s in STAGES} == set(GROUPS)
    assert ANALYSTS == ("market", "sentiment", "news", "fundamentals")


@pytest.mark.unit
def test_streamlit_is_imported_only_by_ui_modules():
    # The engine and CLI must import without the [ui] extra installed.
    allowed = {"webui/app.py", "webui/launch.py", "webui/ui_common.py"}
    offenders = []
    for path in [*ROOT.glob("webui/**/*.py"), *ROOT.glob("tradingagents/**/*.py"), *ROOT.glob("cli/**/*.py")]:
        rel = str(path.relative_to(ROOT))
        if rel in allowed or rel.startswith("webui/pages/"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            mods = ([a.name for a in node.names] if isinstance(node, ast.Import)
                    else [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            if any(m.split(".")[0] == "streamlit" for m in mods):
                offenders.append(rel)
    assert offenders == []
