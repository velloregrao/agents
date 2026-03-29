#!/usr/bin/env bash
# scripts/set-api-key.sh
#
# Sets AGENT_API_KEY as a permanent Container App secret on both
# python-api and stock-bot, then enables external ingress on python-api.
#
# Usage:
#   export AGENT_API_KEY="$(openssl rand -hex 32)"   # generate once
#   ./scripts/set-api-key.sh
#
# Or pass an existing key:
#   AGENT_API_KEY=your-key ./scripts/set-api-key.sh
#
# The key is stored as a Container App secret — it survives all future
# GitHub Actions deploys and never needs to be re-set unless you rotate it.

set -euo pipefail

RG="stock-bot-rg"
PYTHON_API="python-api"
BOT="stock-bot"

# ── Validate key ───────────────────────────────────────────────────────────────

if [[ -z "${AGENT_API_KEY:-}" ]]; then
  echo "❌  AGENT_API_KEY is not set."
  echo ""
  echo "Generate one with:"
  echo "    export AGENT_API_KEY=\"\$(openssl rand -hex 32)\""
  echo "Then re-run this script."
  exit 1
fi

echo "🔑  API key length: ${#AGENT_API_KEY} chars"
echo "🔧  Resource group: $RG"
echo ""

# ── python-api: set secret + wire env var ─────────────────────────────────────

echo "▶  Setting secret on $PYTHON_API..."
az containerapp secret set \
  --name "$PYTHON_API" \
  --resource-group "$RG" \
  --secrets "agent-api-key=${AGENT_API_KEY}" \
  --output none

echo "▶  Updating $PYTHON_API env var to reference secret..."
az containerapp update \
  --name "$PYTHON_API" \
  --resource-group "$RG" \
  --set-env-vars "AGENT_API_KEY=secretref:agent-api-key" \
  --output none

echo "✅  $PYTHON_API updated"
echo ""

# ── stock-bot: set secret + wire env var ──────────────────────────────────────

echo "▶  Setting secret on $BOT..."
az containerapp secret set \
  --name "$BOT" \
  --resource-group "$RG" \
  --secrets "agent-api-key=${AGENT_API_KEY}" \
  --output none

echo "▶  Updating $BOT env var to reference secret..."
az containerapp update \
  --name "$BOT" \
  --resource-group "$RG" \
  --set-env-vars "AGENT_API_KEY=secretref:agent-api-key" \
  --output none

echo "✅  $BOT updated"
echo ""

# ── python-api: open external ingress ─────────────────────────────────────────

echo "▶  Enabling external ingress on $PYTHON_API..."
az containerapp ingress update \
  --name "$PYTHON_API" \
  --resource-group "$RG" \
  --type external \
  --target-port 8000 \
  --output none

PUBLIC_URL=$(az containerapp show \
  --name "$PYTHON_API" \
  --resource-group "$RG" \
  --query properties.configuration.ingress.fqdn \
  --output tsv)

echo ""
echo "════════════════════════════════════════════════════════"
echo "✅  Done. Your public API endpoint:"
echo ""
echo "    https://${PUBLIC_URL}"
echo ""
echo "Test it:"
echo "    curl -s https://${PUBLIC_URL}/health"
echo ""
echo "Call the agent:"
echo "    curl -X POST https://${PUBLIC_URL}/agent \\"
echo "      -H 'X-API-Key: ${AGENT_API_KEY}' \\"
echo "      -H 'Content-Type: application/json' \\"
echo "      -d '{\"user_id\":\"openai\",\"platform\":\"api\",\"text\":\"Analyze AAPL\",\"thread_id\":\"1\",\"timestamp\":\"2026-03-28T00:00:00Z\"}'"
echo ""
echo "⚠️   Store your API key somewhere safe — you'll need it for external callers."
echo "     To rotate it later, just re-run this script with a new AGENT_API_KEY."
echo "════════════════════════════════════════════════════════"
