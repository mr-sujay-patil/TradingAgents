"""Every LLM provider the engine serves, as the UI offers it.

The keys are the engine's own (``api_key_env.PROVIDER_API_KEY_ENV``); the API-key
variable and the model lists come from the engine too, so a provider added there
needs only a label here, and tests/test_webui_providers.py fails until it has one.
The ChatGPT plan is left out: it signs in from the terminal (``tradingagents login
chatgpt``), which the UI does not do.
"""

import importlib.util
import os
from dataclasses import dataclass

from tradingagents.llm_clients.api_key_env import get_api_key_env
from tradingagents.llm_clients.model_catalog import get_model_options

NOT_IN_UI = {"chatgpt"}


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    free: bool = False          # a local server: no account, nothing billed
    needs_url: bool = False     # the UI asks for the endpoint


PROVIDERS = [
    Provider("ollama", "Ollama", free=True, needs_url=True),
    Provider("openai", "OpenAI"),
    Provider("anthropic", "Anthropic"),
    Provider("google", "Google"),
    Provider("xai", "xAI"),
    Provider("deepseek", "DeepSeek"),
    Provider("qwen", "Qwen"),
    Provider("qwen-cn", "Qwen (China)"),
    Provider("glm", "GLM"),
    Provider("glm-cn", "GLM (China)"),
    Provider("minimax", "MiniMax"),
    Provider("minimax-cn", "MiniMax (China)"),
    Provider("openrouter", "OpenRouter"),
    Provider("mistral", "Mistral"),
    Provider("kimi", "Kimi (Moonshot)"),
    Provider("groq", "Groq"),
    Provider("nvidia", "NVIDIA NIM"),
    Provider("azure", "Azure OpenAI"),
    Provider("bedrock", "Amazon Bedrock"),
    Provider("openai_compatible", "OpenAI-compatible server", free=True, needs_url=True),
]
BY_KEY = {p.key: p for p in PROVIDERS}
KEYS = [p.key for p in PROVIDERS]

# Azure reads these from `.env.enterprise`; the deployment name defaults to the model.
AZURE_ENV = ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "OPENAI_API_VERSION")


def label(key: str) -> str:
    return BY_KEY[key].label if key in BY_KEY else key


def is_paid(key: str) -> bool:
    """Whether a run on ``key`` bills an account. Unknown providers count as paid."""
    return not (key in BY_KEY and BY_KEY[key].free)


def run_paid(provider: str, deep_provider: str = "") -> bool:
    """Whether a run bills an account: either tier on a paid provider."""
    return is_paid(provider) or (bool(deep_provider) and is_paid(deep_provider))


def cost_note(key: str) -> str:
    return f"{label(key)} ({'paid' if is_paid(key) else 'free'})"


def model_choices(key: str, tier: str) -> list[str]:
    """The engine's suggested model IDs for a tier ("quick" or "deep"), without "custom"."""
    try:
        options = get_model_options(key, tier)
    except KeyError:
        return []
    return [model for _label, model in options if model != "custom"]


def missing_setup(key: str, endpoint: str = "") -> str | None:
    """What a run on ``key`` still needs before it can start, or None.

    Ollama is checked live by the runner's preflight; this covers the rest.
    """
    if key == "openai_compatible":
        return None if endpoint.strip() else "Enter the server's URL, e.g. http://localhost:8000/v1."
    if key == "bedrock":
        if importlib.util.find_spec("langchain_aws") is None:
            return 'Bedrock needs its extra: `pip install "tradingagents[bedrock]"`.'
        return None
    if key == "azure":
        unset = [v for v in AZURE_ENV if not os.environ.get(v)]
        return f"Azure needs {', '.join(f'`{v}`' for v in unset)} in `.env.enterprise`." if unset else None
    env = get_api_key_env(key)
    if env and not os.environ.get(env):
        return f"No {label(key)} key in `.env` (`{env}`)."
    return None


def key_status() -> list[tuple[str, str, bool]]:
    """(name, variable, whether it is set) for each API key the engine reads; never the value."""
    rows, seen = [], set()
    for p in PROVIDERS:
        env = get_api_key_env(p.key)
        if env and env not in seen and p.key != "openai_compatible":
            seen.add(env)
            rows.append((p.label, env, bool(os.environ.get(env))))
    for name, env in (("FRED", "FRED_API_KEY"), ("Alpha Vantage", "ALPHA_VANTAGE_API_KEY")):
        rows.append((name, env, bool(os.environ.get(env))))
    return rows
