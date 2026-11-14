"""Central configuration for the NovaCart Policy Q&A bot.

LLM  -> Groq, via its OpenAI-compatible endpoint (chat only).
Embeddings -> local HuggingFace model (Groq has no embeddings API).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# --- Paths -----------------------------------------------------------------
# backend/config.py  ->  project root is one level up.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
POLICIES_DIR = PROJECT_ROOT / "policies"
DATA_DIR = PROJECT_ROOT / "data"
FAISS_INDEX_DIR = DATA_DIR / "faiss_index"

# Load .env from the project root if present.
load_dotenv(PROJECT_ROOT / ".env")

# --- LLM provider ----------------------------------------------------------
# "vertex" = Gemini on Vertex AI (primary); Groq is used as automatic fallback.
# "groq"   = Groq only.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "vertex").lower()
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))

# --- Gemini via Vertex AI (primary) ----------------------------------------
# Auth uses Application Default Credentials (gcloud auth application-default
# login) or GOOGLE_APPLICATION_CREDENTIALS. Project/location fall back to the
# gcloud defaults when left blank.
GCP_PROJECT = os.getenv("GCP_PROJECT", "")
GCP_LOCATION = os.getenv("GCP_LOCATION", "us-central1")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# --- Groq (fallback, and primary when LLM_PROVIDER=groq) -------------------
# Groq speaks the OpenAI API, so we point langchain-openai at Groq's base URL.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
# List what your key can use:  python backend/list_models.py
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")

# --- Embeddings (local, free, offline) -------------------------------------
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

# --- Retrieval -------------------------------------------------------------
# Each of the two retrievers (BM25 keyword + FAISS vector) fetches this many;
# their results are fused, then expanded and capped at MAX_CONTEXT_DOCS.
RETRIEVAL_K = int(os.getenv("RETRIEVAL_K", "12"))
# Ample context allowance for Gemini 2.5 Flash and modern LLMs to hold
# all required policy sections, coupled files, and cross-references.
MAX_CONTEXT_DOCS = int(os.getenv("MAX_CONTEXT_DOCS", "160"))

# --- LLM robustness --------------------------------------------------------
# Retries on transient errors incl. Groq 429 rate limits (exponential backoff).
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "5"))


def require_groq_key() -> str:
    """Return the Groq API key or raise a clear error if it is missing."""
    if not GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return GROQ_API_KEY
