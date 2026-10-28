# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Parlo API + worker image (the same image runs both; see docker-entrypoint.sh)
# Build context is the repo root so the curriculum YAML can be copied in.
# ---------------------------------------------------------------------------

FROM python:3.13-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY api/requirements.txt ./
RUN pip install -r requirements.txt

# --- tests: docker compose --profile test run --rm api-test ------------------
FROM base AS test
COPY api/requirements-dev.txt ./
RUN pip install -r requirements-dev.txt
COPY api/ ./
COPY curriculum/ /app/curriculum/
CMD ["python", "-m", "pytest", "-q"]

# --- runtime ----------------------------------------------------------------
FROM base AS runtime
COPY api/ ./
COPY curriculum/ /app/curriculum/
RUN useradd --create-home --uid 1000 parlo \
    && mkdir -p /data/audio_cache /data/recordings \
    && chown -R parlo:parlo /data \
    && chmod +x docker-entrypoint.sh
USER parlo
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s --start-period=40s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["api"]
