"""
Cleanup script to remove invalid PDF files and reset tracker
"""
import os
import json

DOWNLOAD_DIR = "sebi_master_circulars"
METADATA_DIR = "sebi_metadata"
TRACKER_FILE = os.path.join(METADATA_DIR, "downloaded_documents.json")

def is_valid_pdf(file_path):
    """Check if file is a valid PDF"""
    try:
        with open(file_path, 'rb') as f:
            header = f.read(4)
            return header == b'%PDF'
    except:
        return False

def cleanup_invalid_pdfs():
    """Remove invalid PDF files and update tracker"""
    if not os.path.exists(DOWNLOAD_DIR):
        print(f"Directory {DOWNLOAD_DIR} not found.")
        return
    
    pdf_files = [f for f in os.listdir(DOWNLOAD_DIR) if f.endswith('.pdf')]
    
    if not pdf_files:
        print("No PDF files found.")
        return
    
    print(f"Checking {len(pdf_files)} PDF files...")
    
    invalid_files = []
    valid_files = []
    
    for pdf_file in pdf_files:
        file_path = os.path.join(DOWNLOAD_DIR, pdf_file)
        
        if not is_valid_pdf(file_path):
            print(f"  ✗ Invalid PDF: {pdf_file}")
            invalid_files.append(pdf_file)
        else:
            print(f"  ✓ Valid PDF: {pdf_file}")
            valid_files.append(pdf_file)
    
    if invalid_files:
        print(f"\n⚠️  Found {len(invalid_files)} invalid PDFs. Remove them? (y/n): ", end='')
        response = input().strip().lower()
        
        if response == 'y':
            for pdf_file in invalid_files:
                file_path = os.path.join(DOWNLOAD_DIR, pdf_file)
                os.remove(file_path)
                # Also remove metadata
                meta_file = os.path.join(METADATA_DIR, pdf_file.replace('.pdf', '.json'))
                if os.path.exists(meta_file):
                    os.remove(meta_file)
            
            # Reset tracker
            if os.path.exists(TRACKER_FILE):
                print("\n⚠️  Reset tracker file? (y/n): ", end='')
                response = input().strip().lower()
                if response == 'y':
                    tracker = {
                        "downloaded_urls": [],
                        "downloaded_circular_numbers": [],
                        "total_tokens_estimated": 0,
                        "total_pages": 0
                    }
                    with open(TRACKER_FILE, 'w') as f:
                        json.dump(tracker, f, indent=2)
                    print("  ✓ Tracker reset")
            
            print(f"\n{'='*60}")
            print(f"Cleanup complete!")
            print(f"  - Removed: {len(invalid_files)} invalid PDFs")
            print(f"  - Remaining: {len(valid_files)} valid PDFs")
            print(f"{'='*60}")
        else:
            print("Cleanup cancelled.")
    else:
        print(f"\n✅ All {len(valid_files)} PDFs are valid!")

if __name__ == "__main__":
    cleanup_invalid_pdfs()
