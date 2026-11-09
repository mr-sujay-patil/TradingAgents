"""The web UI's own settings, kept apart from the CLI's prefs.

Defaults favor a free local run: Ollama with a small model and demo mode on,
so nothing reaches a paid provider until the user chooses one.
"""

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path

from tradingagents.default_config import _TRADINGAGENTS_HOME

PREFS_PATH = Path(_TRADINGAGENTS_HOME) / "webui_prefs.json"


@dataclass
class UIPrefs:
    provider: str = "ollama"
    quick_model: str = "qwen3:4b"
    deep_model: str = "qwen3:4b"
    ollama_url: str = "http://localhost:11434/v1"
    analysts: list[str] = field(default_factory=lambda: ["market", "news", "fundamentals"])
    debate_rounds: int = 1
    risk_rounds: int = 1
    demo_mode: bool = True
    checkpoint: bool = True     # save each step so a stopped live run can resume


def load_prefs(path: Path | None = None) -> UIPrefs:
    """The saved prefs; a missing or unreadable file gives the defaults."""
    path = path or PREFS_PATH
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return UIPrefs()
    if not isinstance(data, dict):
        return UIPrefs()
    known = {f.name for f in dataclasses.fields(UIPrefs)}
    return UIPrefs(**{k: v for k, v in data.items() if k in known})


def save_prefs(prefs: UIPrefs, path: Path | None = None) -> None:
    path = Path(path or PREFS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dataclasses.asdict(prefs), indent=2), encoding="utf-8")
