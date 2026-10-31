# -*- coding: utf-8 -*-
"""Startup runner for Multi AI 2API gateway."""

import os
import sys
from app.core.config import settings

os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

def main():
    print("=" * 60)
    print("  Multi AI 2API Gateway & Account Manager")
    print("=" * 60)
    print(f"[INFO] Upstream Multi: {settings.MULTI_BASE_URL}")
    print(f"[INFO] Cloudflare Worker Domain: {settings.WORKER_DOMAIN}")
    print(f"[INFO] Outlook Account Pool: {settings.OUTLOOK_ACCOUNT_FILE}")
    print(f"[INFO] Starting FastAPI on http://{settings.HOST}:{settings.PORT} ...")
    print(f"[INFO] Dashboard: http://localhost:{settings.PORT}/")
    print(f"[INFO] OpenAPI Docs: http://localhost:{settings.PORT}/docs")
    print("=" * 60)

    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.RELOAD,
        log_level=settings.LOG_LEVEL.lower()
    )

if __name__ == "__main__":
    main()
