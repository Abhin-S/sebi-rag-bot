# SEBI Regulatory Assistant

A production-grade RAG (Retrieval-Augmented Generation) chatbot over 25 SEBI (Securities and Exchange Board of India) Master Circulars. Built with a CRAG (Corrective RAG) pipeline, parent-child hierarchical chunking, table-aware PDF extraction, and Multi-Query + RAG-Fusion retrieval.

---

## Features

- **Table-aware ingestion** — pdfplumber extracts tables and converts them to Markdown, preserving structure for tabular regulations (fee schedules, penalty matrices, eligibility criteria)
- **Parent-child chunking** — small child chunks (500 tokens) are embedded for precise retrieval; large parent chunks (2000 tokens) are passed to the LLM for full context
- **Multi-Query + RAG-Fusion** — generates 3 query variants per question, retrieves independently, then re-ranks via Reciprocal Rank Fusion (RRF)
- **CRAG pipeline** — each retrieved chunk is graded for relevance; irrelevant chunks are filtered before generation
- **Hallucination check (Self-RAG)** — the generated answer is graded against source context; confidence is reported as high / medium / low
- **Regulatory metadata** — documents tagged with audience (Stock Brokers, Mutual Funds, etc.), date, ACTIVE/SUPERSEDED status, and cross-references
- **25 Master Circulars** — ~2.8M tokens covering Stock Brokers, Mutual Funds, Depositories, Investment Advisers, Research Analysts, REITs, InvITs, CRAs, and more

---

## Architecture

```
User Question
      │
      ▼
Multi-Query Generation (3 variants via LLM)
      │
      ▼
ChromaDB Similarity Search (k=5 per variant → 15 candidates)
      │
      ▼
Reciprocal Rank Fusion → Top 5 child chunks
      │
      ▼
Relevance Grading (CRAG) → filter irrelevant chunks
      │
      ▼
Parent Chunk Lookup → full context sections (~8000 chars each)
      │
      ▼
LLM Generation (Gemma 3 27B via Google AI Studio)
      │
      ▼
Hallucination Check → confidence score
      │
      ▼
Answer + Sources + Confidence
```

---

## Tech Stack

| Component | Tool |
|---|---|
| LLM (primary) | Gemma 3 27B IT via Google AI Studio |
| LLM (fallback) | Gemma 2 27B IT via Google AI Studio |
| Embeddings | `all-MiniLM-L6-v2` (sentence-transformers, CPU) |
| Vector store | ChromaDB (persistent) |
| PDF parsing | pdfplumber (table-aware) |
| Orchestration | LangChain |
| UI | Streamlit |
| API key management | python-dotenv |

---

## Project Structure

```
Sebi_Bot/
├── app.py                  # Streamlit chat interface
├── config.py               # Central configuration (models, paths, chunk sizes)
├── ingest.py               # Table-aware PDF extraction + metadata tagging
├── chunker.py              # Parent-child chunking logic
├── build_index.py          # One-time pipeline: ingest → chunk → embed → ChromaDB
├── retriever.py            # Multi-Query + RAG-Fusion + parent lookup
├── rag_chain.py            # CRAG pipeline: grade → generate → hallucination check
├── verify_build.py         # Post-build verification and ChromaDB inspection
├── requirements.txt
├── .env                    # API key (gitignored — create this yourself)
├── .gitignore
├── chroma_db/              # Vector store (gitignored — built locally)
├── processed_data/         # Parent chunks, circular index, definitions (gitignored)
└── sebi_master_circulars/  # Downloaded PDFs (gitignored)
```

---

## How to Run (First Time Setup)

Follow these steps in order. The full process takes roughly 30–40 minutes on first run (mostly the index build).

---

### Prerequisites

- Python 3.10+
- Google Chrome (required by the scraper)
- A free [Google AI Studio API key](https://aistudio.google.com/apikey)
- ~3 GB of free disk space (PDFs + vector store)

---

### Step 1 — Clone and create virtual environment

```bash
git clone <repo-url>
cd Sebi_Bot

python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux
```

### Step 2 — Install dependencies

```bash
pip install -r requirements.txt
```

This installs everything needed for both the scraper and the RAG pipeline (Selenium, pdfplumber, LangChain, ChromaDB, sentence-transformers, Streamlit).

---

### Step 3 — Add your API key

Create a `.env` file inside `Sebi_Bot/`:

```
GOOGLE_API_KEY=your_key_here
```

Get a free key at [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey). The free tier supports Gemma 3 27B and Gemma 2 27B.

> **Never commit `.env` — it is already in `.gitignore`.**

---

### Step 4 — Download SEBI Master Circulars

Run the scraper from inside `Sebi_Bot/`:

```bash
python sebi_downloader.py
```

This uses Selenium + Chrome to navigate the SEBI website, detect PDF links embedded in the PDF.js viewer, and download all available Master Circulars into `sebi_master_circulars/`. It also saves per-file metadata (date, title, circular number) to `sebi_metadata/`.

**What it downloads:** ~25 Master Circulars across all regulated entity types (Stock Brokers, Mutual Funds, Depositories, Investment Advisers, etc.) — approximately 2.1M tokens total.

**Expected runtime:** 5–15 minutes depending on network speed.

#### ⚠️ Known Limitation — Reference Document Downloading

Each SEBI Master Circular cites many other circulars by their circular ID (e.g., `SEBI/HO/MIRSD/2024/...`). The downloader has a `recursive=True` mode that was intended to follow these IDs and download the referenced documents as well (Phase 2).

**This did not work.** SEBI's website uses a dynamic AJAX-based search to look up circulars by ID, which cannot be reliably automated with Selenium — the search endpoint does not return consistent results when called programmatically. As a result, only the top-level Master Circulars are downloaded; the individual circulars they reference are not included in the corpus.

The corpus is therefore limited to the 25 Master Circulars. These are comprehensive consolidation documents (each Master Circular supersedes and incorporates all prior circulars on that topic), so coverage is still broad even without the referenced documents.

---

### Step 5 — Build the RAG index

```bash
python build_index.py
```

This runs the full ingestion pipeline:
1. Extracts text and tables from each PDF (pdfplumber, table-aware)
2. Tags metadata — audience, date, ACTIVE/SUPERSEDED status, cross-references
3. Creates parent-child chunk pairs (500-token child for retrieval, 2000-token parent for context)
4. Embeds all child chunks using `all-MiniLM-L6-v2` (runs on CPU)
5. Stores embeddings in ChromaDB at `chroma_db/`
6. Saves parent chunks and circular index to `processed_data/`

**Expected runtime:** ~20 minutes on CPU (7,085 chunks to embed).

You can verify the build succeeded with:

```bash
python verify_build.py
```

---

### Step 6 — Run the app

```bash
streamlit run app.py
```

Opens at `http://localhost:8501`. The sidebar shows the knowledge base stats (total docs, active vs superseded). Type any question about SEBI regulations in the chat input.

---

### Re-running after first setup

Once the index is built, you only need Steps 3 and 6 on subsequent runs:

```bash
# Activate venv, then:
streamlit run app.py
```

The index persists in `chroma_db/` and does not need to be rebuilt unless you add new PDFs.

---

## Index Contents (pre-built)

| Metric | Value |
|---|---|
| Documents ingested | 25 Master Circulars |
| Total pages | ~2,396 |
| Child chunks (embedded) | 7,085 |
| Parent chunks (context) | 1,344 |
| Chunks containing tables | 2,629 (37%) |
| Active circulars | 19 |
| Superseded circulars | 6 |
| Approximate token coverage | ~2.1M tokens |

---

## Example Questions

- What are the KYC requirements for stock brokers?
- What is the compensation mechanism for investor grievances?
- Explain the framework for Social Stock Exchange.
- What are the latest listing obligations for non-convertible securities?
- What are the obligations of credit rating agencies?
- What is the role of a debenture trustee?

---

## Notes

- The vector store (`chroma_db/`) and processed data (`processed_data/`) are gitignored and must be built locally by running `build_index.py`
- The app reads the API key from `.env` — never commit this file
- Confidence levels: **high** = answer fully grounded in source docs, **medium** = mostly grounded, **low** = answer may contain unsupported claims
