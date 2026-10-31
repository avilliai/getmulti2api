"""FastAPI application entrypoint for Multi AI 2API."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from app.api.v1.admin import router as admin_router
from app.api.v1.chat import router as chat_router
from app.api.v1.models import router as models_router
from app.api.v1.register import router as register_router
from app.core.config import resolve_project_path, settings
from app.services.account_manager import account_manager

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("getmulti2api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Multi AI 2API service...")
    stats = account_manager.get_pool_stats()
    logger.info(f"Account pool loaded: {stats['active_accounts']} active / {stats['total_accounts']} total")

    # If pool is empty and auto-register enabled, register an initial account
    if stats["active_accounts"] == 0 and settings.AUTO_REGISTER_ON_EMPTY:
        logger.info("Account pool empty, registering initial account...")
        try:
            await account_manager.get_healthy_account()
            new_stats = account_manager.get_pool_stats()
            logger.info(f"Initial account registered. Active accounts: {new_stats['active_accounts']}")
        except Exception as e:
            logger.error(f"Failed to auto-register initial account: {e}")

    yield
    logger.info("Shutting down Multi AI 2API service...")


app = FastAPI(
    title="Multi AI 2API",
    description="OpenAI-compatible 2API for web.getmulti.ai with automated registration and account pooling",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API v1 Routers
app.include_router(chat_router, prefix="/v1", tags=["Chat"])
app.include_router(models_router, prefix="/v1", tags=["Models"])
app.include_router(register_router, prefix="/v1", tags=["Registration"])
app.include_router(admin_router, prefix="/v1", tags=["Admin"])

# Convenience root aliases
app.include_router(register_router, tags=["Registration"])


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Web admin dashboard."""
    tmpl_path = resolve_project_path("app/templates/dashboard.html")
    if tmpl_path.is_file():
        return HTMLResponse(content=tmpl_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h2>Multi AI 2API Dashboard template not found.</h2>")


@app.get("/health")
async def health_check():
    """Service health check endpoint."""
    stats = account_manager.get_pool_stats()
    return {
        "status": "ok",
        "service": "getmulti2api",
        "pool": stats
    }
