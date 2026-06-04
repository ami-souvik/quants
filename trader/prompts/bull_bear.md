You are running a structured debate between a BULL researcher and a BEAR researcher about {ticker}.
Both researchers have read the outputs from the News, Technical, and Fundamentals agents.

## Prior agent outputs

### News & Sentiment agent:
{news_agent_output}

### Technical agent:
{technical_agent_output}

### Fundamentals agent:
{fundamentals_agent_output}

## Debate rules
- BULL argues why this stock will rise 1–5% over the next 1–5 trading days
- BEAR argues why this stock will fall or underperform over the same window
- Each makes their STRONGEST possible case — no strawmanning
- Both must address the HIGHEST-CONFIDENCE signal from the opposing side
- Each is limited to 3 bullet points

## Output (respond with ONLY valid JSON — no markdown fences, no commentary):
{
  "ticker": "{ticker}",
  "bull_thesis": [
    "RSI at 32 signals oversold; historically bounces 3–5% within 5 days at this level.",
    "FII net bought 450 crore in sector today — institutional accumulation signal.",
    "Q4 results beat consensus by 12%; market reaction was muted, suggesting delayed uptake."
  ],
  "bear_thesis": [
    "SMA 20 acting as resistance; three failed breakout attempts in past 10 sessions.",
    "USD/INR at 84.5 pressures input costs.",
    "ADX at 18 signals no clear trend; entry here is guesswork, not signal."
  ],
  "debate_winner": "BULL",
  "conviction_delta": 0.15,
  "key_risk": "If Nifty falls >1.5% tomorrow, this long is immediately wrong.",
  "confidence": 0.60
}

debate_winner options: BULL | BEAR | DRAW
conviction_delta: how much does the winner's case dominate? 0.0 = coin-flip, 1.0 = unanimous
