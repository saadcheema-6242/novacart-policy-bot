# NovaCart Policy Q&A Bot — Setup & Run

A RAG chatbot that answers NovaCart policy questions using **only** the files in
`policies/`, with citations. Built for Tech Fusion '26, Challenge A.

- **LLM:** **Gemini `gemini-2.5-flash` on Vertex AI (primary)** with **Groq `openai/gpt-oss-120b` as automatic fallback**.
  Switch with `LLM_PROVIDER` in `.env` (`vertex` or `groq`). Vertex auth uses Application Default Credentials:
  `gcloud auth application-default login`, and set `GCP_PROJECT` / `GCP_LOCATION` in `.env`.
  (Groq free tier caps at 8,000 tokens/min — Vertex removes that limit; the fallback keeps the bot working if Vertex is unavailable.)
- **Embeddings:** local `sentence-transformers/all-MiniLM-L6-v2` (free, offline)
- **Vector store:** FAISS
- **Backend:** FastAPI · **Frontend:** single HTML page

## Project layout
```
novacart-policy-bot/
├── policies/              the knowledge base (22 files, READ-ONLY, never edit)
├── backend/
│   ├── config.py          paths, model names, loads .env
│   ├── ingest.py          parse policies -> FAISS index   (run once)
│   ├── rules.py           file-00 conventions engine (dates, GST, versions)
│   ├── rag.py             retrieve -> prompt -> Groq answer
│   └── app.py             FastAPI server (/ask, /health, serves the UI)
├── frontend/index.html    chat UI
├── tests/test_cases.py    rules + parser tests (no key needed)
├── data/faiss_index/      built index (gitignored)
├── .env.example           copy to .env and add your Groq key
└── requirements in backend/requirements.txt
```

## 1. Install
```bash
python -m pip install -r backend/requirements.txt
```

## 2. Add your Groq key
Copy `.env.example` to `.env` and set `GROQ_API_KEY`. Get a free key at
https://console.groq.com/keys
```bash
cp .env.example .env
```
`.env` is gitignored and never committed.

## 3. Build the index (run once, re-run only if policies change)
```bash
python backend/ingest.py
```
First run downloads the embedding model (~90 MB). Produces 272 chunks from 22 files.

## 4. Run the server
From the repository root `novacart-policy-bot/`:

**Option A (Shortcut):**
```powershell
.\run.ps1
# or double-click run.bat
```

**Option B (Direct Python command):**
```powershell
$env:PYTHONUTF8="1"
& 'C:\Users\HP\AppData\Local\Python\pythoncore-3.14-64\python.exe' -m uvicorn backend.app:app --port 8000
```
Open **http://localhost:8000**

## Quick checks (no Groq key required)
```bash
python tests/test_cases.py
```
```bash
python backend/rules.py
```

## Ask from the command line (needs the key)
```bash
python backend/rag.py "When can I return electronics delivered 2026-03-01 (change of mind)?"
```

## How the design handles the tricky cases
- **Two returns policies (01 vs 02):** both are indexed with their
  `effective_date`/`scope`; the prompt applies file-00 §4 precedence and names
  which version it used. `rules.resolve_precedence()` encodes the same logic.
- **Future file (21, effective 2027-02-01):** `rules.filter_in_force()` and the
  prompt drop any file not yet in force on the question's contact date.
- **Planted instructions** (e.g. file 12 line 26, file 06's table row telling the
  bot to say shipping is always free / codes always combine): the excerpts are
  indexed as-is, but the system prompt tells the model to treat excerpts as data
  and obey only numbered policy items, so it follows the real rule.
- **Money/dates:** `rules.py` does half-up rounding per step, GST = price×18÷118,
  the checkout order, "N days from delivery", full-months counting, and business
  days — all driven by dates in the question, never the system clock.
```
