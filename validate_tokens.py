"""Validate token estimation accuracy by comparing against actual full text extraction"""
import pdfplumber, os

pdf_dir = 'sebi_master_circulars'
pdfs = sorted(os.listdir(pdf_dir))

total_chars = 0
total_pages = 0
total_estimated = 0

print(f"{'File':<55} {'Pg':>4} {'ActTok':>9} {'EstTok':>9} {'Diff':>7}")
print("-" * 90)

for pdf in pdfs:
    path = os.path.join(pdf_dir, pdf)
    try:
        with pdfplumber.open(path) as p:
            pages = len(p.pages)
            chars = 0
            for page in p.pages:
                try:
                    chars += len(page.extract_text() or '')
                except:
                    chars += 500  # estimate for failed pages

        # Replicate the script's estimation logic (sample first 5 pages)
        with pdfplumber.open(path) as p:
            sample = min(5, len(p.pages))
            sample_chars = 0
            for i in range(sample):
                try:
                    sample_chars += len(p.pages[i].extract_text() or '')
                except:
                    sample_chars += 500
            avg = sample_chars / sample if sample > 0 else 0
            if avg < 50:
                fsize = os.path.getsize(path) / 1024
                est = (int(fsize * 200) + pages * 600) // 2
            elif avg > 0:
                est = int((avg / 4) * pages)
            else:
                est = pages * 600
    except Exception as e:
        pages = 0
        chars = 0
        est = 0
        print(f"{pdf[:53]:<55} ERROR: {e}")
        continue

    actual_tokens = chars // 4
    diff_pct = ((est - actual_tokens) / actual_tokens * 100) if actual_tokens > 0 else 0

    total_chars += chars
    total_pages += pages
    total_estimated += est

    print(f"{pdf[:53]:<55} {pages:>4} {actual_tokens:>9,} {est:>9,} {diff_pct:>+6.1f}%")

print("-" * 90)
actual_total = total_chars // 4
print(f"{'TOTAL':<55} {total_pages:>4} {actual_total:>9,} {total_estimated:>9,} {((total_estimated - actual_total) / actual_total * 100):>+6.1f}%")
print()
print(f"Actual chars extracted:   {total_chars:,}")
print(f"Actual tokens (chars/4):  {actual_total:,}")
print(f"Script estimated tokens:  {total_estimated:,}")
print(f"Tracker reported:         2,257,433")
