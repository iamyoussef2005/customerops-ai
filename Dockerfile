FROM python:3.12.15-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml README.md requirements.lock ./
COPY src ./src
RUN python -m pip install --no-cache-dir -c requirements.lock . \
    && useradd --create-home --uid 10001 customerops \
    && mkdir -p /app/.local/rag \
    && chown -R customerops:customerops /app/.local
COPY alembic.ini ./
COPY alembic ./alembic
USER customerops
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "customerops_ai.main:app", "--host", "0.0.0.0", "--port", "8000"]
