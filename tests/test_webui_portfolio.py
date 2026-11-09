"""The UI's saved book: same shape as the CLI's --portfolio, validated before saving."""

import json

import pytest

from tradingagents.portfolio import load_portfolio
from webui import portfolio_store as ps


@pytest.mark.unit
def test_missing_file_is_no_context(tmp_path):
    assert ps.load(tmp_path / "none.json") is None


@pytest.mark.unit
def test_round_trip_and_cli_compatible(tmp_path):
    path = tmp_path / "p.json"
    ctx = ps.from_rows([{"ticker": " reliance.ns ", "quantity": 10, "average_price": 2900.5}],
                       cash=50000, currency="inr")
    ps.save(ctx, path)
    assert ps.load(path) == ctx
    cli = load_portfolio(path)   # the engine's own loader reads it
    assert cli.positions[0].ticker == "RELIANCE.NS" and cli.currency == "INR"


@pytest.mark.unit
def test_blank_rows_dropped_and_blank_price_allowed():
    ctx = ps.from_rows([{"ticker": "AAPL", "quantity": 5, "average_price": float("nan")},
                        {"ticker": "", "quantity": None, "average_price": None},
                        {"ticker": None}])
    assert [p.ticker for p in ctx.positions] == ["AAPL"]
    assert ctx.positions[0].average_price is None and ctx.cash is None


@pytest.mark.unit
def test_missing_quantity_rejected():
    with pytest.raises(ValueError, match="quantity is required"):
        ps.from_rows([{"ticker": "AAPL", "quantity": None}])


@pytest.mark.unit
def test_non_numeric_quantity_rejected():
    with pytest.raises(ValueError, match="quantity"):
        ps.from_rows([{"ticker": "AAPL", "quantity": "lots"}])


@pytest.mark.unit
def test_corrupt_file_is_no_context(tmp_path):
    path = tmp_path / "p.json"
    path.write_text("{nope")
    assert ps.load(path) is None


@pytest.mark.unit
def test_upload_and_clear(tmp_path):
    path = tmp_path / "p.json"
    ctx = ps.parse_upload(json.dumps({"cash": 1, "positions": [{"ticker": "MSFT", "quantity": 2}]}).encode())
    ps.save(ctx, path)
    assert ps.describe(ctx) == "1 position · cash 1.00"
    ps.clear(path)
    assert ps.load(path) is None
    with pytest.raises(ValueError):
        ps.parse_upload(b"\xff\xfe")
    with pytest.raises(ValueError):
        ps.parse_upload(b'{"positions": [{"ticker": "X"}]}')
