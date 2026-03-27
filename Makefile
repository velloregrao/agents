# ─────────────────────────────────────────────────────────────────────────────
# Stock Copilot Agent — Developer Commands
# Usage: make <target>
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: help setup setup-python setup-bot test test-python test-bot test-integration \
        dev dev-bg dev-stop dev-api dev-bot kill-api kill-bot verify \
        docker-local docker-local-down deploy \
        logs-azure-bot logs-azure-api logs-local \
        clean check-env

PYTHON     := $(PWD)/stock-analysis-agent/.venv/bin/python3
UVICORN    := $(PWD)/stock-analysis-agent/.venv/bin/uvicorn
BOT_DIR    := stock-copilot-agent
API_DIR    := stock-analysis-agent
ACR        := stockbotregkava.azurecr.io
RG         := stock-bot-rg

# ── Help ──────────────────────────────────────────────────────────────────────

help:
	@echo ""
	@echo "Usage: make <target>"
	@echo ""
	@echo "Setup"
	@echo "  setup          Full setup from scratch (Python + Node)"
	@echo "  setup-python   Set up Python API virtual environment"
	@echo "  setup-bot      Install Node deps and compile TypeScript"
	@echo ""
	@echo "Tests"
	@echo "  test           Run all unit + functional tests (Python + TypeScript)"
	@echo "  test-python    Run Python tests only"
	@echo "  test-bot       Run TypeScript tests only"
	@echo "  test-integration  Run integration tests (hits real APIs)"
	@echo ""
	@echo "Local Dev"
	@echo "  dev            Start both, tail logs in terminal (Ctrl+C to stop)"
	@echo "  dev-bg         Start both in background, return to prompt"
	@echo "  dev-stop       Stop all background services"
	@echo "  dev-api        Start Python API only (foreground)"
	@echo "  dev-bot        Start Teams bot only (foreground)"
	@echo "  docker-local   Run full stack in Docker (pre-Azure validation)"
	@echo ""
	@echo "Verify"
	@echo "  verify         Check Python API health after startup"
	@echo ""
	@echo "Deploy"
	@echo "  deploy         Build, push and deploy both services to Azure"
	@echo ""
	@echo "Logs"
	@echo "  logs-azure-api  Tail Python API logs from Azure"
	@echo "  logs-azure-bot  Tail Teams bot logs from Azure"
	@echo "  logs-local      Tail Docker Compose logs"
	@echo ""
	@echo "Cleanup"
	@echo "  clean          Remove virtual env, node_modules, compiled output"
	@echo ""

# ── Setup ─────────────────────────────────────────────────────────────────────

setup: check-env setup-python setup-bot
	@echo ""
	@echo "✅ Setup complete. Run 'make test' to verify."

setup-python:
	@echo "→ Setting up Python virtual environment..."
	cd $(API_DIR) && uv venv
	cd $(API_DIR) && uv pip install --python .venv/bin/python3 -e ".[test]"
	@echo "✅ Python environment ready"

setup-bot:
	@echo "→ Installing Node dependencies..."
	cd $(BOT_DIR) && npm install
	@echo "→ Compiling TypeScript..."
	cd $(BOT_DIR) && npm run build
	@echo "✅ Bot ready"

check-env:
	@echo "→ Checking prerequisites..."
	@command -v uv     >/dev/null 2>&1 || (echo "❌ uv not found. Install: brew install uv" && exit 1)
	@command -v node   >/dev/null 2>&1 || (echo "❌ node not found. Run: nvm use 18" && exit 1)
	@command -v docker >/dev/null 2>&1 || (echo "❌ docker not found. Install Docker Desktop" && exit 1)
	@test -f $(API_DIR)/.env         || (echo "❌ Missing $(API_DIR)/.env — copy from $(API_DIR)/.env.example" && exit 1)
	@echo "✅ Prerequisites OK"

# ── Tests ─────────────────────────────────────────────────────────────────────

test: test-python test-bot
	@echo ""
	@echo "✅ All tests passed"

test-python:
	@echo "→ Running Python unit + functional tests..."
	cd $(API_DIR) && $(PYTHON) -m pytest tests/unit tests/functional -v

test-bot:
	@echo "→ Running TypeScript tests..."
	cd $(BOT_DIR) && npm test

test-integration:
	@echo "→ Running integration tests (hitting real APIs)..."
	cd $(API_DIR) && $(PYTHON) -m pytest --integration -v

# ── Local Dev ─────────────────────────────────────────────────────────────────

kill-api:
	@lsof -ti :8000 | xargs kill 2>/dev/null && echo "✅ Port 8000 freed" || echo "ℹ️  Nothing running on port 8000"

kill-bot:
	@lsof -ti :3978 | xargs kill 2>/dev/null && echo "✅ Port 3978 freed" || echo "ℹ️  Nothing running on port 3978"

dev: kill-api kill-bot
	@echo "→ Starting Python API and Teams bot..."
	@echo "   Logs below — press Ctrl+C to stop both"
	@echo ""
	@mkdir -p /tmp/agents-dev
	@# Start API in background, log to file
	@cd $(API_DIR) && \
	  set -a && . .env && set +a && \
	  $(UVICORN) stock_agent.api:app --host 127.0.0.1 --port 8000 --reload \
	  > /tmp/agents-dev/api.log 2>&1 & echo $$! > /tmp/agents-dev/api.pid
	@# Wait for API to be ready
	@echo "→ Waiting for API to start..."
	@for i in 1 2 3 4 5 6 7 8 9 10; do \
	  curl -sf http://127.0.0.1:8000/health > /dev/null 2>&1 && break; \
	  sleep 1; \
	done
	@curl -sf http://127.0.0.1:8000/health > /dev/null 2>&1 \
	  && echo "✅ API ready on http://127.0.0.1:8000" \
	  || (echo "❌ API failed to start — check logs:" && cat /tmp/agents-dev/api.log && exit 1)
	@# Start bot in background, log to file
	@cd $(BOT_DIR) && \
	  PYTHON_API_URL=http://127.0.0.1:8000 \
	  BOT_ID=$$(grep ^BOT_ID ../.env | cut -d= -f2) \
	  BOT_PASSWORD=$$(grep ^BOT_PASSWORD ../.env | cut -d= -f2) \
	  BOT_TENANT_ID=$$(grep ^BOT_TENANT_ID ../.env | cut -d= -f2) \
	  npm start \
	  > /tmp/agents-dev/bot.log 2>&1 & echo $$! > /tmp/agents-dev/bot.pid
	@echo "✅ Bot ready on port 3978"
	@echo ""
	@echo "─────────────────────────────────────"
	@echo " API logs  → tail -f /tmp/agents-dev/api.log"
	@echo " Bot logs  → tail -f /tmp/agents-dev/bot.log"
	@echo " Stop all  → make dev-stop"
	@echo "─────────────────────────────────────"
	@echo ""
	@# Tail both logs interleaved until Ctrl+C
	@trap 'make dev-stop' INT; tail -f /tmp/agents-dev/api.log /tmp/agents-dev/bot.log

dev-bg: kill-api kill-bot
	@mkdir -p /tmp/agents-dev
	@cd $(API_DIR) && \
	  set -a && . .env && set +a && \
	  $(UVICORN) stock_agent.api:app --host 127.0.0.1 --port 8000 --reload \
	  > /tmp/agents-dev/api.log 2>&1 & echo $$! > /tmp/agents-dev/api.pid
	@echo "→ Waiting for API to start..."
	@for i in 1 2 3 4 5 6 7 8 9 10; do \
	  curl -sf http://127.0.0.1:8000/health > /dev/null 2>&1 && break; \
	  sleep 1; \
	done
	@curl -sf http://127.0.0.1:8000/health > /dev/null 2>&1 \
	  && echo "✅ API ready on http://127.0.0.1:8000" \
	  || (echo "❌ API failed to start — check logs: tail -f /tmp/agents-dev/api.log" && exit 1)
	@cd $(BOT_DIR) && \
	  PYTHON_API_URL=http://127.0.0.1:8000 \
	  BOT_ID=$$(grep ^BOT_ID ../.env | cut -d= -f2) \
	  BOT_PASSWORD=$$(grep ^BOT_PASSWORD ../.env | cut -d= -f2) \
	  BOT_TENANT_ID=$$(grep ^BOT_TENANT_ID ../.env | cut -d= -f2) \
	  npm start \
	  > /tmp/agents-dev/bot.log 2>&1 & echo $$! > /tmp/agents-dev/bot.pid
	@echo "✅ Bot ready on port 3978"
	@echo ""
	@echo "─────────────────────────────────────"
	@echo " API logs  → tail -f /tmp/agents-dev/api.log"
	@echo " Bot logs  → tail -f /tmp/agents-dev/bot.log"
	@echo " Stop all  → make dev-stop"
	@echo "─────────────────────────────────────"

dev-stop:
	@echo "→ Stopping all dev services..."
	@test -f /tmp/agents-dev/api.pid && kill $$(cat /tmp/agents-dev/api.pid) 2>/dev/null || true
	@test -f /tmp/agents-dev/bot.pid && kill $$(cat /tmp/agents-dev/bot.pid) 2>/dev/null || true
	@rm -rf /tmp/agents-dev
	@echo "✅ All dev services stopped"

dev-api: kill-api
	@echo "→ Starting Python API on http://127.0.0.1:8000 (hot reload on)"
	@echo "   Press Ctrl+C to stop"
	cd $(API_DIR) && \
	  set -a && . .env && set +a && \
	  $(UVICORN) stock_agent.api:app --host 127.0.0.1 --port 8000 --reload

dev-bot: kill-bot
	@echo "→ Starting Teams bot on port 3978"
	@echo "   Make sure 'make dev-api' is running in another terminal"
	@echo "   Press Ctrl+C to stop"
	cd $(BOT_DIR) && \
	  PYTHON_API_URL=http://127.0.0.1:8000 \
	  BOT_ID=$$(grep ^BOT_ID ../.env | cut -d= -f2) \
	  BOT_PASSWORD=$$(grep ^BOT_PASSWORD ../.env | cut -d= -f2) \
	  BOT_TENANT_ID=$$(grep ^BOT_TENANT_ID ../.env | cut -d= -f2) \
	  npm start

docker-local:
	docker compose -f docker-compose.yml -f docker-compose.local.yml \
	  --env-file .env up --build

docker-local-down:
	docker compose -f docker-compose.yml -f docker-compose.local.yml down

# ── Verify ────────────────────────────────────────────────────────────────────

verify:
	@echo "→ Checking Python API health..."
	@curl -sf http://127.0.0.1:8000/health | python3 -m json.tool \
	  && echo "✅ API is healthy" \
	  || echo "❌ API not responding — is 'make dev-api' running?"

# ── Deploy ────────────────────────────────────────────────────────────────────

deploy:
	@echo "→ Running tests before deploy..."
	$(MAKE) test
	@echo "→ Logging in to ACR..."
	az acr login --name stockbotregkava
	@echo "→ Building images..."
	docker build --platform linux/amd64 -t $(ACR)/python-api:latest ./$(API_DIR)
	docker build --platform linux/amd64 -t $(ACR)/bot:latest ./$(BOT_DIR)
	@echo "→ Pushing images..."
	docker push $(ACR)/python-api:latest
	docker push $(ACR)/bot:latest
	@echo "→ Deploying to Azure Container Apps..."
	az containerapp update --name python-api --resource-group $(RG) \
	  --image $(ACR)/python-api:latest \
	  --set-env-vars "DEPLOYED_AT=$$(date +%s)"
	az containerapp update --name stock-bot --resource-group $(RG) \
	  --image $(ACR)/bot:latest \
	  --set-env-vars "DEPLOYED_AT=$$(date +%s)"
	@echo "✅ Deploy complete"

# ── Logs ─────────────────────────────────────────────────────────────────────

logs-azure-api:
	az containerapp logs show --name python-api \
	  --resource-group $(RG) --tail 50 --follow

logs-azure-bot:
	az containerapp logs show --name stock-bot \
	  --resource-group $(RG) --tail 50 --follow

logs-local:
	docker compose -f docker-compose.yml -f docker-compose.local.yml logs -f

# ── Clean ─────────────────────────────────────────────────────────────────────

clean:
	@echo "→ Removing Python virtual environment..."
	rm -rf $(API_DIR)/.venv
	@echo "→ Removing Node modules and compiled output..."
	rm -rf $(BOT_DIR)/node_modules $(BOT_DIR)/lib
	@echo "✅ Clean complete. Run 'make setup' to start fresh."
