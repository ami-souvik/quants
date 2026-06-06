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
    docker-compose up trader-api
"""
from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# setup_logging must run before other imports so all loggers inherit handlers
from trader.logging_config import setup_logging

setup_logging()

from trader.api.routes import decisions, health, logs, metrics, positions
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


# ─── CORS ────────────────────────────────────────────────────────────────────

_ALLOWED_ORIGINS = (
    ["*"]
    if settings.environment == "development"
    else [
        "https://your-vercel-app.vercel.app",  # replace with actual Vercel URL
        "http://localhost:3000",
    ]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


# ─── API key auth dependency ──────────────────────────────────────────────────

def verify_api_key(request: Request) -> None:
    """
    Require X-API-Key header on all routes except /api/health.
    Health check is public so uptime monitors can reach it without auth.
    """
    if request.url.path == "/api/health":
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


# ─── Root redirect ───────────────────────────────────────────────────────────

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
