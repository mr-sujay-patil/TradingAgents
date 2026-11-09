"""The run's agents in pipeline order, and where each one's report is saved.

History, the demo replay, the live runner and the progress view all walk this
one table, so a stage added to the engine's report tree is added here once.
The relpaths mirror ``tradingagents.reporting._SECTIONS``; a test keeps them in step.
"""

from typing import NamedTuple


class Stage(NamedTuple):
    key: str
    title: str
    group: str
    relpath: str


STAGES = (
    Stage("market", "Market Analyst", "analysts", "1_analysts/market.md"),
    Stage("sentiment", "Sentiment Analyst", "analysts", "1_analysts/sentiment.md"),
    Stage("news", "News Analyst", "analysts", "1_analysts/news.md"),
    Stage("fundamentals", "Fundamentals Analyst", "analysts", "1_analysts/fundamentals.md"),
    Stage("bull", "Bull Researcher", "debate", "2_research/bull.md"),
    Stage("bear", "Bear Researcher", "debate", "2_research/bear.md"),
    Stage("manager", "Research Manager", "manager", "2_research/manager.md"),
    Stage("trader", "Trader", "trader", "3_trading/trader.md"),
    Stage("aggressive", "Aggressive Analyst", "risk", "4_risk/aggressive.md"),
    Stage("conservative", "Conservative Analyst", "risk", "4_risk/conservative.md"),
    Stage("neutral", "Neutral Analyst", "risk", "4_risk/neutral.md"),
    Stage("portfolio", "Portfolio Manager", "portfolio", "5_portfolio/decision.md"),
)

GROUPS = ("analysts", "debate", "manager", "trader", "risk", "portfolio")

# The analysts as the user picks them; the graph calls "sentiment" "social".
ANALYSTS = ("market", "sentiment", "news", "fundamentals")

STAGE_BY_KEY = {s.key: s for s in STAGES}
