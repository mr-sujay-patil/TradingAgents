"""Saved-report fixtures for the web UI tests, written by the engine's own writer
so the UI's parser is tested against the real format."""

from tradingagents.reporting import write_report_tree


def make_run(root, ticker, date, decision="**Rating**: Hold\n\nok", name=None, stamp="120000"):
    state = {
        "trade_date": date,
        "market_report": "m",
        "news_report": "n",
        "investment_debate_state": {"bull_history": "b", "bear_history": "r"},
        "investment_plan": "p",
        "trader_investment_plan": "t",
        "risk_debate_state": {"aggressive_history": "a", "conservative_history": "c",
                              "neutral_history": "u"},
        "final_trade_decision": decision,
    }
    settings = {"llm_provider": "ollama", "deep_think_llm": "qwen3:4b",
                "quick_think_llm": "qwen3:4b", "version": "0.7.1",
                "analysts": ["market", "news"], "max_debate_rounds": 1,
                "max_risk_discuss_rounds": 1}
    path = root / (name or f"{ticker}_{date.replace('-', '')}_{stamp}")
    write_report_tree(state, ticker, path, settings=settings, html=False)
    return path
