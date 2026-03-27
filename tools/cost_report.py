#!/usr/bin/env python3
"""
Cost Report Agent — fetches actual spend from Azure Cost Management
and summarizes all resource costs for the Stock Copilot stack.

Usage:
    python cost_report.py
    python cost_report.py --days 7
    python cost_report.py --days 30
"""

import argparse
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone

# ── Config ────────────────────────────────────────────────────────────────────
SUBSCRIPTION_ID = os.getenv("AZURE_SUBSCRIPTION_ID", "")
RESOURCE_GROUP = os.getenv("AZURE_RESOURCE_GROUP", "stock-bot-rg")


# ── Azure CLI helpers ─────────────────────────────────────────────────────────

def az(args: list[str]) -> dict | list | None:
    """Run an az CLI command and return parsed JSON output."""
    try:
        result = subprocess.run(
            ["az"] + args + ["--output", "json"],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout) if result.stdout.strip() else None
    except subprocess.CalledProcessError as e:
        print(f"  [warn] az command failed: {' '.join(args)}")
        if e.stderr:
            print(f"         {e.stderr.strip()[:200]}")
        return None
    except json.JSONDecodeError:
        return None


def get_cost_by_resource(days: int) -> list[dict]:
    """Query Azure Cost Management for actual spend broken down by resource."""
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=days)

    data = az([
        "consumption", "usage", "list",
        "--subscription", SUBSCRIPTION_ID,
        "--start-date", str(start_date),
        "--end-date", str(end_date),
    ])
    return data or []


def get_resource_group_resources() -> list[dict]:
    """List all resources in the resource group."""
    return az([
        "resource", "list",
        "--resource-group", RESOURCE_GROUP,
    ]) or []


def get_container_app_details(app_name: str) -> dict | None:
    """Get Container App details including current image."""
    return az([
        "containerapp", "show",
        "--name", app_name,
        "--resource-group", RESOURCE_GROUP,
    ])


def get_acr_details() -> dict | None:
    """Get Container Registry details and tier."""
    registries = az([
        "acr", "list",
        "--resource-group", RESOURCE_GROUP,
    ])
    return registries[0] if registries else None


# ── Cost aggregation ──────────────────────────────────────────────────────────

def _parse_cost(record: dict) -> float:
    """Extract numeric cost from a usage record, handling 'None' strings."""
    for key in ("pretaxCost", "cost", "effectivePrice"):
        raw = record.get(key)
        if raw is None or raw == "None" or raw == "":
            continue
        try:
            return float(raw)
        except (ValueError, TypeError):
            continue
    return 0.0


def aggregate_costs(usage_records: list[dict]) -> dict[str, float]:
    """Sum pretax cost by resource name."""
    totals: dict[str, float] = {}
    for record in usage_records:
        name = record.get("instanceName") or record.get("productName") or "Unknown"
        if "/" in name:
            name = name.split("/")[-1]
        cost = _parse_cost(record)
        totals[name] = totals.get(name, 0) + cost
    return dict(sorted(totals.items(), key=lambda x: x[1], reverse=True))


def aggregate_by_service(usage_records: list[dict]) -> dict[str, float]:
    """Sum pretax cost by service/meter category."""
    totals: dict[str, float] = {}
    for record in usage_records:
        service = record.get("consumedService") or record.get("meterCategory") or "Unknown"
        cost = _parse_cost(record)
        totals[service] = totals.get(service, 0) + cost
    return dict(sorted(totals.items(), key=lambda x: x[1], reverse=True))


# ── Formatting ────────────────────────────────────────────────────────────────

def fmt_usd(amount: float) -> str:
    if amount == 0:
        return "$0.00"
    if amount < 0.01:
        return f"<$0.01"
    return f"${amount:.2f}"


def print_section(title: str) -> None:
    print(f"\n{'─' * 55}")
    print(f"  {title}")
    print(f"{'─' * 55}")


# ── Main report ───────────────────────────────────────────────────────────────

def run_report(days: int) -> None:
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=days)

    print()
    print("━" * 55)
    print("  Stock Copilot — Cost Report")
    print(f"  Period: {start_date} → {end_date} ({days} days)")
    print("━" * 55)

    # ── Azure resources ───────────────────────────────────────────────────────
    print_section("Azure Resources")

    resources = get_resource_group_resources()
    resource_types: dict[str, list[str]] = {}
    for r in resources:
        rtype = r.get("type", "unknown")
        resource_types.setdefault(rtype, []).append(r.get("name", ""))

    if resources:
        print(f"\n  Resources in '{RESOURCE_GROUP}':")
        for rtype, names in resource_types.items():
            short = rtype.split("/")[-1]
            print(f"    {short}: {', '.join(names)}")
    else:
        print("  (could not list resources)")

    # Container Apps detail
    for app_name in ["python-api", "stock-bot"]:
        app = get_container_app_details(app_name)
        if app:
            try:
                image = app["properties"]["template"]["containers"][0]["image"]
                tag = image.split(":")[-1][:12] if ":" in image else "latest"
                replicas = app["properties"]["template"].get("scale", {})
                min_r = replicas.get("minReplicas", 0)
                max_r = replicas.get("maxReplicas", 10)
                print(f"\n  {app_name}:")
                print(f"    image tag : {tag}")
                print(f"    replicas  : {min_r} – {max_r}")
            except (KeyError, IndexError):
                pass

    acr = get_acr_details()
    if acr:
        print(f"\n  Container Registry ({acr.get('name', '')}):")
        print(f"    tier: {acr.get('sku', {}).get('name', 'unknown')}")

    # ── Azure cost data ───────────────────────────────────────────────────────
    print_section("Azure Actual Spend")
    print(f"  Fetching usage data ({days} days)... ", end="", flush=True)

    usage = get_cost_by_resource(days)
    print(f"got {len(usage)} records")

    if usage:
        by_service = aggregate_by_service(usage)
        total_azure = sum(by_service.values())

        print(f"\n  By service:")
        for service, cost in by_service.items():
            if cost >= 0.001:
                print(f"    {service:<40} {fmt_usd(cost):>8}")
        print(f"  {'─' * 50}")
        print(f"  {'AZURE TOTAL':<40} {fmt_usd(total_azure):>8}")

        # Per-day rate
        if days > 0:
            daily = total_azure / days
            print(f"\n  Daily rate : {fmt_usd(daily)}/day")
            print(f"  Projected  : {fmt_usd(daily * 30)}/month")
    else:
        print("\n  No usage data returned.")
        print("  (Free tier usage may not appear in consumption API)")
        print("\n  Estimated Azure costs based on configured tiers:")
        print(f"    Container Apps (python-api)          ~$3–8/month")
        print(f"    Container Apps (stock-copilot-agent) ~$3–8/month")
        print(f"    Container Registry (Basic tier)      $5.00/month")
        print(f"    Log Analytics                        ~$2–5/month")
        print(f"    Azure Bot Service (F0 free)          $0.00/month")
        print(f"  {'─' * 50}")
        print(f"    Estimated Total                      ~$13–26/month")

    # ── External services (static/free tier) ─────────────────────────────────
    print_section("External Services")

    ext_services = [
        ("Anthropic Claude API",   "Pay-per-token", "~$1–40/month (usage-based)"),
        ("Alpaca (paper trading)", "Free",           "$0.00"),
        ("Brave Search API",       "Free (2K req)",  "$0.00"),
        ("ngrok",                  "Free tier",      "$0.00"),
        ("GitHub Actions",         "Free (2K min)",  "$0.00"),
    ]

    print()
    for name, tier, cost in ext_services:
        print(f"  {name:<35} {tier:<20} {cost}")

    print(f"\n  Note: Anthropic cost depends on query volume.")
    print(f"        ~$0.01–0.08 per analyze/research call (Sonnet 4.6)")
    print(f"        Use 'make test' to avoid accidental API calls in dev.")

    # ── Summary ───────────────────────────────────────────────────────────────
    print_section("Summary")
    print()
    print(f"  {'Service':<35} {'Est. Monthly':>12}")
    print(f"  {'─' * 48}")
    print(f"  {'Azure (all resources)':<35} {'$13–26':>12}")
    print(f"  {'Anthropic API (light use)':<35} {'$1–5':>12}")
    print(f"  {'Anthropic API (moderate use)':<35} {'$5–20':>12}")
    print(f"  {'All other services':<35} {'$0':>12}")
    print(f"  {'─' * 48}")
    print(f"  {'TOTAL (light use)':<35} {'~$14–31':>12}")
    print(f"  {'TOTAL (moderate use)':<35} {'~$18–46':>12}")
    print()
    print("━" * 55)
    print()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stock Copilot cost report")
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days to look back (default: 30)",
    )
    args = parser.parse_args()
    run_report(args.days)
