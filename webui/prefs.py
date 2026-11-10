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
    backend_url: str = ""       # an OpenAI-compatible server's endpoint
    analysts: list[str] = field(default_factory=lambda: ["market", "news", "fundamentals"])
    debate_rounds: int = 1
    risk_rounds: int = 1
    demo_mode: bool = True
    checkpoint: bool = True     # save each step so a stopped live run can resume
    # Advanced; "" or None leaves each to the engine's (or the provider's) default.
    deep_provider: str = ""     # the deep-thinking tier on a provider of its own
    deep_backend_url: str = ""  # that provider's endpoint, when it takes one
    output_language: str = "English"
    openai_reasoning_effort: str = ""
    anthropic_effort: str = ""
    google_thinking_level: str = ""
    temperature: float | None = None
    data_vendors: dict = field(default_factory=dict)   # category -> "vendor,vendor"


# The prefs a run carries as they are (RunRequest has a field of each name).
RUN_SETTINGS = ("deep_provider", "deep_backend_url", "output_language", "openai_reasoning_effort",
                "anthropic_effort", "google_thinking_level", "temperature", "data_vendors")


def run_settings(prefs: UIPrefs) -> dict:
    """The advanced settings for a run started from these prefs."""
    return {name: getattr(prefs, name) for name in RUN_SETTINGS}


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
