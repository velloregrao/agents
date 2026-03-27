FROM python:3.11-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml .
COPY src/ src/

# Install all dependencies (includes fastapi + uvicorn + alpaca-py)
RUN uv pip install --system -e .

# Data directory for SQLite — mount Azure Files here in production
RUN mkdir -p /data

EXPOSE 8000

CMD ["uvicorn", "stock_agent.api:app", "--host", "0.0.0.0", "--port", "8000"]
