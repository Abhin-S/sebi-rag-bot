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
- **25 Master Circulars** — ~2.1M tokens covering Stock Brokers, Mutual Funds, Depositories, Investment Advisers, Research Analysts, REITs, InvITs, CRAs, and more

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

## Setup

### 1. Clone and create virtual environment

```bash
git clone <repo-url>
cd Sebi_Bot
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Add your API key

Create a `.env` file in the `Sebi_Bot/` directory:

```
GOOGLE_API_KEY=your_key_here
```

Get a free key at [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)

### 4. Add PDFs

Place SEBI Master Circular PDFs in `sebi_master_circulars/`. You can use `sebi_downloader.py` (in the repo root) to download them automatically.

### 5. Build the index

```bash
python build_index.py
```

This ingests all PDFs, extracts text and tables, creates parent-child chunks, embeds child chunks, and stores everything in ChromaDB. Takes ~20 minutes on CPU for 25 documents.

### 6. Run the app

```bash
streamlit run app.py
```

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
