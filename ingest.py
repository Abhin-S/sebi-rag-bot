"""
SEBI PDF Ingestion Pipeline
─────────────────────────────────────────────────────────────────────────────
• Table-aware text extraction via pdfplumber (tables → Markdown)
• Metadata extraction: audience, dates, references, rescission, glossary
• Temporal versioning (is_latest flag for overlapping subjects)
• Scanned-page detection
"""

import pdfplumber
import re
import json
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from config import PDF_DIR, METADATA_DIR, PROCESSED_DIR, CIRCULAR_INDEX_PATH, DEFINITIONS_PATH


# ═══════════════════════════════════════════════════════════════════════════════
#  TABLE EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════

def table_to_markdown(table_data: list[list]) -> str:
    """Convert pdfplumber table (list of rows) to a Markdown table string."""
    if not table_data or len(table_data) < 2:
        return ""

    def clean(cell):
        if cell is None:
            return ""
        return str(cell).replace("\n", " ").replace("|", "\\|").strip()

    headers = [clean(c) for c in table_data[0]]
    # Skip tables where all headers are empty
    if all(h == "" for h in headers):
        if len(table_data) > 1:
            headers = [clean(c) for c in table_data[1]]
            table_data = table_data[1:]
        else:
            return ""

    num_cols = len(headers)
    md_lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * num_cols) + " |",
    ]

    for row in table_data[1:]:
        cells = [clean(c) for c in row]
        # Pad or truncate to match header count
        while len(cells) < num_cols:
            cells.append("")
        cells = cells[:num_cols]
        md_lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(md_lines)


def extract_text_outside_tables(page, table_bboxes: list[tuple]) -> str:
    """Extract text from areas of the page that are NOT inside any table."""
    if not table_bboxes:
        return page.extract_text() or ""
    try:
        def is_outside(obj):
            ox = obj.get("x0", 0)
            oy = obj.get("top", 0)
            for (tx0, ty0, tx1, ty1) in table_bboxes:
                if tx0 - 2 <= ox <= tx1 + 2 and ty0 - 2 <= oy <= ty1 + 2:
                    return False
            return True

        filtered_page = page.filter(is_outside)
        return filtered_page.extract_text() or ""
    except Exception:
        return page.extract_text() or ""


# ═══════════════════════════════════════════════════════════════════════════════
#  PAGE-LEVEL EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════

def extract_page_content(page, page_num: int) -> dict:
    """
    Extract content from a single PDF page.
    Returns dict with: page_num, text, tables_md, has_tables, is_scanned
    """
    # ── Try finding tables ────────────────────────────────────────────────
    try:
        tables = page.find_tables()
    except Exception:
        tables = []

    # ── No tables: simple text extraction ─────────────────────────────────
    if not tables:
        text = ""
        try:
            text = page.extract_text() or ""
        except Exception:
            pass
        return {
            "page_num": page_num,
            "text": text,
            "tables_md": [],
            "has_tables": False,
            "is_scanned": len(text.strip()) < 50,
        }

    # ── With tables: separate table-text from non-table-text ──────────────
    table_bboxes = []
    for t in tables:
        try:
            table_bboxes.append(t.bbox)
        except Exception:
            pass

    non_table_text = extract_text_outside_tables(page, table_bboxes)

    table_markdowns = []
    for table in tables:
        try:
            data = table.extract()
            md = table_to_markdown(data)
            if md:
                table_markdowns.append(md)
        except Exception:
            pass

    # Combine: non-table text + markdown tables
    full_text = non_table_text.strip()
    if table_markdowns:
        full_text += "\n\n" + "\n\n".join(table_markdowns)

    return {
        "page_num": page_num,
        "text": full_text,
        "tables_md": table_markdowns,
        "has_tables": len(table_markdowns) > 0,
        "is_scanned": len(full_text.strip()) < 50,
    }


def extract_document_text(pdf_path: str | Path) -> list[dict]:
    """Extract all pages from a PDF with table-aware processing."""
    pages_data = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for i, page in enumerate(pdf.pages):
            try:
                content = extract_page_content(page, i + 1)
            except Exception:
                content = {
                    "page_num": i + 1, "text": "", "tables_md": [],
                    "has_tables": False, "is_scanned": True,
                }
            pages_data.append(content)
    return pages_data


# ═══════════════════════════════════════════════════════════════════════════════
#  METADATA EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════

def extract_audience(first_page_text: str) -> str:
    """Extract target audience from the 'To' field on page 1."""
    # Direct audience keywords from filename/content
    audience_keywords = [
        ("Mutual Fund", "Mutual Funds"),
        ("Stock Broker", "Stock Brokers"),
        ("Depositor", "Depositories"),
        ("Credit Rating", "Credit Rating Agencies (CRAs)"),
        ("Portfolio Manager", "Portfolio Managers"),
        ("Research Analyst", "Research Analysts"),
        ("Investment Adviser", "Investment Advisers"),
        ("Registrar", "Registrars to an Issue and Share Transfer Agents"),
        ("Debenture Trustee", "Debenture Trustees (DTs)"),
        ("Stock Exchange", "Stock Exchanges and Clearing Corporations"),
        ("Clearing Corporation", "Stock Exchanges and Clearing Corporations"),
        ("Infrastructure Investment Trust", "Infrastructure Investment Trusts (InvITs)"),
        ("InvIT", "Infrastructure Investment Trusts (InvITs)"),
        ("Real Estate Investment Trust", "Real Estate Investment Trusts (REITs)"),
        ("REIT", "Real Estate Investment Trusts (REITs)"),
        ("ESG Rating", "ESG Rating Providers (ERPs)"),
        ("Social Stock Exchange", "Social Stock Exchange"),
        ("Surveillance", "Stock Exchanges"),
        ("Non-convertible Securities", "Market Participants"),
        ("Listing Obligation", "Listed Entities"),
        ("Issue of Capital", "Market Participants"),
    ]
    for keyword, label in audience_keywords:
        if keyword.lower() in first_page_text.lower():
            return label

    # Try regex on "To" field
    m = re.search(
        r"(?:To|TO)\s*[,:\n]+\s*(?:All\s+)?(.+?)(?:\n\n|\n(?=[A-Z]))",
        first_page_text[:2000], re.IGNORECASE
    )
    if m:
        return m.group(1).strip()[:100]

    return "General"


def extract_date_from_filename(filename: str) -> datetime | None:
    """Parse date from filename format 'Mon_DD_YYYY_...'"""
    m = re.match(r"(\w{3})_(\d{2})_(\d{4})_", filename)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%b %d %Y")
        except ValueError:
            pass
    return None


def extract_subject(filename: str) -> str:
    """Extract the subject/topic from filename."""
    m = re.match(r"\w{3}_\d{2}_\d{4}_(.+?)\.pdf$", filename)
    if m:
        subject = m.group(1)
        subject = re.sub(r"^Master [Cc]ircular (?:for |on )", "", subject)
        return subject.strip()
    return filename


def extract_sebi_references(pages_data: list[dict]) -> list[str]:
    """Extract SEBI circular IDs referenced in the document."""
    full_text = "\n".join(p["text"] for p in pages_data)
    patterns = [
        r'SEBI/HO/[A-Z]+(?:/[A-Z0-9]+){1,6}/\d{4}/\d+',
        r'CIR/[A-Z]+(?:/[A-Z0-9]+){1,4}/\d+/\d{4}',
        r'SEBI/HO/[A-Z]+(?:/[A-Z0-9]+){1,6}/CIR/[A-Z]/\d{4}/\d+',
        r'SEBI/HO/[A-Z]+(?:/[A-Z0-9]+){1,6}/P/CIR/\d{4}/\d+',
    ]
    refs = set()
    for pat in patterns:
        for match in re.finditer(pat, full_text):
            ref = match.group(0)
            if re.search(r'/\d{4}/', ref):
                refs.add(ref)
    return sorted(refs)


def extract_rescinded_circulars(pages_data: list[dict]) -> list[str]:
    """Find rescinded circular IDs from appendix / end of document."""
    rescinded = set()
    # Look at last 20% of pages
    start = max(0, len(pages_data) - max(len(pages_data) // 5, 5))
    for page_data in pages_data[start:]:
        text = page_data["text"]
        if re.search(r"rescind|supersed|repeal|withdraw", text, re.IGNORECASE):
            for pat in [
                r'SEBI/HO/[A-Z/0-9]+/\d{4}/\d+',
                r'CIR/[A-Z/0-9]+/\d+/\d{4}',
            ]:
                rescinded.update(re.findall(pat, text))
    return sorted(rescinded)


def extract_glossary(pages_data: list[dict], source_file: str) -> list[dict]:
    """
    Find definitions / glossary sections and extract term-definition pairs.
    Looks for patterns like: "term" means ... ; or "term" refers to ...
    """
    definitions = []
    in_definitions = False

    for page_data in pages_data:
        text = page_data["text"]

        # Detect start of definitions section
        if re.search(
            r"^\s*(Definitions?|Glossary|Interpretation)\s*$",
            text, re.MULTILINE | re.IGNORECASE
        ):
            in_definitions = True

        if in_definitions:
            for m in re.finditer(
                r'["\u201c]([^"\u201d]+)["\u201d]\s*'
                r'(?:means?|refers?\s+to|shall\s+(?:mean|include)|includes?)\s+'
                r'(.+?)(?:[;.](?:\s|$)|\n\n)',
                text, re.IGNORECASE | re.DOTALL,
            ):
                term = m.group(1).strip()
                defn = re.sub(r'\s+', ' ', m.group(2).strip())
                if len(term) > 1 and len(defn) > 10:
                    definitions.append({
                        "term": term,
                        "definition": defn[:500],
                        "source_page": page_data["page_num"],
                        "source_file": source_file,
                    })

            # End of definitions if we hit a chapter/part header
            if re.search(r"^\s*(?:Chapter|CHAPTER)\s+[IVX\d]", text, re.MULTILINE):
                in_definitions = False

    return definitions


# ═══════════════════════════════════════════════════════════════════════════════
#  TEMPORAL VERSIONING
# ═══════════════════════════════════════════════════════════════════════════════

def determine_latest_versions(all_circulars: list[dict]) -> list[dict]:
    """Group circulars by subject, mark the newest as is_latest=True."""
    subject_groups = defaultdict(list)

    for c in all_circulars:
        key = c.get("subject_normalized", "")
        subject_groups[key].append(c)

    for group in subject_groups.values():
        group.sort(key=lambda x: x.get("date_parsed", ""), reverse=True)
        for i, c in enumerate(group):
            c["is_latest"] = (i == 0)
            c["status"] = "ACTIVE" if i == 0 else "SUPERSEDED"
            if len(group) > 1:
                c["version_count"] = len(group)
                c["all_versions"] = [g["filename"] for g in group]

    return all_circulars


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN INGESTION ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════════

def process_all_pdfs() -> tuple[list[dict], list[dict]]:
    """
    Main entry point: parse every PDF, extract metadata, text, tables,
    glossary, references, and rescission info.

    Returns (all_documents, all_definitions)
    """
    PROCESSED_DIR.mkdir(exist_ok=True)
    pdf_files = sorted(PDF_DIR.glob("*.pdf"))

    if not pdf_files:
        print(f"No PDFs found in {PDF_DIR}")
        return [], []

    all_documents = []
    all_definitions = []

    print(f"Ingesting {len(pdf_files)} PDFs from {PDF_DIR}\n")

    for idx, pdf_path in enumerate(pdf_files, 1):
        fname = pdf_path.name
        print(f"[{idx}/{len(pdf_files)}] {fname[:70]}")

        # Load existing downloader metadata (if available)
        meta_path = METADATA_DIR / (pdf_path.stem + ".json")
        existing_meta = {}
        if meta_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    existing_meta = json.load(f)
            except Exception:
                pass

        # ── Extract text with table-aware processing ──────────────────────
        pages_data = extract_document_text(pdf_path)

        # ── Build annotated full text ─────────────────────────────────────
        full_text = "\n\n".join(
            f"[Page {p['page_num']}]\n{p['text']}"
            for p in pages_data if p["text"].strip()
        )

        # ── Extract metadata ──────────────────────────────────────────────
        first_page_text = pages_data[0]["text"] if pages_data else ""
        audience = extract_audience(first_page_text + " " + fname)
        date_parsed = extract_date_from_filename(fname)
        subject = extract_subject(fname)
        references = extract_sebi_references(pages_data)
        rescinded = extract_rescinded_circulars(pages_data)
        glossary = extract_glossary(pages_data, fname)
        scanned_pages = [p["page_num"] for p in pages_data if p.get("is_scanned")]
        table_pages = sum(1 for p in pages_data if p["has_tables"])

        all_definitions.extend(glossary)

        doc_info = {
            "filename": fname,
            "filepath": str(pdf_path),
            "title": existing_meta.get("title", subject),
            "date": existing_meta.get("date", ""),
            "date_parsed": date_parsed.isoformat() if date_parsed else "",
            "url": existing_meta.get("url", ""),
            "pdf_url": existing_meta.get("pdf_url", ""),
            "audience": audience,
            "subject": subject,
            "subject_normalized": re.sub(r"\s+", " ", subject.lower().strip()),
            "num_pages": len(pages_data),
            "references": references,
            "rescinded_circulars": rescinded,
            "scanned_pages": scanned_pages,
            "has_tables": table_pages > 0,
            "full_text": full_text,
            "pages_data": pages_data,
        }
        all_documents.append(doc_info)

        print(f"   Pages: {len(pages_data)} | Tables: {table_pages} | "
              f"Refs: {len(references)} | Glossary: {len(glossary)} | "
              f"Audience: {audience}")

    # ── Temporal versioning ───────────────────────────────────────────────
    all_documents = determine_latest_versions(all_documents)

    # ── Rescission index ──────────────────────────────────────────────────
    rescission_index = {}
    for doc in all_documents:
        for r_id in doc.get("rescinded_circulars", []):
            rescission_index[r_id] = {
                "rescinded_by": doc["filename"],
                "status": "RESCINDED",
            }

    # ── Save circular index (without full_text / pages_data) ──────────────
    circular_index = []
    for doc in all_documents:
        entry = {k: v for k, v in doc.items() if k not in ("full_text", "pages_data")}
        circular_index.append(entry)

    with open(CIRCULAR_INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(circular_index, f, indent=2, default=str)

    # ── Save definitions ──────────────────────────────────────────────────
    with open(DEFINITIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(all_definitions, f, indent=2)

    # ── Summary ───────────────────────────────────────────────────────────
    active = sum(1 for d in all_documents if d.get("status") == "ACTIVE")
    superseded = sum(1 for d in all_documents if d.get("status") == "SUPERSEDED")
    print(f"\n{'─'*60}")
    print(f"Ingestion complete:")
    print(f"  Documents:   {len(all_documents)} ({active} active, {superseded} superseded)")
    print(f"  Definitions: {len(all_definitions)}")
    print(f"  Rescinded:   {len(rescission_index)} circular IDs")
    print(f"  Saved to:    {PROCESSED_DIR}")
    print(f"{'─'*60}")

    return all_documents, all_definitions


if __name__ == "__main__":
    process_all_pdfs()
