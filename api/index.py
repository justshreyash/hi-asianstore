"""
Vercel Serverless Function Entrypoint
Exposes the FastAPI application for Vercel Serverless Python.
"""

import sys
import os
import traceback
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from api.app import app
except Exception as e:
    import logging
    logging.exception("Failed to load FastAPI app:")
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    app = FastAPI(title="Error Fallback App")

    @app.api_route("/{path_name:path}", methods=["GET", "POST", "PUT", "DELETE"])
    def error_fallback(path_name: str):
        return JSONResponse(
            status_code=500,
            content={
                "error": "FastAPI Startup Failure",
                "detail": str(e),
                "traceback": traceback.format_exc()
            }
        )
