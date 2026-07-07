#!/bin/bash
# Quick validation script for new recursive crawler

echo "🔍 Testing Scraper Service..."
echo ""

BASE_URL="http://localhost:8000"

# Check if server is running
echo "1️⃣ Checking server status..."
curl -s "$BASE_URL/" > /dev/null
if [ $? -eq 0 ]; then
    echo "✅ Server is running"
else
    echo "❌ Server not running. Start with:"
    echo "   cd app && ../venv/bin/uvicorn main:app --reload --port 8000"
    exit 1
fi
echo ""

# Test single page crawl
echo "2️⃣ Testing single page crawl..."
RESULT=$(curl -s "$BASE_URL/crawl/test?url=https://example.com")
if echo "$RESULT" | grep -q "success"; then
    echo "✅ Single page crawl works"
else
    echo "❌ Single page crawl failed"
    echo "$RESULT"
fi
echo ""

# Test recursive crawler
echo "3️⃣ Testing recursive crawler..."
CRAWL_RESULT=$(curl -s -X POST "$BASE_URL/crawl/recursive" \
    -H "Content-Type: application/json" \
    -d '{"url": "https://example.com", "max_depth": 1, "max_pages": 5}')

JOB_ID=$(echo "$CRAWL_RESULT" | grep -o '"job_id":"[^"]*"' | cut -d'"' -f4)

if [ -n "$JOB_ID" ]; then
    echo "✅ Recursive crawl started (job_id: $JOB_ID)"
    
    # Wait and check status
    echo "   Waiting 5 seconds..."
    sleep 5
    
    STATUS=$(curl -s "$BASE_URL/crawl/recursive/status/$JOB_ID")
    if echo "$STATUS" | grep -q "completed\|running"; then
        echo "✅ Job status retrieved"
        echo "$STATUS" | grep -o '"progress":[0-9]*' || true
    else
        echo "❌ Could not get job status"
    fi
else
    echo "❌ Recursive crawl failed to start"
    echo "$CRAWL_RESULT"
fi
echo ""

# List jobs
echo "4️⃣ Listing all jobs..."
JOBS=$(curl -s "$BASE_URL/crawl/recursive/jobs")
if echo "$JOBS" | grep -q "jobs"; then
    COUNT=$(echo "$JOBS" | grep -o '"count":[0-9]*' | cut -d':' -f2)
    echo "✅ Job list retrieved ($COUNT jobs)"
else
    echo "❌ Could not list jobs"
fi
echo ""

echo "🎉 Basic tests completed!"
echo ""
echo "📚 Next steps:"
echo "   1. Check full test suite: TEST_GUIDE.md"
echo "   2. Review implementation: IMPLEMENTATION_SUMMARY.md"
echo "   3. See roadmap: PRODUCTION_ROADMAP.md"
echo "   4. Open Swagger UI: $BASE_URL/docs"
