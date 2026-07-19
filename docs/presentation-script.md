# TenBit RAG Platform — Presentation Script

## Setup Check (before recording)

```bash
./start.sh
# Services ready in ~30 seconds
```

---

## Scene 1: Services Running (0:00 - 0:30)

**Screen:** Terminal showing `docker compose ps`

**Script:**
Yeh hamara TenBit RAG Platform hai. 6 Docker containers chal rahe hain:
- **nginx** — reverse proxy, SSL terminate karta hai
- **rag_api** — main backend (FastAPI)
- **qdrant** — vector database
- **redis** — caching / rate limiting
- **ocr_service** — OCR processing
- **scraper_service** — web scraping

---

## Scene 2: Admin Dashboard Login (0:30 - 1:00)

**Screen:** Browser at `https://localhost/`

**Actions:**
- Accept self-signed SSL warning
- Login form appears automatically (no JWT = redirect to login)
- Enter username: `admin`, password: `admin`
- Click Login

**Script:**
Dashboard open karte hi login modal auto dikhta hai. JWT-based auth hai. Admin login karte hi tenant list dikhti hai.

---

## Scene 3: Tenant Management (1:00 - 1:45)

**Screen:** Inside dashboard, show existing tenant

**Actions:**
- Click on an existing tenant (e.g., "Rimsha")
- Show stats cards: model, tier, fee

**Script:**
Har client ka isolated tenant hota hai. Yahan dikhta hai:
- LLM model aur provider
- Subscription tier
- Embedding model
- Documents aur chunks count

Side panel mein system prompt bhi edit kar sakte hain jo LLM ko guide karta hai.

---

## Scene 4: LLM Configuration (1:45 - 2:30)

**Screen:** Config tab

**Actions:**
- Click Config tab
- Show LLM Provider dropdown (Mistral, Gemini, OpenAI, etc.)
- Click Mistral — auto-fills model aur base URL
- Show RAG parameters (top-k, reranking, chunking)

**Script:**
Config tab mein har tenant ke liye LLM set kar sakte hain. Mistral, Gemini, OpenAI, Anthropic — sab supported hain. RAG parameters bhi fine-tune kar sakte hain jaise retrieval depth, chunk size, reranking.

---

## Scene 5: Document Upload & Scraping (2:30 - 3:30)

**Screen:** Documents tab

**Actions:**
- Click Documents tab
- Show existing document list
- Click "Upload" — select a PDF
- Show upload progress bar
- Then click "Scrape URL" — paste a URL, click Scrape

**Script:**
Documents tab mein files upload kar sakte hain — PDF, images, HTML, docs — sab support hain. Agar website ko scrape karna hai to URL daal kar scrape kar sakte hain. DeepCrawl fallback hai, agar site block kare to automatic DeepCrawl se content fetch hota hai.

---

## Scene 6: Ingestion Pipeline (3:30 - 4:00)

**Screen:** Click "Ingest All" button

**Actions:**
- Click "Ingest All" (or "Re-ingest")
- Show progress bar with logs

**Script:**
"Ingest" button document ko chunk karta hai, embeddings generate karta hai, aur Qdrant vector database mein store karta hai. Progress bar mein live logs dikhte hain.

---

## Scene 7: Playground — Chat Testing (4:00 - 5:00)

**Screen:** Playground tab

**Actions:**
- Click Playground tab
- Type a question: "What services do you offer?"
- Show streaming response with citations
- Click on a citation number — drawer opens showing source chunk

**Script:**
Playground mein admin apne tenant ka LLM test kar sakta hai. Streaming response aata hai — real-time tokens. Citations ke saath answer aata hai, aur kisi bhi citation number pe click karne se source chunk open hota hai. Yahan system prompt bhi edit kar sakte hain sidebar mein.

---

## Scene 8: Chat Sessions (5:00 - 5:30)

**Screen:** Playground sidebar showing session history

**Actions:**
- Click "+ New Chat"
- Show session list
- Click on a previous session — history loads

**Script:**
Chat sessions persist hote hain. Purani conversations load kar sakte hain. Session memory limit bhi configurable hai.

---

## Scene 9: Client Dashboard (5:30 - 6:30)

**Screen:** Browser at `https://localhost/client`

**Actions:**
- Enter API key: `rbs_rag_sk_03b70e36389b4057bff8561ce87f84de`
- Click Connect
- Show documents list
- Click "View" on a document — opens in new tab
- Click "Delete" on a document
- Then go to Chat section
- Type a question, show answer with sources

**Script:**
Client dashboard mein har client apna data dekh sakta hai. API key se login hota hai. Documents view aur delete kar sakta hai. Aur chat bhi kar sakta hai apne documents se. Client apna system prompt bhi set kar sakta hai chat ke liye.

---

## Scene 10: Widget Embed (6:30 - 7:00)

**Screen:** Open `test-widget.html` in browser (or show widget HTML)

**Actions:**
- Open test-widget.html
- Show floating chatbot widget
- Type a question

**Script:**
Client apni website pe ek floating chatbot widget embed kar sakta hai. Bas ek script tag copy kare, apni website ke body mein paste kare. API key set kare, aur chatbot ready.

---

## Scene 11: System Prompt Customization (7:00 - 7:30)

**Screen:** Show admin playground sidebar, then client dashboard chat

**Actions:**
- In Playground, expand "System Prompt"
- Edit the prompt, click Apply
- Show that the LLM behavior changes

**Script:**
Har tenant ka custom system prompt ho sakta hai. Admin dashboard se set karein, aur client dashboard se bhi temporary override kar sakte hain. Is se LLM ko specific instructions de sakte hain jaise "Only answer in Urdu" ya "Be concise".

---

## Scene 12: Wrap-Up (7:30 - 8:00)

**Script:**
To summarize:
- **Multi-tenant** — har client ka isolated environment
- **Multi-LLM** — Mistral, Gemini, OpenAI, Anthropic
- **Documents + Scraping** — upload ya website scrape
- **RAG Pipeline** — chunking, embedding, retrieval, reranking
- **Admin Dashboard** — manage tenants, config, test chat
- **Client Dashboard** — view docs, chat, embed widget
- **System Prompt** — customizable per tenant

Production ke liye: `RAG_ADMIN_PASSWORD` change karein, `RAG_ENCRYPTION_KEY` set karein, aur proper SSL certificate lagayein.

**End screen:** Show dashboard with smile :)

---

## Quick Reference

| Feature | URL / Command |
|---------|--------------|
| Admin Dashboard | `https://localhost/` |
| Client Dashboard | `https://localhost/client` |
| Health API | `https://localhost/health` |
| Chat API | `POST /api/v1/chat` (header `X-API-Key`) |
| Default Login | admin / admin |
| Client API Key | `rbs_rag_sk_03b70e36389b4057bff8561ce87f84de` (rimsha) |
| Start Services | `./start.sh` |
