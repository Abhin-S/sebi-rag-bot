import os
import time
import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import re
import json
from datetime import datetime
try:
    import pdfplumber
except ImportError:
    print("Warning: pdfplumber not installed. Install with: pip install pdfplumber")
    pdfplumber = None

# Token limit configuration
TOKEN_LIMIT = 2_000_000  # 2 million tokens
TOKENS_PER_PAGE_ESTIMATE = 500  # Rough estimate: 1 page ≈ 500 tokens

# Setup Directories
DOWNLOAD_DIR = "sebi_master_circulars"
METADATA_DIR = "sebi_metadata"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(METADATA_DIR, exist_ok=True)

# Track downloaded documents to avoid duplicates
DOWNLOADED_TRACKER_FILE = os.path.join(METADATA_DIR, "downloaded_documents.json")
REFERENCES_FILE = os.path.join(METADATA_DIR, "document_references.json")

def load_tracker():
    """Load the set of already downloaded documents"""
    if os.path.exists(DOWNLOADED_TRACKER_FILE):
        with open(DOWNLOADED_TRACKER_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        "downloaded_urls": [], 
        "downloaded_circular_numbers": [],
        "total_tokens_estimated": 0,
        "total_pages": 0
    }

def save_tracker(tracker):
    """Save the tracker of downloaded documents"""
    with open(DOWNLOADED_TRACKER_FILE, 'w', encoding='utf-8') as f:
        json.dump(tracker, f, indent=2)

def load_references():
    """Load the document reference graph"""
    if os.path.exists(REFERENCES_FILE):
        with open(REFERENCES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_references(references):
    """Save the document reference graph"""
    with open(REFERENCES_FILE, 'w', encoding='utf-8') as f:
        json.dump(references, f, indent=2)

def sanitize_filename(filename):
    """Clean filename to remove invalid characters and limit length"""
    # Remove or replace invalid characters
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    # Remove extra spaces
    filename = ' '.join(filename.split())
    # Encode to ASCII, replacing problematic characters
    try:
        # Try to encode as UTF-8 first, then replace surrogates
        filename = filename.encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')
    except:
        # If that fails, convert to ASCII
        filename = filename.encode('ascii', errors='ignore').decode('ascii')
    # Limit length more aggressively to avoid Windows path limit (260 chars total)
    # Account for path + date prefix + .pdf extension
    max_length = 120  # Conservative limit
    if len(filename) > max_length:
        filename = filename[:max_length]
    return filename.strip()

def estimate_tokens_from_pdf(pdf_path):
    """Estimate token count from PDF, handles both text and scanned PDFs"""
    if not pdfplumber:
        # Fallback: use file size as rough estimate
        # ~1KB ≈ 150 tokens (very rough)
        file_size_kb = os.path.getsize(pdf_path) / 1024
        return int(file_size_kb * 150), 0
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            num_pages = len(pdf.pages)
            
            # Sample first few pages to get better estimate
            sample_pages = min(5, num_pages)
            total_chars = 0
            
            for i in range(sample_pages):
                text = pdf.pages[i].extract_text() or ""
                total_chars += len(text)
            
            # Check if this is likely a scanned/image-based PDF
            avg_chars_per_page = total_chars / sample_pages if sample_pages > 0 else 0
            
            if avg_chars_per_page < 50:
                # Likely a scanned PDF (very little text extracted)
                # Use conservative estimate based on file size and page count
                file_size_kb = os.path.getsize(pdf_path) / 1024
                
                # For scanned PDFs, estimate higher token count
                # Images contain more information when OCR'd
                # Formula: base estimate + bonus for pages
                file_based_estimate = int(file_size_kb * 200)  # Higher multiplier for images
                page_based_estimate = num_pages * 600  # Higher per-page estimate for scanned docs
                
                # Use average of both methods for better accuracy
                estimated_tokens = (file_based_estimate + page_based_estimate) // 2
                
                print(f"  ⚠️  Scanned PDF detected (low text extraction)")
                print(f"  📊 Using conservative estimate for image-based PDF")
                
                return estimated_tokens, num_pages
            
            elif avg_chars_per_page > 0:
                # Text-based PDF with good extraction
                # Estimate based on character count
                # ~1 token ≈ 4 characters (rough average)
                estimated_tokens = int((avg_chars_per_page / 4) * num_pages)
                return estimated_tokens, num_pages
            
            else:
                # No text at all - definitely scanned or empty
                # Use page count and file size
                file_size_kb = os.path.getsize(pdf_path) / 1024
                estimated_tokens = max(
                    num_pages * 600,  # Conservative page estimate
                    int(file_size_kb * 200)  # File size estimate
                )
                print(f"  ⚠️  Image-only PDF (no text extracted)")
                return estimated_tokens, num_pages
    
    except Exception as e:
        print(f"  ⚠️  Warning: Could not estimate tokens accurately: {e}")
        # Fallback to file size
        try:
            file_size_kb = os.path.getsize(pdf_path) / 1024
            # Conservative estimate for unknown PDF type
            return int(file_size_kb * 180), 0
        except:
            # Last resort: assume moderate size
            return 50000, 0

def extract_sebi_references(pdf_path):
    """Extract SEBI circular references from a PDF"""
    if not pdfplumber:
        return []
    
    references = []
    
    # Patterns to match SEBI circular numbers
    patterns = [
        r'SEBI/HO/[A-Z]+/[A-Z0-9_]+/[A-Z]*/?P?/?[A-Z]*/?CIR/[A-Z]*/?P?/?[0-9]+/[0-9]+',  # SEBI/HO/IMD/IMD_II/P/CIR/2024/123
        r'SEBI/HO/[A-Z]+/[A-Z0-9_-]+/[0-9]+',  # SEBI/HO/CFD/DIL2/CIR/P/2024/0112
        r'SEBI/[A-Z]+/[A-Z0-9_-]+/[0-9]+/[0-9]+',  # SEBI/IMD/CIR/2024/123
        r'CIR/[A-Z]+/[0-9]+/[0-9]+',  # CIR/IMD/2024/123
        r'Circular\s+No\.?\s*:?\s*([A-Z0-9/\-_]+)',  # Circular No. XXX
        r'Notification\s+No\.?\s*:?\s*([A-Z0-9/\-_]+)',  # Notification No. XXX
        r'SEBI/LAD-NRO/GN/[0-9]+/[0-9]+',  # Legal Affairs Department
    ]
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            text = ""
            # Extract text from all pages (limit to first 50 pages to avoid huge documents)
            for page in pdf.pages[:50]:
                text += page.extract_text() or ""
        
        # Find all matches
        for pattern in patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                ref = match.group(0)
                # Clean up the reference
                ref = ref.strip()
                if ref and len(ref) > 5:  # Avoid too short matches
                    references.append(ref)
        
        # Deduplicate
        references = list(set(references))
        
    except Exception as e:
        print(f"Error extracting references from {pdf_path}: {e}")
    
    return references

def search_sebi_document(search_query, driver):
    """Search SEBI website for a specific document/circular number"""
    try:
        # Use SEBI's search functionality
        search_url = f"https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doSearch=yes&searchString={search_query}"
        
        # Open in new tab
        driver.execute_script("window.open('');")
        driver.switch_to.window(driver.window_handles[-1])
        driver.get(search_url)
        time.sleep(2)
        
        # Look for the first relevant result
        try:
            results = driver.find_elements(By.CSS_SELECTOR, "table tbody tr td a")
            for result in results[:3]:  # Check first 3 results
                href = result.get_attribute("href")
                text = result.text
                if href and ("circular" in href.lower() or "notification" in href.lower()):
                    url = href
                    title = text
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])
                    return {"url": url, "title": title}
        except:
            pass
        
        driver.close()
        driver.switch_to.window(driver.window_handles[0])
        
    except Exception as e:
        # Ensure we're back on main window
        if len(driver.window_handles) > 1:
            driver.close()
            driver.switch_to.window(driver.window_handles[0])
    
    return None

def save_metadata(filename, metadata):
    """Save document metadata for RAG indexing"""
    metadata_file = os.path.join(METADATA_DIR, f"{os.path.splitext(filename)[0]}.json")
    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)

def is_valid_pdf(file_path):
    """Check if downloaded file is a valid PDF"""
    try:
        with open(file_path, 'rb') as f:
            header = f.read(4)
            # PDF files start with %PDF
            return header == b'%PDF'
    except:
        return False

def extract_pdf_url_from_html(html_text):
    """Extract actual PDF URL from page HTML source.
    
    SEBI embeds PDFs via a PDF.js viewer in an iframe like:
      <iframe src='../../../web/?file=https://www.sebi.gov.in/sebi_data/attachdocs/aug-2025/xxx.pdf'>
    
    We need the actual PDF URL from the 'file=' parameter, NOT the viewer URL.
    """
    # Method 1: Look for the ?file= pattern in iframe src (most common on SEBI)
    file_param_pattern = r'[?&]file=(https?://[^\s\'"&]+\.pdf)'
    match = re.search(file_param_pattern, html_text, re.IGNORECASE)
    if match:
        return match.group(1)
    
    # Method 2: Direct PDF URL in sebi_data/attachdocs (the actual PDF location)
    sebi_pdf_pattern = r'(https?://www\.sebi\.gov\.in/sebi_data/attachdocs/[^\s\'"<>]+\.pdf)'
    match = re.search(sebi_pdf_pattern, html_text, re.IGNORECASE)
    if match:
        return match.group(1)
    
    # Method 3: Any sebi.gov.in PDF URL
    any_sebi_pdf = r'(https?://www\.sebi\.gov\.in/[^\s\'"<>]+\.pdf)'
    match = re.search(any_sebi_pdf, html_text, re.IGNORECASE)
    if match:
        return match.group(1)
    
    # Method 4: Generic PDF URL
    generic_pdf = r'(https?://[^\s\'"<>]+\.pdf)'
    match = re.search(generic_pdf, html_text, re.IGNORECASE)
    if match:
        return match.group(1)
    
    return None

def extract_pdf_url(driver, title, circular_page_url=None):
    """Try multiple methods to extract PDF URL from the page.
    
    The main insight: SEBI uses a PDF.js viewer in an iframe.
    The iframe src contains '?file=<actual_pdf_url>'.
    We need to extract the actual PDF URL, NOT the viewer URL.
    """
    # Method A (fastest): Use requests to fetch page HTML directly and parse it
    # This avoids any Selenium rendering issues
    if circular_page_url:
        try:
            resp = requests.get(circular_page_url, timeout=15)
            if resp.status_code == 200:
                pdf_url = extract_pdf_url_from_html(resp.text)
                if pdf_url:
                    return pdf_url
        except Exception as e:
            pass  # Fall through to Selenium methods
    
    # Method B: Parse the Selenium page source
    try:
        page_source = driver.page_source
        pdf_url = extract_pdf_url_from_html(page_source)
        if pdf_url:
            return pdf_url
    except Exception as e:
        pass
    
    # Method C: Check iframe src attributes via Selenium DOM
    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for iframe in iframes:
            src = iframe.get_attribute("src") or ""
            if ".pdf" in src.lower():
                # Extract actual PDF URL from viewer URL
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(src)
                params = parse_qs(parsed.query)
                if 'file' in params:
                    return params['file'][0]
                # If no file= param, it might be a direct PDF link
                if src.lower().endswith('.pdf'):
                    return src
    except Exception as e:
        pass
    
    # Method D: Look for embed/object tags
    try:
        for tag in ["embed", "object"]:
            elements = driver.find_elements(By.TAG_NAME, tag)
            for elem in elements:
                src = elem.get_attribute("src") or elem.get_attribute("data") or ""
                if src and ".pdf" in src.lower():
                    return src
    except:
        pass
    
    # Method E: Look for download links
    try:
        links = driver.find_elements(By.TAG_NAME, "a")
        for link in links:
            href = link.get_attribute("href") or ""
            if href and ".pdf" in href.lower() and "sebi_data" in href.lower():
                return href
    except:
        pass
    
    return None

def extract_pdf_url_from_html_page(circular_page_url):
    """Fetch a circular page via HTTP and extract the actual PDF URL.
    
    This is the fastest method - no Selenium needed.
    SEBI circular pages embed PDFs via:
      <iframe src='../../../web/?file=<actual_pdf_url>'>
    """
    try:
        resp = requests.get(circular_page_url, timeout=15)
        if resp.status_code == 200:
            return extract_pdf_url_from_html(resp.text)
    except Exception as e:
        pass
    return None

# Initialize Selenium
options = webdriver.ChromeOptions()
# options.add_argument('--headless')  # Uncomment to run without a window
prefs = {
    "download.default_directory": os.path.abspath(DOWNLOAD_DIR),
    "download.prompt_for_download": False,
    "plugins.always_open_pdf_externally": True
}
options.add_experimental_option("prefs", prefs)
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

def download_pdfs(recursive=True, max_depth=2):
    """
    Download PDFs from SEBI website with token limit
    Args:
        recursive: Whether to follow references in PDFs
        max_depth: Maximum depth for recursive downloading
    """
    base_url = "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=6&smid=0"
    driver.get(base_url)
    time.sleep(3)  # Wait for page to load
    
    page_num = 1
    downloaded_count = 0
    skipped_count = 0
    
    # Load tracker
    tracker = load_tracker()
    references_graph = load_references()
    documents_to_process = []  # Queue for recursive processing
    
    # Token tracking
    initial_tokens = tracker.get("total_tokens_estimated", 0)
    current_tokens = initial_tokens
    token_limit_reached = False
    
    print(f"\n📊 Starting with {current_tokens:,} tokens already downloaded")
    print(f"🎯 Target: ~{TOKEN_LIMIT:,} tokens ({(TOKEN_LIMIT - current_tokens):,} remaining)")
    print(f"📝 Note: Will complete all referenced documents even if limit is exceeded\n")
    
    while True:
        print(f"\n{'='*60}")
        print(f"Processing Page {page_num}")
        print(f"{'='*60}")
        
        time.sleep(2)  # Wait for page to load
        
        # Get all circular links from the current page
        try:
            # Find all rows in the table
            rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
            circular_data = []
            
            for row in rows:
                try:
                    # Get the title link
                    title_element = row.find_element(By.CSS_SELECTOR, "td a")
                    title = title_element.text.strip()
                    url = title_element.get_attribute("href")
                    
                    # Get the date if available
                    date_elements = row.find_elements(By.TAG_NAME, "td")
                    date = date_elements[0].text.strip() if date_elements else "no_date"
                    
                    if url and title:
                        circular_data.append((title, url, date))
                except Exception as e:
                    continue
            
            print(f"Found {len(circular_data)} circulars on this page")
            
            # Process each circular
            for idx, (title, url, date) in enumerate(circular_data, 1):
                # Skip if already downloaded
                if url in tracker["downloaded_urls"]:
                    # Clean title for display
                    display_title = title.encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')
                    print(f"\n[{idx}/{len(circular_data)}] ⊘ Already downloaded: {display_title[:60]}...")
                    continue
                
                # Check token limit (but only for master circulars, not referenced docs)
                if not token_limit_reached and current_tokens >= TOKEN_LIMIT:
                    print(f"\n{'='*60}")
                    print(f"✓ Token limit reached: {current_tokens:,} tokens")
                    print(f"⏭️  Skipping remaining master circulars")
                    print(f"📥 Will still download referenced documents from collected docs")
                    print(f"{'='*60}")
                    token_limit_reached = True
                    break
                
                try:
                    # Clean title for display
                    display_title = title.encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')
                    print(f"\n[{idx}/{len(circular_data)}] Processing: {display_title[:60]}...")
                    
                    # Extract PDF URL directly via HTTP request (no need to open browser tab)
                    pdf_url = extract_pdf_url_from_html_page(url)
                    
                    if not pdf_url:
                        # Fallback: open in browser and try Selenium extraction
                        driver.execute_script("window.open('');")
                        driver.switch_to.window(driver.window_handles[1])
                        driver.get(url)
                        time.sleep(3)
                        pdf_url = extract_pdf_url(driver, title, circular_page_url=url)
                        driver.close()
                        driver.switch_to.window(driver.window_handles[0])
                    
                    if pdf_url:
                        print(f"  PDF URL: {pdf_url[:80]}...")

                        # Create filename with date prefix
                        date_prefix = date.replace(" ", "_").replace(",", "")
                        clean_title = sanitize_filename(title)
                        filename = f"{date_prefix}_{clean_title}.pdf"
                        file_path = os.path.join(DOWNLOAD_DIR, filename)
                        
                        # Check if path is too long
                        if len(file_path) > 250:
                            # Truncate title further
                            clean_title = sanitize_filename(title)[:80]
                            filename = f"{date_prefix}_{clean_title}.pdf"
                            file_path = os.path.join(DOWNLOAD_DIR, filename)
                        
                        # Download the PDF
                        response = requests.get(pdf_url, timeout=30, allow_redirects=True)
                        response.raise_for_status()
                        
                        # Save to file
                        with open(file_path, 'wb') as f:
                            f.write(response.content)
                        
                        # Validate that it's actually a PDF
                        if not is_valid_pdf(file_path):
                            print(f"  ⚠️  Downloaded file is not a valid PDF, skipping...")
                            os.remove(file_path)
                            skipped_count += 1

                            continue
                        
                        # Estimate tokens for this document
                        est_tokens, num_pages = estimate_tokens_from_pdf(file_path)
                        current_tokens += est_tokens
                        
                        print(f"✓ Downloaded: {filename}")
                        print(f"  📄 Pages: {num_pages}, Estimated tokens: {est_tokens:,}")
                        print(f"  📊 Total tokens so far: {current_tokens:,} / {TOKEN_LIMIT:,}")
                        downloaded_count += 1
                        
                        # Track this download
                        tracker["downloaded_urls"].append(url)
                        tracker["total_tokens_estimated"] = current_tokens
                        tracker["total_pages"] = tracker.get("total_pages", 0) + num_pages
                        
                        # Save metadata
                        metadata = {
                            "title": title,
                            "date": date,
                            "url": url,
                            "pdf_url": pdf_url,
                            "filename": filename,
                            "download_timestamp": datetime.now().isoformat(),
                            "source": "master_circulars",
                            "estimated_tokens": est_tokens,
                            "num_pages": num_pages
                        }
                        save_metadata(filename, metadata)
                        
                        # Add to queue for reference extraction
                        documents_to_process.append({
                            "path": file_path,
                            "filename": filename,
                            "title": title,
                            "depth": 0
                        })
                        
                    else:
                        # Clean title for display
                        display_title = title.encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')
                        print(f"✗ Could not find PDF URL for: {display_title}")
                        skipped_count += 1
                    
                except Exception as e:
                    # Clean title for display
                    display_title = title.encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')
                    print(f"✗ Error processing {display_title}: {str(e)}")
                    skipped_count += 1
                    # Ensure we're back on the main window
                    if len(driver.window_handles) > 1:
                        driver.close()
                        driver.switch_to.window(driver.window_handles[0])
            
        except Exception as e:
            print(f"Error processing page {page_num}: {e}")
        
        # Try to navigate to next page (only if we haven't hit token limit)
        if token_limit_reached:
            print("\n⏭️  Stopping pagination - token limit reached")
            break
        
        try:
            # Look for "Next ›" link
            next_button = driver.find_element(By.LINK_TEXT, "Next ›")
            if "disabled" not in next_button.get_attribute("class"):
                next_button.click()
                page_num += 1
                time.sleep(3)
            else:
                print("\nReached the last page.")
                break
        except Exception as e:
            # Try alternative methods to find next button
            try:
                next_buttons = driver.find_elements(By.XPATH, "//a[contains(text(), 'Next')]")
                if next_buttons:
                    next_buttons[0].click()
                    page_num += 1
                    time.sleep(3)
                else:
                    print("\nNo more pages found.")
                    break
            except:
                print("\nReached the end of the list.")
                break
    
    # Save tracker after main scraping
    save_tracker(tracker)
    
    # Phase 2: Process references recursively
    if recursive and pdfplumber:
        print(f"\n{'='*60}")
        print(f"Phase 2: Extracting and Downloading Referenced Documents")
        print(f"📝 Note: This continues regardless of token limit")
        print(f"{'='*60}")
        
        processed_refs = set()
        depth = 0
        
        while documents_to_process and depth < max_depth:
            depth += 1
            print(f"\n--- Depth {depth} ---")
            
            current_batch = documents_to_process.copy()
            documents_to_process = []
            
            for doc_info in current_batch:
                if doc_info["depth"] >= max_depth:
                    continue
                
                print(f"\nExtracting references from: {doc_info['filename'][:50]}...")
                references = extract_sebi_references(doc_info["path"])
                
                if references:
                    print(f"  Found {len(references)} potential references")
                    references_graph[doc_info["filename"]] = references
                    
                    # Try to download each referenced document
                    for ref in references:
                        if ref in processed_refs or ref in tracker["downloaded_circular_numbers"]:
                            continue
                        
                        processed_refs.add(ref)
                        print(f"  Searching for: {ref}...")
                        
                        result = search_sebi_document(ref, driver)
                        
                        if result and result["url"] not in tracker["downloaded_urls"]:
                            try:
                                # Open and download
                                driver.execute_script("window.open('');")
                                driver.switch_to.window(driver.window_handles[1])
                                driver.get(result["url"])
                                time.sleep(3)
                                
                                pdf_url = extract_pdf_url(driver, result["title"], circular_page_url=result["url"])
                                
                                if pdf_url:
                                    ref_filename = sanitize_filename(f"{ref}_{result['title']}")[:200] + ".pdf"
                                    ref_path = os.path.join(DOWNLOAD_DIR, ref_filename)
                                    
                                    response = requests.get(pdf_url, timeout=30)
                                    response.raise_for_status()
                                    
                                    with open(ref_path, 'wb') as f:
                                        f.write(response.content)
                                    
                                    # Estimate tokens for referenced document
                                    ref_est_tokens, ref_num_pages = estimate_tokens_from_pdf(ref_path)
                                    current_tokens += ref_est_tokens
                                    
                                    print(f"    ✓ Downloaded referenced doc: {ref_filename[:50]}...")
                                    print(f"      📄 Pages: {ref_num_pages}, Tokens: {ref_est_tokens:,} (Total: {current_tokens:,})")
                                    downloaded_count += 1
                                    
                                    tracker["downloaded_urls"].append(result["url"])
                                    tracker["downloaded_circular_numbers"].append(ref)
                                    tracker["total_tokens_estimated"] = current_tokens
                                    tracker["total_pages"] = tracker.get("total_pages", 0) + ref_num_pages
                                    
                                    # Save metadata
                                    metadata = {
                                        "title": result["title"],
                                        "circular_number": ref,
                                        "url": result["url"],
                                        "pdf_url": pdf_url,
                                        "filename": ref_filename,
                                        "download_timestamp": datetime.now().isoformat(),
                                        "source": "referenced_document",
                                        "referenced_by": doc_info["filename"],
                                        "depth": depth,
                                        "estimated_tokens": ref_est_tokens,
                                        "num_pages": ref_num_pages
                                    }
                                    save_metadata(ref_filename, metadata)
                                    
                                    # Add to queue for next depth level
                                    if depth < max_depth:
                                        documents_to_process.append({
                                            "path": ref_path,
                                            "filename": ref_filename,
                                            "title": result["title"],
                                            "depth": depth
                                        })
                                
                                driver.close()
                                driver.switch_to.window(driver.window_handles[0])
                                
                            except Exception as e:
                                print(f"    ✗ Error downloading {ref}: {e}")
                                if len(driver.window_handles) > 1:
                                    driver.close()
                                    driver.switch_to.window(driver.window_handles[0])
                        
                        time.sleep(1)  # Rate limiting
                
                # Save progress periodically
                save_tracker(tracker)
                save_references(references_graph)
            
            # Update token count in tracker after each depth level
            tracker["total_tokens_estimated"] = current_tokens
            save_tracker(tracker)
        
        save_references(references_graph)
    
    driver.quit()
    save_tracker(tracker)
    
    print(f"\n{'='*60}")
    print(f"Download Complete!")
    print(f"{'='*60}")
    print(f"Successfully downloaded: {downloaded_count} PDFs")
    print(f"Skipped: {skipped_count} items")
    print(f"\n📊 Token Statistics:")
    print(f"   - Total estimated tokens: {current_tokens:,}")
    print(f"   - Target was: {TOKEN_LIMIT:,}")
    print(f"   - Total pages: {tracker.get('total_pages', 0):,}")
    if current_tokens >= TOKEN_LIMIT:
        print(f"   ✓ Target reached! ({((current_tokens/TOKEN_LIMIT)-1)*100:.1f}% over)")
    else:
        print(f"   ⚠ Under target by {TOKEN_LIMIT - current_tokens:,} tokens")
    print(f"\n📁 Output:")
    print(f"   - Files saved to: {os.path.abspath(DOWNLOAD_DIR)}")
    print(f"   - Metadata saved to: {os.path.abspath(METADATA_DIR)}")
    if recursive:
        print(f"   - Reference graph: {REFERENCES_FILE}")
    print(f"{'='*60}")

if __name__ == "__main__":
    # Run with recursive scraping (depth=2 means: original docs + their references + references of references)
    # Stops at ~2 million tokens for master circulars, but completes all referenced documents
    download_pdfs(recursive=True, max_depth=2)
