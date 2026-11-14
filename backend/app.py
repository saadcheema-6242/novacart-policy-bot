"""FastAPI backend for the NovaCart Policy Q&A bot.

Serves the HTML chat UI and a JSON endpoint the UI calls.

Run from the project root:
    uvicorn backend.app:app --reload --port 8000
then open http://localhost:8000
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Make the backend package importable no matter how the server is launched
# (uvicorn backend.app:app from the project root, or uvicorn app:app from here).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import config
import rag

FRONTEND_DIR = config.PROJECT_ROOT / "frontend"
PRESENTATION_DIR = config.PROJECT_ROOT / "presentation"

app = FastAPI(title="NovaCart Policy Q&A Bot")

# Allow localhost (any port) and file:// ('null' origin) for local web UI access.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["null"],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1500, description="Customer question text")
    k: int | None = Field(default=None, ge=1, le=100, description="Max documents to retrieve")


class AskResponse(BaseModel):
    answer: str
    citations: list[str]
    sources: list[dict]


@app.get("/health")
def health() -> dict:
    primary = config.GEMINI_MODEL if config.LLM_PROVIDER == "vertex" else config.LLM_MODEL
    return {
        "status": "ok",
        "provider": config.LLM_PROVIDER,
        "primary_model": primary,
        "fallback": config.LLM_MODEL if (config.LLM_PROVIDER == "vertex" and config.GROQ_API_KEY) else None,
    }


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    result = rag.answer(req.question, k=req.k)
    return AskResponse(**result)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get("/presentation")
def presentation() -> FileResponse:
    return FileResponse(str(PRESENTATION_DIR / "index.html"))
