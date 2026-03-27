"""
Reflection engine for the learning trading agent.
Uses Claude to analyze trade history and extract actionable lessons.
"""

import os
import json
from anthropic import Anthropic
from dotenv import load_dotenv
from stock_agent.memory import (
    get_recent_trades,
    get_lessons,
    store_lessons,
    get_performance_summary,
    log_token_usage,
)

load_dotenv()

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def reflect(min_trades: int = 5) -> dict:
    """
    Analyze recent trades and extract actionable lessons.

    Args:
        min_trades: Minimum trades needed before reflecting (default 5)
    """
    # Get recent closed trades
    recent = get_recent_trades(20)
    trades = recent.get("trades", [])

    if len(trades) < min_trades:
        return {
            "status": "skipped",
            "reason": f"Need at least {min_trades} closed trades to reflect. Have {len(trades)}.",
            "trades_available": len(trades),
        }

    # Get existing lessons for context
    existing = get_lessons()
    existing_lessons = [l["lesson"] for l in existing.get("lessons", [])]

    # Get performance summary
    performance = get_performance_summary()

    # Build reflection prompt
    prompt = f"""You are analyzing the trade history of a learning stock trading agent.
Your goal is to extract specific, actionable, and falsifiable trading rules from this data.

## Performance Summary
{json.dumps(performance, indent=2)}

## Recent Trades (last {len(trades)})
{json.dumps(trades, indent=2)}

## Existing Lessons Already Learned
{json.dumps(existing_lessons, indent=2)}

## Your Task
1. Analyze the trade history carefully — look for patterns in:
   - RSI levels at entry (winning vs losing trades)
   - VIX levels at entry
   - Sectors that outperform/underperform
   - Hold duration patterns
   - Entry/exit reasoning quality

2. Extract 3-7 NEW specific lessons not already in the existing lessons list.
   Each lesson must be:
   - Specific and measurable (include numbers where possible)
   - Falsifiable (can be proven right or wrong)
   - Actionable (changes how future trades are made)

3. Write a brief overall summary of what the agent is learning.

## Response Format (JSON only, no other text)
{{
    "lessons": [
        "Lesson 1 text here",
        "Lesson 2 text here"
    ],
    "summary": "Brief overall summary of patterns observed"
}}
"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    log_token_usage(
        call_type="reflect",
        model=response.model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )

    # Parse Claude's response
    try:
        content = response.content[0].text.strip()
        # Extract JSON if wrapped in markdown
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        result = json.loads(content)
        lessons = result.get("lessons", [])
        summary = result.get("summary", "")

        # Store the lessons
        store_result = store_lessons(lessons, summary)

        return {
            "status": "completed",
            "trades_analyzed": len(trades),
            "lessons_extracted": len(lessons),
            "lessons": lessons,
            "summary": summary,
            "tokens_used": response.usage.input_tokens + response.usage.output_tokens,
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "raw_response": response.content[0].text,
        }


def get_relevant_lessons(ticker: str, sector: str = None, rsi: float = None) -> list[str]:
    """
    Retrieve lessons most relevant to a potential trade.

    Args:
        ticker: Stock being considered
        sector: Sector of the stock
        rsi:    Current RSI value
    """
    all_lessons = get_lessons()
    lessons = all_lessons.get("lessons", [])

    if not lessons:
        return []

    # Ask Claude to filter relevant lessons
    prompt = f"""From these trading lessons, select the most relevant ones for this trade context.

## Trade Context
Ticker: {ticker}
Sector: {sector or 'Unknown'}
Current RSI: {rsi or 'Unknown'}

## All Lessons
{json.dumps([l['lesson'] for l in lessons], indent=2)}

Return only the lesson texts that are relevant to this specific trade context.
Format: JSON array of strings only.
Example: ["lesson 1", "lesson 2"]
"""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",   # filtering/classification task — Haiku is sufficient
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}]
    )
    log_token_usage(
        call_type="reflect",
        model=response.model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )

    try:
        content = response.content[0].text.strip()
        if "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
            if content.startswith("json"):
                content = content[4:].strip()
        return json.loads(content)
    except Exception:
        # Fallback — return top 3 lessons by confidence
        return [l["lesson"] for l in lessons[:3]]


if __name__ == "__main__":
    print("Testing reflection engine...")
    print("\nNote: Need at least 5 closed trades to reflect.")
    print("Running with min_trades=1 for testing...\n")

    result = reflect(min_trades=1)
    print(json.dumps(result, indent=2))

    print("\n=== Relevant Lessons for AAPL ===")
    lessons = get_relevant_lessons("AAPL", sector="Technology", rsi=28.5)
    print(json.dumps(lessons, indent=2))
