FROM python:3.11-slim

WORKDIR /app

RUN pip install uv

# Build context is the repo root (docker build -f stock-analysis-agent/Dockerfile .)
# so paths are relative to agents/.
COPY stock-analysis-agent/pyproject.toml .
COPY stock-analysis-agent/src/ src/

# orchestrator/ is imported by api.py at runtime — must be present in the image.
# api.py computes _AGENTS_ROOT and inserts /app into sys.path, so placing
# orchestrator/ at /app/orchestrator/ makes it importable.
COPY orchestrator/ orchestrator/
COPY config/ config/

# ipo-watch/ is imported by orchestrator/scheduler.py and api.py at runtime.
# Profiles (JSON) and signal/alert modules must be present in the image.
COPY ipo-watch/ ipo-watch/

# Install all dependencies (includes fastapi + uvicorn + alpaca-py)
RUN uv pip install --system -e .

# Data directory for SQLite — mount Azure Files here in production
RUN mkdir -p /data

EXPOSE 8000

CMD ["uvicorn", "stock_agent.api:app", "--host", "0.0.0.0", "--port", "8000"]
