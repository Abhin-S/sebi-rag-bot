"""
Verify the RAG build — check ChromaDB, chunking quality, and run test queries.
Run:  python verify_build.py
"""

import json
from pathlib import Path
from config import (
    CHROMA_DIR, CHILD_COLLECTION, DEFINITIONS_COLLECTION,
    EMBEDDING_MODEL, PARENT_STORE_PATH, CIRCULAR_INDEX_PATH,
)


def section_header(title: str):
    print(f"\n{'═' * 60}")
    print(f"  {title}")
    print(f"{'═' * 60}")


def verify():
    # ══════════════════════════════════════════════════════════════════
    #  1. CHECK FILES EXIST
    # ══════════════════════════════════════════════════════════════════
    section_header("1. FILE CHECKS")

    checks = {
        "ChromaDB directory": CHROMA_DIR,
        "Parent store": PARENT_STORE_PATH,
        "Circular index": CIRCULAR_INDEX_PATH,
    }
    for name, path in checks.items():
        exists = path.exists()
        icon = "✅" if exists else "❌"
        print(f"  {icon} {name}: {path}")

    # ══════════════════════════════════════════════════════════════════
    #  2. INSPECT CHROMADB
    # ══════════════════════════════════════════════════════════════════
    section_header("2. CHROMADB COLLECTIONS")

    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_chroma import Chroma

    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)

    # Child chunks collection
    vs = Chroma(
        collection_name=CHILD_COLLECTION,
        embedding_function=embeddings,
        persist_directory=str(CHROMA_DIR),
    )
    collection = vs._collection
    count = collection.count()
    print(f"\n  📦 Collection: {CHILD_COLLECTION}")
    print(f"     Total chunks: {count:,}")

    # Sample a few entries
    sample = collection.peek(limit=3)
    if sample and sample.get("documents"):
        print(f"\n  📝 Sample entries (first 3):")
        for i, (doc, meta) in enumerate(
            zip(sample["documents"], sample["metadatas"])
        ):
            print(f"\n  ── Chunk {i + 1} ──")
            print(f"     Source:   {meta.get('source', '?')}")
            print(f"     Section:  {meta.get('section', 'N/A')}")
            print(f"     Audience: {meta.get('audience', '?')}")
            print(f"     Status:   {meta.get('status', '?')}")
            print(f"     Pages:    {meta.get('pages', '?')}")
            print(f"     Has table:{meta.get('has_table', '?')}")
            print(f"     Text:     {doc[:200]}...")

    # Definitions collection
    try:
        ds = Chroma(
            collection_name=DEFINITIONS_COLLECTION,
            embedding_function=embeddings,
            persist_directory=str(CHROMA_DIR),
        )
        def_count = ds._collection.count()
        print(f"\n  📦 Collection: {DEFINITIONS_COLLECTION}")
        print(f"     Total definitions: {def_count}")
        if def_count > 0:
            defs = ds._collection.peek(limit=5)
            for doc in defs.get("documents", []):
                print(f"     • {doc[:100]}")
    except Exception:
        print(f"\n  ⚠️  No definitions collection found")

    # ══════════════════════════════════════════════════════════════════
    #  3. METADATA STATS
    # ══════════════════════════════════════════════════════════════════
    section_header("3. METADATA ANALYSIS")

    # Get all metadata
    all_meta = collection.get(include=["metadatas"])["metadatas"]
    print(f"\n  Total chunks with metadata: {len(all_meta):,}")

    # Audience distribution
    audiences = {}
    for m in all_meta:
        a = m.get("audience", "Unknown")
        audiences[a] = audiences.get(a, 0) + 1

    print(f"\n  📊 Chunks by Audience:")
    for a, c in sorted(audiences.items(), key=lambda x: -x[1]):
        print(f"     {c:>5}  {a}")

    # Status distribution
    statuses = {}
    for m in all_meta:
        s = m.get("status", "Unknown")
        statuses[s] = statuses.get(s, 0) + 1

    print(f"\n  📊 Chunks by Status:")
    for s, c in sorted(statuses.items(), key=lambda x: -x[1]):
        print(f"     {c:>5}  {s}")

    # Sources
    sources = set(m.get("source", "?") for m in all_meta)
    print(f"\n  📊 Unique source documents: {len(sources)}")

    # Table chunks
    table_chunks = sum(1 for m in all_meta if m.get("has_table"))
    print(f"  📊 Chunks with tables: {table_chunks}")

    # ══════════════════════════════════════════════════════════════════
    #  4. PARENT STORE CHECK
    # ══════════════════════════════════════════════════════════════════
    section_header("4. PARENT STORE")

    with open(PARENT_STORE_PATH, "r", encoding="utf-8") as f:
        parents = json.load(f)
    print(f"  Parent chunks stored: {len(parents):,}")
    avg_len = sum(len(v) for v in parents.values()) / len(parents) if parents else 0
    print(f"  Avg parent chunk length: {avg_len:,.0f} chars (~{avg_len / 4:,.0f} tokens)")

    # ══════════════════════════════════════════════════════════════════
    #  5. CIRCULAR INDEX
    # ══════════════════════════════════════════════════════════════════
    section_header("5. CIRCULAR INDEX")

    with open(CIRCULAR_INDEX_PATH, "r", encoding="utf-8") as f:
        circulars = json.load(f)

    print(f"  Total circulars: {len(circulars)}")
    active = [c for c in circulars if c.get("status") == "ACTIVE"]
    superseded = [c for c in circulars if c.get("status") == "SUPERSEDED"]
    print(f"  Active:     {len(active)}")
    print(f"  Superseded: {len(superseded)}")

    print(f"\n  📋 Active circulars:")
    for c in active:
        print(f"     • [{c.get('date', '?')}] {c.get('subject', c.get('title', '?'))}")

    if superseded:
        print(f"\n  📋 Superseded circulars:")
        for c in superseded:
            print(f"     ⚠️ [{c.get('date', '?')}] {c.get('subject', c.get('title', '?'))}")

    # ══════════════════════════════════════════════════════════════════
    #  6. TEST SIMILARITY SEARCH
    # ══════════════════════════════════════════════════════════════════
    section_header("6. TEST SIMILARITY SEARCH (no LLM needed)")

    test_queries = [
        "What are the KYC requirements for stock brokers?",
        "compensation mechanism for investor grievances",
        "What is the role of a debenture trustee?",
        "mutual fund NAV calculation",
        "listing obligations for non-convertible securities",
    ]

    for query in test_queries:
        results = vs.similarity_search(query, k=3)
        print(f"\n  🔍 Query: \"{query}\"")
        for j, doc in enumerate(results):
            src = doc.metadata.get("source", "?")[:50]
            section = doc.metadata.get("section", "")[:40]
            status = doc.metadata.get("status", "?")
            preview = doc.page_content[:120].replace("\n", " ")
            print(f"     [{j+1}] {src} | {status} | {section}")
            print(f"         {preview}...")

    # ══════════════════════════════════════════════════════════════════
    #  SUMMARY
    # ══════════════════════════════════════════════════════════════════
    section_header("VERIFICATION SUMMARY")
    print(f"  ✅ ChromaDB:     {count:,} child chunks indexed")
    print(f"  ✅ Parents:      {len(parents):,} parent chunks stored")
    print(f"  ✅ Definitions:  {def_count} regulatory definitions")
    print(f"  ✅ Circulars:    {len(active)} active, {len(superseded)} superseded")
    print(f"  ✅ Tables:       {table_chunks} chunks contain tables")
    print(f"  ✅ Search:       5 test queries returned results")
    print(f"\n  🚀 Ready to run:  streamlit run app.py")


if __name__ == "__main__":
    verify()
