"""Which data vendor serves each kind of data, in order, as Settings sets it.

The categories, their tools and which vendor serves which tool come from the
engine's router, so a vendor added there shows up here. A chain is checked
before it is saved: every tool in a category needs a vendor in its chain, or the
router refuses that tool mid-run (SEC EDGAR alone, for one, has no company
overview).
"""

import os

from tradingagents.dataflows.router import TOOLS_CATEGORIES, VENDOR_METHODS
from tradingagents.default_config import DEFAULT_CONFIG

LABELS = {"yfinance": "Yahoo Finance", "alpha_vantage": "Alpha Vantage", "sec_edgar": "SEC EDGAR",
          "fred": "FRED", "polymarket": "Polymarket"}
# Vendors that need a key, and the variable that holds it.
KEYS = {"alpha_vantage": "ALPHA_VANTAGE_API_KEY", "fred": "FRED_API_KEY"}


def label(vendor: str) -> str:
    return LABELS.get(vendor, vendor)


def options(category: str) -> list[str]:
    """Every vendor that serves at least one of the category's tools."""
    found = []
    for tool in TOOLS_CATEGORIES[category]["tools"]:
        found += [v for v in VENDOR_METHODS[tool] if v not in found]
    return found


def choosable() -> list[str]:
    """The categories with more than one vendor to choose between."""
    return [c for c in TOOLS_CATEGORIES if len(options(c)) > 1]


def default_chain(category: str) -> list[str]:
    value = DEFAULT_CONFIG["data_vendors"].get(category, "default")
    return options(category) if value == "default" else [v.strip() for v in value.split(",") if v.strip()]


def chain_problem(category: str, chain: list[str]) -> str | None:
    """Why ``chain`` can't serve the category, or None."""
    if not chain:
        return "Pick at least one vendor."
    uncovered = [t for t in TOOLS_CATEGORIES[category]["tools"]
                 if not any(v in VENDOR_METHODS[t] for v in chain)]
    if uncovered:
        return f"Nothing in this list serves {', '.join(f'`{t}`' for t in uncovered)}; add a vendor that does."
    return None


def key_notes(chain: list[str]) -> list[str]:
    """A note for each vendor in ``chain`` whose key is not set."""
    return [f"{label(v)} needs `{KEYS[v]}` in `.env`; without it the next vendor in the list is used."
            for v in chain if v in KEYS and not os.environ.get(KEYS[v])]


def overrides(chains: dict[str, list[str]]) -> dict[str, str]:
    """The chains that differ from the engine's defaults, as config values."""
    return {c: ",".join(chain) for c, chain in chains.items() if chain and chain != default_chain(c)}


def chain_for(saved: dict[str, str], category: str) -> list[str]:
    value = saved.get(category)
    return [v for v in value.split(",") if v in options(category)] if value else default_chain(category)
