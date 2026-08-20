# splice-api — multi-stage image for the FastAPI gateway over the Splice engines.
# Build context is the Splice repo root:  docker build -f splice_api/Dockerfile -t splice-api .

# ---- builder: install deps into an isolated venv (wheels only, no compiler) ----
FROM python:3.12-slim AS builder
WORKDIR /app
COPY splice_api/requirements-runtime.txt ./requirements-runtime.txt
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/venv/bin/pip install --no-cache-dir -r requirements-runtime.txt

# ---- runtime: slim, non-root, healthchecked ----
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PATH="/opt/venv/bin:$PATH"

RUN useradd --create-home --uid 10001 appuser
WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
# Only what the service needs: the engines and the API layer (no UIs, tests, or data).
COPY splice ./splice
COPY splice_api ./splice_api

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=2).status==200 else 1)"

CMD ["uvicorn", "splice_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
