"""
Build Vector Store — one-time indexing script
─────────────────────────────────────────────────────────────────────────────
Pipeline: Ingest PDFs → Chunk → Embed → Store in ChromaDB

Run:  python build_index.py
"""

import shutil
import sys
import time
from config import (
    CHROMA_DIR, PROCESSED_DIR, EMBEDDING_MODEL,
    CHILD_COLLECTION, DEFINITIONS_COLLECTION,
)
from ingest import process_all_pdfs
from chunker import process_all_documents


def build():
    start = time.time()

    # ══════════════════════════════════════════════════════════════════════
    #  STEP 1 — Ingest PDFs
    # ══════════════════════════════════════════════════════════════════════
    print("=" * 60)
    print("  STEP 1 / 3 — Ingesting PDFs (table-aware extraction)")
    print("=" * 60)
    all_documents, all_definitions = process_all_pdfs()

    if not all_documents:
        print("No documents found. Exiting.")
        sys.exit(1)

    # ══════════════════════════════════════════════════════════════════════
    #  STEP 2 — Parent-Child Chunking
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("  STEP 2 / 3 — Creating parent-child chunks")
    print("=" * 60)
    all_parents, all_children = process_all_documents(all_documents)

    # ══════════════════════════════════════════════════════════════════════
    #  STEP 3 — Embed & Store in ChromaDB
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("  STEP 3 / 3 — Embedding & storing in ChromaDB")
    print("=" * 60)

    # Clear existing DB
    if CHROMA_DIR.exists():
        print(f"  Removing existing vector store at {CHROMA_DIR}...")
        shutil.rmtree(CHROMA_DIR)

    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_chroma import Chroma

    print(f"  Loading embedding model: {EMBEDDING_MODEL} ...")
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)

    # ── 3a. Child chunks (main retrieval collection) ──────────────────────
    print(f"\n  Embedding {len(all_children):,} child chunks ...")
    vectorstore = Chroma(
        collection_name=CHILD_COLLECTION,
        embedding_function=embeddings,
        persist_directory=str(CHROMA_DIR),
    )

    batch_size = 200
    for i in range(0, len(all_children), batch_size):
        batch = all_children[i : i + batch_size]
        vectorstore.add_texts(
            texts=[c["text"] for c in batch],
            metadatas=[c["metadata"] for c in batch],
            ids=[c["id"] for c in batch],
        )
        done = min(i + batch_size, len(all_children))
        print(f"    {done:>6,} / {len(all_children):,} chunks embedded", end="\r")
    print()

    # ── 3b. Definitions collection ────────────────────────────────────────
    if all_definitions:
        print(f"  Embedding {len(all_definitions)} definitions ...")
        def_texts = [f"{d['term']}: {d['definition']}" for d in all_definitions]
        def_metas = [
            {
                "term": d["term"],
                "source": d["source_file"],
                "page": d["source_page"],
            }
            for d in all_definitions
        ]
        def_ids = [f"def_{i}" for i in range(len(all_definitions))]

        Chroma.from_texts(
            texts=def_texts,
            metadatas=def_metas,
            ids=def_ids,
            embedding=embeddings,
            collection_name=DEFINITIONS_COLLECTION,
            persist_directory=str(CHROMA_DIR),
        )

    # ══════════════════════════════════════════════════════════════════════
    #  Done
    # ══════════════════════════════════════════════════════════════════════
    elapsed = time.time() - start
    print(f"\n{'═' * 60}")
    print(f"  INDEX BUILD COMPLETE  ({elapsed:.0f}s)")
    print(f"{'═' * 60}")
    print(f"  Child chunks:  {len(all_children):,}")
    print(f"  Parent chunks: {len(all_parents):,}")
    print(f"  Definitions:   {len(all_definitions)}")
    print(f"  ChromaDB:      {CHROMA_DIR}")
    print(f"  Parent store:  {PROCESSED_DIR / 'parent_chunks.json'}")
    print(f"{'═' * 60}")
    print(f"\nYou can now run:  streamlit run app.py")


if __name__ == "__main__":
    build()
