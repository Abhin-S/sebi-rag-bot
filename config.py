"""
Configuration for SEBI RAG Chatbot
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file (if present)
load_dotenv()

# ─── Directories ──────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
PDF_DIR = BASE_DIR / "sebi_master_circulars"
METADATA_DIR = BASE_DIR / "sebi_metadata"
CHROMA_DIR = BASE_DIR / "chroma_db"
PROCESSED_DIR = BASE_DIR / "processed_data"

PARENT_STORE_PATH = PROCESSED_DIR / "parent_chunks.json"
DEFINITIONS_PATH = PROCESSED_DIR / "definitions.json"
CIRCULAR_INDEX_PATH = PROCESSED_DIR / "circular_index.json"

# ─── API Keys ─────────────────────────────────────────────────────────────────
# Set via environment variable or Streamlit sidebar
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# ─── Models ───────────────────────────────────────────────────────────────────
LLM_MODEL = "gemma-3-27b-it"           # Primary: Gemma 3 via Google AI Studio
LLM_FALLBACK = "gemma-2-27b-it"        # Fallback: Gemma 2 via Google AI Studio
EMBEDDING_MODEL = "all-MiniLM-L6-v2"   # Open-source, runs on CPU
LLM_TEMPERATURE = 0.1

# ─── Chunking ─────────────────────────────────────────────────────────────────
CHILD_CHUNK_SIZE = 500      # tokens (~2000 chars) — embedded for retrieval
CHILD_CHUNK_OVERLAP = 50    # tokens overlap between child chunks
PARENT_CHUNK_SIZE = 2000    # tokens (~8000 chars) — used as context
PARENT_CHUNK_OVERLAP = 200  # tokens overlap between parent chunks
CHARS_PER_TOKEN = 4         # approximate chars per token

# ─── Retrieval ────────────────────────────────────────────────────────────────
TOP_K = 5                   # Final number of documents to retrieve
MULTI_QUERY_COUNT = 3       # Number of alternate queries to generate
RRF_K = 60                  # Reciprocal Rank Fusion constant

# ─── ChromaDB Collection Names ────────────────────────────────────────────────
CHILD_COLLECTION = "sebi_child_chunks"
DEFINITIONS_COLLECTION = "sebi_definitions"
