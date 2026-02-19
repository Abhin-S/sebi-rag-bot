"""
Helper script to analyze downloaded SEBI documents
Shows statistics, reference graph, and coverage analysis
"""

import json
import os
from collections import Counter, defaultdict
from datetime import datetime

METADATA_DIR = "sebi_metadata"
DOWNLOAD_DIR = "sebi_master_circulars"

def load_metadata():
    """Load all metadata files"""
    metadata_files = []
    for filename in os.listdir(METADATA_DIR):
        if filename.endswith('.json') and filename not in ['downloaded_documents.json', 'document_references.json']:
            filepath = os.path.join(METADATA_DIR, filename)
            with open(filepath, 'r', encoding='utf-8') as f:
                metadata_files.append(json.load(f))
    return metadata_files

def check_pdf_type(pdf_path):
    """Check if PDF is text-based or scanned"""
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            if len(pdf.pages) == 0:
                return "empty"
            
            # Sample first page
            text = pdf.pages[0].extract_text() or ""
            chars_per_page = len(text)
            
            if chars_per_page < 50:
                return "scanned"
            else:
                return "text"
    except:
        return "unknown"

def analyze_documents():
    """Analyze downloaded documents and show statistics"""
    
    if not os.path.exists(METADATA_DIR):
        print("❌ Metadata directory not found. Run sebi_downloader.py first.")
        return
    
    # Load tracker
    tracker_file = os.path.join(METADATA_DIR, "downloaded_documents.json")
    if os.path.exists(tracker_file):
        with open(tracker_file, 'r', encoding='utf-8') as f:
            tracker = json.load(f)
    else:
        tracker = {"downloaded_urls": [], "downloaded_circular_numbers": [], "total_tokens_estimated": 0, "total_pages": 0}
    
    # Load references
    ref_file = os.path.join(METADATA_DIR, "document_references.json")
    if os.path.exists(ref_file):
        with open(ref_file, 'r', encoding='utf-8') as f:
            references = json.load(f)
    else:
        references = {}
    
    # Load all metadata
    metadata_list = load_metadata()
    
    print("=" * 80)
    print("📊 SEBI Document Collection Analysis")
    print("=" * 80)
    
    # Basic stats
    print(f"\n📁 Total Documents Downloaded: {len(metadata_list)}")
    print(f"🔗 Total URLs Processed: {len(tracker['downloaded_urls'])}")
    print(f"📋 Total Circular Numbers Tracked: {len(tracker.get('downloaded_circular_numbers', []))}")
    
    # Token statistics
    total_tokens = tracker.get('total_tokens_estimated', 0)
    total_pages = tracker.get('total_pages', 0)
    if total_tokens > 0:
        print(f"\n📊 Token Statistics:")
        print(f"   - Total estimated tokens: {total_tokens:,}")
        print(f"   - Total pages: {total_pages:,}")
        if total_pages > 0:
            print(f"   - Average tokens per page: {total_tokens/total_pages:.0f}")
    
    # Source breakdown
    sources = Counter([m.get('source', 'unknown') for m in metadata_list])
    print(f"\n📈 Documents by Source:")
    for source, count in sources.items():
        print(f"   - {source}: {count}")
    
    # Date analysis
    dates = [m.get('date', '') for m in metadata_list if m.get('date')]
    if dates:
        print(f"\n📅 Date Range:")
        print(f"   - Oldest: {min(dates)}")
        print(f"   - Newest: {max(dates)}")
    
    # Reference graph analysis
    if references:
        print(f"\n🔗 Reference Graph Analysis:")
        print(f"   - Documents with references: {len(references)}")
        
        total_refs = sum(len(refs) for refs in references.values())
        print(f"   - Total references found: {total_refs}")
        
        if references:
            avg_refs = total_refs / len(references)
            print(f"   - Average references per document: {avg_refs:.1f}")
        
        # Most referenced documents
        all_refs = []
        for refs in references.values():
            all_refs.extend(refs)
        
        if all_refs:
            ref_counter = Counter(all_refs)
            print(f"\n🔝 Top 10 Most Referenced Circulars:")
            for circular, count in ref_counter.most_common(10):
                print(f"   - {circular[:60]}: {count} times")
    
    # Documents with most outgoing references
    if references:
        print(f"\n📤 Documents with Most Outgoing References:")
        sorted_refs = sorted(references.items(), key=lambda x: len(x[1]), reverse=True)[:10]
        for doc, refs in sorted_refs:
            print(f"   - {doc[:60]}: {len(refs)} references")
    
    # File size analysis
    if os.path.exists(DOWNLOAD_DIR):
        pdf_files = [os.path.join(DOWNLOAD_DIR, f) for f in os.listdir(DOWNLOAD_DIR) if f.endswith('.pdf')]
        if pdf_files:
            total_size = sum(os.path.getsize(f) for f in pdf_files) / (1024 * 1024)  # MB
            print(f"\n💾 Storage:")
            print(f"   - Total size: {total_size:.2f} MB")
            print(f"   - Average file size: {total_size/len(pdf_files):.2f} MB")
            
            # Check PDF types (text vs scanned)
            print(f"\n📄 PDF Type Analysis:")
            pdf_types = {"text": 0, "scanned": 0, "unknown": 0, "empty": 0}
            sample_size = min(20, len(pdf_files))  # Sample first 20 to avoid long processing
            for pdf_file in pdf_files[:sample_size]:
                pdf_type = check_pdf_type(pdf_file)
                pdf_types[pdf_type] += 1
            
            total_checked = sum(pdf_types.values())
            if total_checked > 0:
                print(f"   - Sample size: {total_checked} PDFs")
                print(f"   - Text-based PDFs: {pdf_types['text']} ({pdf_types['text']/total_checked*100:.1f}%)")
                print(f"   - Scanned/Image PDFs: {pdf_types['scanned']} ({pdf_types['scanned']/total_checked*100:.1f}%)")
                if pdf_types['scanned'] > 0:
                    print(f"   ⚠️  Note: Scanned PDFs may need OCR for accurate text extraction")
                if pdf_types['unknown'] > 0:
                    print(f"   - Unknown type: {pdf_types['unknown']}")
    
    # Depth analysis (for recursively downloaded docs)
    depth_counter = Counter([m.get('depth', 0) for m in metadata_list])
    if any(d > 0 for d in depth_counter.keys()):
        print(f"\n🌳 Recursive Download Depth:")
        for depth, count in sorted(depth_counter.items()):
            level = "Original" if depth == 0 else f"Level {depth}"
            print(f"   - {level}: {count} documents")
    
    # Document type analysis (from titles)
    doc_types = []
    for m in metadata_list:
        title = m.get('title', '').lower()
        if 'research analyst' in title:
            doc_types.append('Research Analysts')
        elif 'investment advis' in title:
            doc_types.append('Investment Advisers')
        elif 'portfolio manager' in title:
            doc_types.append('Portfolio Managers')
        elif 'mutual fund' in title:
            doc_types.append('Mutual Funds')
        elif 'debenture' in title:
            doc_types.append('Debentures')
        elif 'stock exchange' in title:
            doc_types.append('Stock Exchanges')
        else:
            doc_types.append('Other')
    
    if doc_types:
        type_counter = Counter(doc_types)
        print(f"\n📚 Documents by Topic:")
        for doc_type, count in type_counter.most_common():
            print(f"   - {doc_type}: {count}")
    
    print("\n" + "=" * 80)
    
    # Save detailed analysis
    analysis = {
        "generated_at": datetime.now().isoformat(),
        "total_documents": len(metadata_list),
        "total_tokens": total_tokens,
        "total_pages": total_pages,
        "sources": dict(sources),
        "date_range": {"oldest": min(dates) if dates else None, "newest": max(dates) if dates else None},
        "reference_stats": {
            "documents_with_refs": len(references),
            "total_references": sum(len(refs) for refs in references.values()),
        },
        "storage_mb": total_size if os.path.exists(DOWNLOAD_DIR) and pdf_files else 0,
        "depth_distribution": dict(depth_counter),
        "topic_distribution": dict(Counter(doc_types))
    }
    
    analysis_file = os.path.join(METADATA_DIR, "collection_analysis.json")
    with open(analysis_file, 'w', encoding='utf-8') as f:
        json.dump(analysis, f, indent=2)
    
    print(f"📊 Detailed analysis saved to: {analysis_file}")
    print("=" * 80)

def find_missing_references():
    """Find references that were mentioned but not downloaded"""
    ref_file = os.path.join(METADATA_DIR, "document_references.json")
    tracker_file = os.path.join(METADATA_DIR, "downloaded_documents.json")
    
    if not os.path.exists(ref_file):
        print("\nNo reference file found.")
        return
    
    with open(ref_file, 'r', encoding='utf-8') as f:
        references = json.load(f)
    
    with open(tracker_file, 'r', encoding='utf-8') as f:
        tracker = json.load(f)
    
    downloaded_circulars = set(tracker.get('downloaded_circular_numbers', []))
    
    all_mentioned = set()
    for refs in references.values():
        all_mentioned.update(refs)
    
    missing = all_mentioned - downloaded_circulars
    
    if missing:
        print(f"\n⚠️  Found {len(missing)} referenced circulars that weren't downloaded:")
        for i, circ in enumerate(sorted(missing)[:20], 1):
            print(f"   {i}. {circ}")
        if len(missing) > 20:
            print(f"   ... and {len(missing) - 20} more")
    else:
        print("\n✅ All referenced circulars were successfully downloaded!")

if __name__ == "__main__":
    analyze_documents()
    find_missing_references()
