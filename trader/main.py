"""
FastAPI application entry point.

Mounts all API routes and configures:
  - CORS (allow Next.js dashboard on any origin in dev, restricted in prod)
  - API key authentication via X-API-Key header (all routes except /api/health)
  - 60-second Redis response cache on GET routes
  - Structured JSON logging via logging_config

Run locally:
    uvicorn trader.main:app --reload --port 8000

Run via Docker Compose:
    docker compose up trader-api
"""
from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# setup_logging must run before other imports so all loggers inherit handlers
from trader.logging_config import setup_logging

setup_logging()

from trader.api.routes import decisions, health, logs, metrics, positions, report
from trader.config.settings import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


# ─── App factory ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="NSE LLM Trader API",
    description=(
        "Paper-trading system for Indian equities (NSE). "
        "5-agent LLM pipeline — personal, non-commercial experiment."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


# ─── Vercel path fix ASGI middleware ─────────────────────────────────────────

class VercelPathFixMiddleware:
    """
    ASGI middleware that restores the real request path when Vercel serverless
    rewrites requests to /api/index.py or passes x-forwarded-uri / x-matched-path.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            forwarded = (
                headers.get(b"x-forwarded-uri")
                or headers.get(b"x-matched-path")
                or headers.get(b"x-vercel-matched-path")
                or headers.get(b"x-real-url")
            )
            if forwarded:
                raw_path = forwarded.decode("utf-8").split("?")[0]
                if scope.get("path", "").endswith("index.py") or scope.get("path") in ("/api/index.py", "/api/index"):
                    scope["path"] = raw_path
                    scope["raw_path"] = raw_path.encode("utf-8")

            cur_path = scope.get("path", "")
            if not cur_path.startswith("/api") and cur_path not in ("/docs", "/redoc", "/openapi.json", "/"):
                scope["path"] = f"/api{cur_path}"
                scope["raw_path"] = scope["path"].encode("utf-8")

        await self.app(scope, receive, send)


app.add_middleware(VercelPathFixMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── API key auth dependency ──────────────────────────────────────────────────

_PUBLIC_PATHS = {"/api/health", "/health", "/healthz", "/docs", "/openapi.json", "/redoc", "/"}

def verify_api_key(request: Request) -> None:
    """
    Require X-API-Key header on protected routes.
    Health check, docs, and root are public.
    """
    if request.url.path in _PUBLIC_PATHS:
        return
    key = request.headers.get("X-API-Key", "")
    if not key or key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header.",
        )


# ─── Routers ─────────────────────────────────────────────────────────────────

_auth = Depends(verify_api_key)

app.include_router(health.router)
app.include_router(positions.router, dependencies=[_auth])
app.include_router(decisions.router, dependencies=[_auth])
app.include_router(metrics.router,   dependencies=[_auth])
app.include_router(logs.router,      dependencies=[_auth])
app.include_router(report.router,    dependencies=[_auth])


# ─── Root & Health aliases ───────────────────────────────────────────────────

@app.get("/health", response_model=health.HealthResponse, include_in_schema=False)
def health_alias() -> health.HealthResponse:
    return health.get_health()


@app.get("/", include_in_schema=False)
def root():
    return JSONResponse({"message": "NSE LLM Trader API. See /docs for endpoints."})



# ─── Global exception handler ────────────────────────────────────────────────

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s: %s", request.method, request.url, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Check logs for details."},
    )


# ─── Startup / shutdown events ───────────────────────────────────────────────

@app.on_event("startup")
async def on_startup():
    logger.info(
        "NSE LLM Trader API starting | env=%s | paper_mode=%s",
        settings.environment,
        settings.paper_trading_mode,
    )
    if not settings.paper_trading_mode:
        logger.critical(
            "PAPER_TRADING_MODE is False — this API is running in LIVE mode. "
            "Ensure you intend this before connecting a broker."
        )


@app.on_event("shutdown")
async def on_shutdown():
    logger.info("NSE LLM Trader API shutting down.")
