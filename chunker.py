"""
Parent-Child Chunking for SEBI Documents
─────────────────────────────────────────────────────────────────────────────
Parent chunks (~2000 tokens) provide broad context.
Child  chunks (~500  tokens) are embedded for precise retrieval.
Tables are kept intact within chunks wherever possible.

Follows the Multi-Representation Indexing pattern from
rag_from_scratch_12_to_14.ipynb (Part 12).
"""

import re
import uuid
import json
from langchain_text_splitters import RecursiveCharacterTextSplitter
from config import (
    CHILD_CHUNK_SIZE, CHILD_CHUNK_OVERLAP,
    PARENT_CHUNK_SIZE, PARENT_CHUNK_OVERLAP,
    CHARS_PER_TOKEN, PROCESSED_DIR, PARENT_STORE_PATH,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  SECTION HEADER DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

def detect_section_header(text: str) -> str:
    """Try to detect the chapter / section header within a text chunk."""
    patterns = [
        r"(?:Chapter|CHAPTER)\s+[IVX\d]+[.:\s\-]+(.+)",
        r"(?:Part|PART)\s+[A-Z\d]+[.:\s\-]+(.+)",
        r"(?:Section|SECTION)\s+\d+[.:\s\-]+(.+)",
        r"(?:Clause|CLAUSE)\s+\d+[.:\s\-]+(.+)",
        r"(?:Annexure|ANNEXURE|Appendix|APPENDIX)\s*[A-Z0-9]*[.:\s\-]*(.*)",
        r"(?:Schedule|SCHEDULE)\s+[IVX\d]+[.:\s\-]+(.+)",
    ]
    for pat in patterns:
        m = re.search(pat, text[:600])
        if m:
            header = m.group(0).strip()
            return header[:120]
    return ""


# ═══════════════════════════════════════════════════════════════════════════════
#  PARENT-CHILD CHUNKING
# ═══════════════════════════════════════════════════════════════════════════════

def create_parent_child_chunks(doc_info: dict) -> tuple[list[dict], list[dict]]:
    """
    Split a document into parent (large) and child (small) chunks.
    Each child stores its parent_id so the parent can be fetched at query time.

    Returns (parents, children)
    """
    full_text = doc_info["full_text"]
    if not full_text.strip():
        return [], []

    # ── Base metadata attached to every chunk ─────────────────────────────
    meta_base = {
        "source": doc_info["filename"],
        "title": doc_info["title"],
        "date": doc_info.get("date", ""),
        "audience": doc_info.get("audience", "General"),
        "subject": doc_info.get("subject", ""),
        "is_latest": doc_info.get("is_latest", True),
        "status": doc_info.get("status", "ACTIVE"),
        "references": json.dumps(doc_info.get("references", [])),
    }

    # ── Splitters ─────────────────────────────────────────────────────────
    # Use page markers as primary separator so chunks respect page boundaries
    parent_splitter = RecursiveCharacterTextSplitter(
        chunk_size=PARENT_CHUNK_SIZE * CHARS_PER_TOKEN,
        chunk_overlap=PARENT_CHUNK_OVERLAP * CHARS_PER_TOKEN,
        separators=["\n\n[Page ", "\n\n", "\n", ". ", " "],
    )
    child_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHILD_CHUNK_SIZE * CHARS_PER_TOKEN,
        chunk_overlap=CHILD_CHUNK_OVERLAP * CHARS_PER_TOKEN,
        separators=["\n\n", "\n", ". ", " "],
    )

    parent_texts = parent_splitter.split_text(full_text)

    parents = []
    children = []

    for parent_text in parent_texts:
        parent_id = str(uuid.uuid4())
        section = detect_section_header(parent_text)

        # ── Extract page numbers mentioned in this parent chunk ───────────
        page_nums = re.findall(r"\[Page (\d+)\]", parent_text)
        page_range = ""
        if page_nums:
            nums = sorted(set(int(n) for n in page_nums))
            page_range = f"{nums[0]}-{nums[-1]}" if len(nums) > 1 else str(nums[0])

        parent_meta = {
            **meta_base,
            "parent_id": parent_id,
            "section": section,
            "pages": page_range,
            "chunk_type": "parent",
        }
        parents.append({
            "id": parent_id,
            "text": parent_text,
            "metadata": parent_meta,
        })

        # ── Split parent → children ──────────────────────────────────────
        child_texts = child_splitter.split_text(parent_text)

        for child_text in child_texts:
            child_id = str(uuid.uuid4())
            has_table = "|" in child_text and "---" in child_text
            child_meta = {
                **meta_base,
                "child_id": child_id,
                "parent_id": parent_id,
                "section": section,
                "pages": page_range,
                "chunk_type": "child",
                "has_table": has_table,
            }
            children.append({
                "id": child_id,
                "text": child_text,
                "metadata": child_meta,
            })

    return parents, children


# ═══════════════════════════════════════════════════════════════════════════════
#  PROCESS ALL DOCUMENTS
# ═══════════════════════════════════════════════════════════════════════════════

def process_all_documents(all_documents: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Create parent-child chunks for every ingested document.
    Also saves the parent store (parent_id → text) to disk.

    Returns (all_parents, all_children)
    """
    all_parents = []
    all_children = []

    print(f"\nChunking {len(all_documents)} documents...\n")

    for doc_info in all_documents:
        parents, children = create_parent_child_chunks(doc_info)
        all_parents.extend(parents)
        all_children.extend(children)
        print(f"  {doc_info['filename'][:55]:55s}  "
              f"{len(parents):>4} parents  {len(children):>5} children")

    # ── Persist parent store ──────────────────────────────────────────────
    parent_store = {p["id"]: p["text"] for p in all_parents}
    PROCESSED_DIR.mkdir(exist_ok=True)
    with open(PARENT_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(parent_store, f)

    print(f"\n{'─'*60}")
    print(f"Chunking complete:")
    print(f"  Parent chunks: {len(all_parents):,}")
    print(f"  Child chunks:  {len(all_children):,}")
    print(f"  Parent store:  {PARENT_STORE_PATH}")
    print(f"{'─'*60}")

    return all_parents, all_children
