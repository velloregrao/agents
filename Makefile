# ─────────────────────────────────────────────
# Stock Copilot Agent — Developer Commands
# ─────────────────────────────────────────────

# Mode 1: Local debug (no Docker)
# Start Python API locally, then press F5 in VS Code for bot
local-api:
	cd stock-analysis-agent && \
	ANTHROPIC_API_KEY=$$(grep ANTHROPIC_API_KEY .env | cut -d= -f2) \
	ALPACA_API_KEY=$$(grep ALPACA_API_KEY .env | cut -d= -f2) \
	ALPACA_API_SECRET=$$(grep ALPACA_API_SECRET .env | cut -d= -f2) \
	.venv/bin/uvicorn stock_agent.api:app --host 127.0.0.1 --port 8000 --reload

# Mode 2: Local Docker (pre-Azure validation)
docker-local:
	docker compose -f docker-compose.yml -f docker-compose.local.yml \
	  --env-file .env up --build

docker-local-down:
	docker compose -f docker-compose.yml -f docker-compose.local.yml down

# Mode 3: Deploy to Azure
deploy:
	@echo "Building bot TypeScript..."
	cd stock-copilot-agent && npm run build
	@echo "Building and pushing images..."
	docker build --platform linux/amd64 \
	  -t stockbotregkava.azurecr.io/python-api:latest \
	  ./stock-analysis-agent
	docker build --platform linux/amd64 \
	  -t stockbotregkava.azurecr.io/bot:latest \
	  ./stock-copilot-agent
	docker push stockbotregkava.azurecr.io/python-api:latest
	docker push stockbotregkava.azurecr.io/bot:latest
	@echo "Restarting Azure containers..."
	az containerapp update --name python-api \
	  --resource-group stock-bot-rg \
	  --image stockbotregkava.azurecr.io/python-api:latest
	az containerapp update --name stock-bot \
	  --resource-group stock-bot-rg \
	  --image stockbotregkava.azurecr.io/bot:latest
	@echo "Deploy complete ✅"

# Logs
logs-azure-bot:
	az containerapp logs show --name stock-bot \
	  --resource-group stock-bot-rg --tail 50 --follow

logs-azure-api:
	az containerapp logs show --name python-api \
	  --resource-group stock-bot-rg --tail 50 --follow

logs-local:
	docker compose -f docker-compose.yml -f docker-compose.local.yml logs -f
