"""
scripts/setup_vector_db.py

Standalone setup script for the Stock Copilot vector database.

Steps performed:
  1. Verify chromadb is installed
  2. Initialize ChromaDB collections (trade_memories, market_knowledge, risk_decisions)
  3. Backfill trade_memories from the existing SQLite trading_memory.db
  4. Print summary statistics

Usage:
    python scripts/setup_vector_db.py

Options:
    --skip-backfill   Initialize collections only, do not backfill from SQLite
    --verbose         Show more detail during backfill
"""

from __future__ import annotations

import sys
import argparse
from pathlib import Path

# ── Path bootstrap ─────────────────────────────────────────────────────────────
_AGENTS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_AGENTS_ROOT / "stock-analysis-agent" / "src"))
sys.path.insert(0, str(_AGENTS_ROOT))

from dotenv import load_dotenv
load_dotenv(_AGENTS_ROOT / "stock-analysis-agent" / ".env")


def check_chromadb() -> bool:
    """Return True if chromadb is importable, False otherwise."""
    try:
        import chromadb  # noqa: F401
        return True
    except ImportError:
        return False


def print_collection_stats(verbose: bool = False) -> None:
    """Print record counts for each ChromaDB collection."""
    from orchestrator.vector_store import (
        _get_collection,
        _COLLECTION_TRADE_MEMORIES,
        _COLLECTION_MARKET_KNOWLEDGE,
        _COLLECTION_RISK_DECISIONS,
        _CHROMA_PATH,
    )

    print(f"\n{'─' * 50}")
    print("ChromaDB Collection Stats")
    print(f"Storage: {_CHROMA_PATH}")
    print(f"{'─' * 50}")

    for name in (
        _COLLECTION_TRADE_MEMORIES,
        _COLLECTION_MARKET_KNOWLEDGE,
        _COLLECTION_RISK_DECISIONS,
    ):
        try:
            col   = _get_collection(name)
            count = col.count()
            label = f"  {name:<30}"
            print(f"{label} {count:>5} records")

            if verbose and count > 0:
                # Show first 3 document snippets
                sample = col.get(limit=3, include=["documents", "metadatas"])
                for doc, meta in zip(
                    sample.get("documents", []),
                    sample.get("metadatas", []),
                ):
                    print(f"    ↳ [{meta.get('ticker','?')}] {doc[:80]}...")
        except Exception as exc:
            print(f"  {name:<30} ERROR: {exc}")

    print(f"{'─' * 50}\n")


def main(skip_backfill: bool = False, verbose: bool = False) -> int:
    """
    Run setup steps and return 0 on success, 1 on failure.
    """

    # ── Step 1: Verify chromadb ────────────────────────────────────────────
    print("Step 1: Checking chromadb installation...")
    if not check_chromadb():
        print(
            "  ERROR: chromadb is not installed.\n"
            "  Run: pip install chromadb\n"
            "  Or:  pip install -r orchestrator/requirements.txt",
            file=sys.stderr,
        )
        return 1
    import chromadb
    print(f"  OK — chromadb {chromadb.__version__}")

    # Check OpenAI for embeddings
    import os
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        print(f"  OPENAI_API_KEY detected — will use text-embedding-3-small")
    else:
        print(
            "  OPENAI_API_KEY not set — using chromadb default embeddings\n"
            "  (Set OPENAI_API_KEY in .env for higher-quality embeddings)"
        )

    # ── Step 2: Initialize collections ────────────────────────────────────
    print("\nStep 2: Initializing ChromaDB collections...")
    try:
        from orchestrator.vector_store import initialize_collections
        initialize_collections()
        print("  OK — all three collections ready")
    except Exception as exc:
        print(f"  ERROR: {exc}", file=sys.stderr)
        return 1

    # ── Step 3: Backfill from SQLite ───────────────────────────────────────
    if skip_backfill:
        print("\nStep 3: Skipping SQLite backfill (--skip-backfill flag set)")
    else:
        print("\nStep 3: Backfilling trade_memories from SQLite...")
        try:
            from stock_agent.memory import DB_PATH
            db_path = Path(DB_PATH)

            if not db_path.exists():
                print(
                    f"  WARNING: SQLite DB not found at {db_path}\n"
                    f"  Skipping backfill — no trades to embed yet."
                )
            else:
                print(f"  SQLite DB: {db_path}")
                from orchestrator.vector_store import backfill_from_sqlite
                stats = backfill_from_sqlite()

                if stats["total"] == 0:
                    print(
                        "  No CLOSED trades found in SQLite yet.\n"
                        "  Backfill will auto-populate as trades are closed."
                    )
                else:
                    print(f"  Total closed trades: {stats['total']}")
                    print(f"  Newly embedded:      {stats['embedded']}")
                    print(f"  Skipped (errors):    {stats['skipped']}")
                    if stats["errors"] and verbose:
                        for err in stats["errors"]:
                            print(f"    ERR [{err.get('ticker')}]: {err.get('error')}")

        except Exception as exc:
            print(f"  ERROR during backfill: {exc}", file=sys.stderr)
            # Non-fatal — collections are still usable
            print("  Continuing (backfill can be retried later)...")

    # ── Step 4: Print summary stats ────────────────────────────────────────
    print("\nStep 4: Collection summary:")
    try:
        print_collection_stats(verbose=verbose)
    except Exception as exc:
        print(f"  ERROR reading stats: {exc}", file=sys.stderr)

    print("Setup complete. The vector store is ready.")
    print(
        "\nNext steps:\n"
        "  1. Register managed agents:  python scripts/register_agents.py\n"
        "  2. Test a trade pipeline:    python orchestrator/session_orchestrator.py --ticker AAPL\n"
        "  3. Import vector_store in your agent code for similarity lookup."
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Set up the Stock Copilot ChromaDB vector store."
    )
    parser.add_argument(
        "--skip-backfill",
        action="store_true",
        help="Initialize collections only, skip SQLite backfill",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show sample documents and error details",
    )
    args = parser.parse_args()

    exit_code = main(skip_backfill=args.skip_backfill, verbose=args.verbose)
    sys.exit(exit_code)
