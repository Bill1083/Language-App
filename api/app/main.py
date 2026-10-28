import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .config import get_settings
from .db import SessionLocal, engine
from .logging_setup import setup_logging
from .providers.base import ProviderError, http_client
from .redis_client import get_redis
from .routers import (
    admin,
    audio,
    auth,
    conversations,
    course,
    export,
    languages,
    push,
    srs,
    stats,
    vocab,
)
from .services.ai import BudgetExceeded

setup_logging()
log = logging.getLogger("parlo.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    env = get_settings()
    env.audio_cache_dir.mkdir(parents=True, exist_ok=True)
    env.recordings_dir.mkdir(parents=True, exist_ok=True)
    if env.app_secret in ("", "change-me"):
        log.warning("APP_SECRET is not set — set it in .env before exposing this server")
    yield
    await http_client().aclose()
    await engine.dispose()


app = FastAPI(title="Parlo API", version="1.0.0", lifespan=lifespan, docs_url="/api/docs",
              openapi_url="/api/openapi.json", redoc_url=None)


@app.middleware("http")
async def access_log(request: Request, call_next):
    started = time.monotonic()
    response = await call_next(request)
    if request.url.path not in ("/healthz", "/api/v1/healthz"):
        log.info("request", extra={"method": request.method, "path": request.url.path,
                                   "status": response.status_code, "ms": int((time.monotonic() - started) * 1000)})
    return response


@app.exception_handler(BudgetExceeded)
async def budget_handler(request: Request, exc: BudgetExceeded):
    return JSONResponse({"detail": str(exc), "code": "budget_exceeded"}, status_code=429)


@app.exception_handler(ProviderError)
async def provider_handler(request: Request, exc: ProviderError):
    log.warning("provider error: %s", exc)
    return JSONResponse({"detail": "AI provider unavailable — retry.", "provider_error": str(exc)[:400],
                         "retryable": exc.retryable, "code": "provider_error"}, status_code=502)


@app.get("/healthz")
@app.get("/api/v1/healthz")
async def healthz():
    status = {"db": False, "redis": False}
    try:
        async with SessionLocal() as db:
            await db.execute(text("SELECT 1"))
        status["db"] = True
        status["redis"] = bool(await get_redis().ping())
    except Exception as e:  # pragma: no cover
        log.error("health check failed: %s", e)
    ok = all(status.values())
    return JSONResponse({"ok": ok, **status}, status_code=200 if ok else 503)


for r in (auth, languages, course, srs, vocab, audio, conversations, stats, admin, export, push):
    app.include_router(r.router, prefix="/api/v1")
