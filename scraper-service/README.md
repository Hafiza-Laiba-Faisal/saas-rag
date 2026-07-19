# 🕷️ Scraper Service

**Production-ready web scraping API** with recursive crawling, PDF extraction, metadata analysis, and intelligent content detection.

## ✨ Key Features

- 🔄 **Recursive Web Crawling** - Multi-depth crawling with queue management
- 📄 **PDF Processing** - Text extraction with OCR support
- 🧠 **Content Intelligence** - Automatic content type detection & readability scoring
- 🔐 **Smart Request Handling** - DeepCrawl API fallback for 403/Cloudflare bypass
- 🚀 **FastAPI Backend** - High-performance async API
- 💾 **SQLite Storage** - Structured data storage with metadata
- 🌐 **Proxy Support** - Automatic IP rotation
- ⚡ **Rate Limiting** - Domain-based request throttling
- 📊 **Real-time Progress** - Job status tracking

## 🚀 Quick Start

```bash
# Setup
python3 -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt

# Configure (optional)
cp .env.example .env
# Add DEEPCRAWL_API_KEY for Cloudflare bypass

# Run
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Visit: http://localhost:8000/docs

## 📦 Quick Scripts

### Download Tax.gov.ae VAT Documents
```bash
python download_all_vat_docs.py
```

### Simple PDF Download (Any Site)
```bash
# Edit SEED_URLS in the script
python download_all_pdfs.py
```

## 🔧 API Examples

### Recursive Crawl
```bash
curl -X POST "http://localhost:8000/crawl/recursive" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "max_depth": 3,
    "max_pages": 100,
    "workers": 5
  }'
```

### Check Status
```bash
curl "http://localhost:8000/crawl/recursive/status/{job_id}"
```

## 📁 Project Structure

```
scraper-service/
├── app/
│   ├── api/routes/          # API endpoints
│   ├── core/
│   │   ├── crawler/         # Crawling engine
│   │   ├── fetcher/         # HTTP clients (with 403 bypass)
│   │   ├── extractor/       # Content extractors
│   │   └── content/         # Content analysis
│   ├── storage/             # Database layer
│   └── main.py              # FastAPI app
├── downloads/               # Downloaded files
├── download_all_vat_docs.py # Tax.gov.ae scraper
├── download_all_pdfs.py     # Universal PDF downloader
└── README.md
```

## 🔐 Environment Variables

```env
# Optional: For bypassing Cloudflare/403 errors
DEEPCRAWL_API_KEY=your_key_here
```

## 📚 Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) - System design
- [FEATURES.md](FEATURES.md) - Complete feature list
- [TEST_GUIDE.md](TEST_GUIDE.md) - Testing instructions
- [PRODUCTION_ROADMAP.md](PRODUCTION_ROADMAP.md) - Deployment guide

## 🛠️ Tech Stack

- **Backend**: FastAPI, Python 3.10+
- **HTTP**: httpx (async), requests
- **Parsing**: BeautifulSoup4, lxml
- **PDF**: PyPDF2, pytesseract (OCR)
- **Storage**: SQLite
- **Rate Limiting**: Custom domain-based limiter

## 📊 Use Cases

- ✅ VAT/Tax documentation scraping
- ✅ Legal document collection
- ✅ Government website archival
- ✅ Competitive intelligence
- ✅ Content aggregation

## ⚠️ Important Notes

### 403 Error Handling
This service includes automatic 403 bypass using:
1. **Enhanced Headers** - Browser-like request headers
2. **DeepCrawl API** - Fallback for blocked requests (requires API key)
3. **Rate Limiting** - Prevents IP bans

### Ethical Scraping
- ✅ Respects robots.txt (can be disabled)
- ✅ Implements rate limiting
- ✅ User-Agent identification
- ⚠️ Always check website Terms of Service

## 🤝 Contributing

1. Fork the repo
2. Create feature branch (`git checkout -b feature/amazing`)
3. Commit changes (`git commit -m 'Add feature'`)
4. Push to branch (`git push origin feature/amazing`)
5. Open Pull Request

## 📝 License

MIT License - see LICENSE file

## 🆘 Support

- 📧 Issues: GitHub Issues
- 📖 Docs: `/docs` endpoint when running
- 💬 Questions: Open a discussion

---

**Built for production use** • Fast, reliable, and scalable web scraping
