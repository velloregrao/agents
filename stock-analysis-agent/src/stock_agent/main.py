"""Entry point for the stock analysis agent."""

import argparse
import os
import sys

from dotenv import load_dotenv

from .agent import run_analysis


def main():
    load_dotenv()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set.")
        print("Add it to a .env file or export it before running.")
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="Stock analysis agent powered by Claude"
    )
    parser.add_argument(
        "ticker",
        nargs="?",
        help="Stock ticker symbol (e.g. AAPL, MSFT, TSLA)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show tool calls and thinking steps",
    )
    args = parser.parse_args()

    if not args.ticker:
        ticker = input("Enter ticker symbol: ").strip().upper()
    else:
        ticker = args.ticker.upper()

    if not ticker:
        print("No ticker provided. Exiting.")
        sys.exit(1)

    analysis = run_analysis(ticker, verbose=args.verbose)
    print(analysis)


if __name__ == "__main__":
    main()
