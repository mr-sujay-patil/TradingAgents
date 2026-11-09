"""The standing book the UI feeds to runs: holdings, cash and currency.

Saved in the engine's own ``PortfolioContext`` JSON shape, so the same file
works with the CLI's ``--portfolio``. No file means no context at all, which
the engine keeps distinct from a flat book; the UI never turns one into the other.
"""

import json
import math
from pathlib import Path

from pydantic import ValidationError

from tradingagents.default_config import _TRADINGAGENTS_HOME
from tradingagents.portfolio import PortfolioContext

PORTFOLIO_PATH = Path(_TRADINGAGENTS_HOME) / "webui_portfolio.json"


def _path(path) -> Path:
    return Path(path or PORTFOLIO_PATH)


def load(path: Path | None = None) -> PortfolioContext | None:
    """The saved book, or None when there is none or it can't be read."""
    try:
        return PortfolioContext.model_validate_json(_path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save(ctx: PortfolioContext, path: Path | None = None) -> None:
    target = _path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(ctx.model_dump_json(indent=2), encoding="utf-8")


def clear(path: Path | None = None) -> None:
    _path(path).unlink(missing_ok=True)


def _blank(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return isinstance(value, str) and not value.strip()


def _message(exc: ValidationError) -> str:
    first = exc.errors()[0]
    where = ".".join(str(p) for p in first["loc"])
    return f"{where}: {first['msg']}"


def from_rows(rows: list[dict], cash=None, currency: str | None = None) -> PortfolioContext:
    """A book from the Settings table. Rows with no ticker are dropped; anything
    the engine would reject raises ValueError with a readable reason."""
    positions = []
    for i, row in enumerate(rows, 1):
        ticker = row.get("ticker")
        if _blank(ticker):
            continue
        quantity = row.get("quantity")
        if _blank(quantity):
            raise ValueError(f"row {i} ({str(ticker).strip()}): quantity is required")
        price = row.get("average_price")
        positions.append({"ticker": str(ticker).strip().upper(), "quantity": quantity,
                          "average_price": None if _blank(price) else price})
    data = {"cash": None if _blank(cash) else cash,
            "currency": None if _blank(currency) else str(currency).strip().upper(),
            "positions": positions}
    try:
        return PortfolioContext.model_validate(data)
    except ValidationError as exc:
        raise ValueError(_message(exc)) from None


def to_rows(ctx: PortfolioContext | None) -> list[dict]:
    if ctx is None:
        return []
    return [{"ticker": p.ticker, "quantity": p.quantity, "average_price": p.average_price}
            for p in ctx.positions]


def parse_upload(data: bytes) -> PortfolioContext:
    """A book from an uploaded JSON file, in the CLI's ``--portfolio`` format."""
    try:
        return PortfolioContext.model_validate(json.loads(data.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"not a JSON file: {exc}") from None
    except ValidationError as exc:
        raise ValueError(_message(exc)) from None


def describe(ctx: PortfolioContext) -> str:
    """One line for the forms: '3 positions · cash 50,000.00 INR'."""
    n = len(ctx.positions)
    parts = [f"{n} position{'s' if n != 1 else ''}"]
    if ctx.cash is not None:
        parts.append(f"cash {ctx.cash:,.2f}{' ' + ctx.currency if ctx.currency else ''}")
    return " · ".join(parts)
