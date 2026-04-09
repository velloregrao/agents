"""
scripts/register_agents.py

Standalone script to register the three Stock Copilot managed agents
with the Anthropic API and save their IDs to .agent_registry.json.

This is a one-time setup step. Run it once per environment.
The operation is idempotent — if the registry already exists and all
three agents are registered, no new agents will be created.

Usage:
    python scripts/register_agents.py

Options:
    --force     Force re-registration even if the registry already exists
    --show      Print current registry without registering anything
"""

from __future__ import annotations

import sys
import json
import argparse
from pathlib import Path

# ── Path bootstrap ─────────────────────────────────────────────────────────────
_AGENTS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_AGENTS_ROOT / "stock-analysis-agent" / "src"))
sys.path.insert(0, str(_AGENTS_ROOT))

from dotenv import load_dotenv
load_dotenv(_AGENTS_ROOT / "stock-analysis-agent" / ".env")

_REGISTRY_PATH = _AGENTS_ROOT / ".agent_registry.json"


def show_registry() -> None:
    """Print the current contents of the agent registry."""
    if not _REGISTRY_PATH.exists():
        print("No agent registry found (.agent_registry.json does not exist).")
        print("Run this script without --show to register agents.")
        return

    try:
        registry = json.loads(_REGISTRY_PATH.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR reading registry: {exc}", file=sys.stderr)
        return

    print(f"\nAgent Registry ({_REGISTRY_PATH})")
    print("─" * 50)
    for role, agent_id in registry.items():
        print(f"  {role:<15} → {agent_id}")
    print()


def check_api_key() -> bool:
    """Verify ANTHROPIC_API_KEY is set before attempting registration."""
    import os
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        print(
            "ERROR: ANTHROPIC_API_KEY is not set.\n"
            "Add it to stock-analysis-agent/.env or export it in your shell.",
            file=sys.stderr,
        )
        return False
    masked = key[:8] + "..." + key[-4:]
    print(f"  ANTHROPIC_API_KEY: {masked}")
    return True


def main(force: bool = False, show: bool = False) -> int:
    """
    Register agents and return 0 on success, 1 on failure.
    """
    if show:
        show_registry()
        return 0

    print("=== Stock Copilot Agent Registration ===\n")

    # ── Check prerequisites ────────────────────────────────────────────────
    print("Checking prerequisites...")
    if not check_api_key():
        return 1

    try:
        import anthropic
        print(f"  anthropic SDK: {anthropic.__version__}")
    except ImportError:
        print(
            "  ERROR: anthropic is not installed.\n"
            "  Run: pip install -U anthropic",
            file=sys.stderr,
        )
        return 1

    # ── Force re-registration ──────────────────────────────────────────────
    if force and _REGISTRY_PATH.exists():
        print(f"\n--force flag set — deleting existing registry: {_REGISTRY_PATH}")
        _REGISTRY_PATH.unlink()

    # ── Check existing registry ────────────────────────────────────────────
    from orchestrator.managed_agents import load_agent_registry
    existing = load_agent_registry()
    if existing and not force:
        print(f"\nExisting registry found ({len(existing)} agent(s)):")
        for role, agent_id in existing.items():
            print(f"  {role:<15} → {agent_id}")

        missing = {"analysis", "risk", "portfolio"} - set(existing.keys())
        if not missing:
            print(
                "\nAll three agents are already registered. "
                "Use --force to re-register.\n"
            )
            return 0
        else:
            print(f"\nMissing agents: {missing} — registering now...")

    # ── Register agents ────────────────────────────────────────────────────
    print("\nRegistering agents with Anthropic API...")
    print("(This may take a few seconds per agent)\n")

    try:
        from orchestrator.managed_agents import get_or_create_agents
        ids = get_or_create_agents()
    except RuntimeError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        print(
            "\nIf the managed-agents beta is not yet available on your account:\n"
            "  1. Contact Anthropic support to enable the beta\n"
            "  2. Or manually create .agent_registry.json with placeholder IDs\n"
            "     and use run_analysis_session() with direct model calls instead.",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(f"\nUnexpected error during registration: {exc}", file=sys.stderr)
        return 1

    # ── Print results ──────────────────────────────────────────────────────
    print(f"\nRegistration complete. Agent IDs saved to: {_REGISTRY_PATH}\n")
    print("─" * 50)
    for key, value in ids.items():
        print(f"  {key:<15} → {value}")
    print("─" * 50)
    print(
        "\nNext steps:\n"
        "  1. Test the trade pipeline:\n"
        "       python orchestrator/session_orchestrator.py --ticker AAPL --qty 5 --side buy\n"
        "  2. Run a parallel watchlist scan:\n"
        "       python orchestrator/session_orchestrator.py --watchlist AAPL NVDA MSFT\n"
        "  3. The registry is loaded automatically by get_or_create_agents() — "
        "no further setup needed."
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Register Stock Copilot managed agents with Anthropic."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete the existing registry and re-register all agents",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Print the current registry and exit without registering",
    )
    args = parser.parse_args()

    exit_code = main(force=args.force, show=args.show)
    sys.exit(exit_code)
