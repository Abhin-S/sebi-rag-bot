# Token Tracking Feature - SEBI Scraper

## 🎯 Overview

The enhanced scraper now includes **intelligent token tracking** to ensure you collect approximately **2 million tokens** worth of data while guaranteeing all referenced documents are downloaded.

## 📊 How Token Estimation Works

### Estimation Method
The scraper estimates tokens using a multi-step approach:

1. **Primary Method** (with pdfplumber):
   - Samples the first 5 pages of each PDF
   - Counts characters in the sample
   - Uses the formula: `~1 token ≈ 4 characters`
   - Extrapolates to full document

2. **Fallback Method** (without pdfplumber):
   - Uses file size as proxy
   - Formula: `~1 KB ≈ 150 tokens`

### Accuracy
This is a **soft constraint** and rough estimate:
- Actual tokens may vary by ±20%
- Real token count depends on the LLM tokenizer used (GPT, Claude, etc.)
- Estimates are intentionally conservative

## 🔄 How It Works

### Phase 1: Master Circulars (Token-Limited)
```
1. Downloads master circulars from SEBI
2. After each download, estimates tokens
3. Tracks cumulative token count
4. When ~2M tokens reached:
   - Stops downloading NEW master circulars
   - Moves to Phase 2
```

### Phase 2: Referenced Documents (Unlimited)
```
1. Extracts references from ALL downloaded documents
2. Searches for and downloads referenced circulars
3. Continues REGARDLESS of token limit
4. Ensures complete document graph
```

### Why This Approach?
- **Comprehensive coverage**: No broken reference chains
- **Quality over quantity**: Better to have complete context
- **RAG-optimized**: Referenced docs crucial for accuracy

## 📈 Example Output

```
📊 Starting with 0 tokens already downloaded
🎯 Target: ~2,000,000 tokens (2,000,000 remaining)
📝 Note: Will complete all referenced documents even if limit is exceeded

Processing Page 1
Found 25 circulars on this page

[1/25] Processing: Master Circular for Research Analysts...
✓ Downloaded: Feb_06_2026_Master_Circular_for_Research_Analysts.pdf
  📄 Pages: 107, Estimated tokens: 26,750
  📊 Total tokens so far: 26,750 / 2,000,000

... (continues until ~2M tokens)

✓ Token limit reached: 2,003,450 tokens
⏭️  Skipping remaining master circulars
📥 Will still download referenced documents from collected docs

Phase 2: Extracting and Downloading Referenced Documents
📝 Note: This continues regardless of token limit

Extracting references from: Feb_06_2026_Master_Circular_for_Research_Analysts.pdf...
  Found 12 potential references
  Searching for: SEBI/HO/IMD/IMD_II/P/CIR/2024/123...
    ✓ Downloaded referenced doc: SEBI_HO_IMD_IMD_II_P_CIR_2024_123_...
      📄 Pages: 8, Tokens: 2,000 (Total: 2,005,450)
```

## 📁 Token Tracking in Metadata

The tracker file `sebi_metadata/downloaded_documents.json` now includes:

```json
{
  "downloaded_urls": [...],
  "downloaded_circular_numbers": [...],
  "total_tokens_estimated": 2123456,
  "total_pages": 4247
}
```

Each document's metadata also includes:
```json
{
  "title": "Master Circular for Research Analysts",
  "estimated_tokens": 26750,
  "num_pages": 107,
  ...
}
```

## ⚙️ Configuration

You can adjust the token limit:

```python
# At top of sebi_downloader.py
TOKEN_LIMIT = 2_000_000  # Change this value
TOKENS_PER_PAGE_ESTIMATE = 500  # Adjust if needed
```

### Estimating Your Needs

Based on your data (12 docs in 2025, 10 with ~1500 pages):
- **Average**: ~150 pages per document
- **Tokens per doc**: ~75,000 tokens
- **For 2M tokens**: ~27 documents

But actual results depend on:
- Document density (text vs images/tables)
- Formatting
- Language complexity

## 🔁 Resumable Downloads

If the script is interrupted:
1. Token count is saved in tracker
2. Next run resumes from current count
3. Skips already-downloaded files
4. Continues toward 2M target

## 📊 Analyzing Your Collection

After download, run:
```bash
python analyze_documents.py
```

This shows:
- Total tokens collected
- Total pages
- Document breakdown
- Reference graph statistics

## 🎯 Your Target: 2 Million Tokens

### What This Gives You:

**Token Context Windows:**
- GPT-4 Turbo: 128K tokens → **15.6 queries** worth of context
- Claude 3: 200K tokens → **10 queries** worth of context  
- GPT-3.5: 16K tokens → **125 queries** worth of context

**With RAG (top 5 chunks of 1000 tokens each):**
- 2M tokens = 2000 chunks
- Enough for **400 different queries** before repeating chunks
- Or **comprehensive coverage** of SEBI regulations

### This is Perfect For:
- ✅ Master circulars from last 3-5 years
- ✅ Core regulatory framework
- ✅ Complete reference chains
- ✅ Production-ready RAG chatbot

## 🚀 Ready to Run?

```bash
# Install dependencies
pip install -r requirements.txt

# Run the scraper
python sebi_downloader.py

# Analyze results
python analyze_documents.py
```

The script will handle everything automatically!
