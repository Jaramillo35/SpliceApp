# splice-ui — the full Streamlit app in a container.
# Build context is the repo root:  docker build -t splice-ui .
#
# Data (SECR database, tickets, transcripts) lives under /data — mount a
# volume there so it survives image upgrades (docker-compose does this).
# Meeting Transcripts capture is Windows-desktop-only by nature; in the
# container that page degrades to a transcript browser, as designed.

# ---- builder: install deps into an isolated venv (wheels only, no compiler) ----
FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt ./requirements.txt
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# ---- runtime: slim, non-root, healthchecked ----
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    SPLICE_DATA_DIR=/data \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_GLOBAL_DEVELOPMENT_MODE=false

RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p /data && chown appuser:appuser /data
WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
# The whole app: shell, pages, UI modules, engines, vendored SECR core, assets.
COPY app.py feedback_system.py ./
COPY pages ./pages
COPY ui ./ui
COPY splice ./splice
COPY secrdb ./secrdb
COPY assets ./assets
COPY vbom_legacy ./vbom_legacy

USER appuser
EXPOSE 8501
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health',timeout=2).status==200 else 1)"

CMD ["streamlit", "run", "app.py", "--server.port", "8501", "--server.address", "0.0.0.0", "--server.headless", "true"]
