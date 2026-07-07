# Running the RAG SaaS Platform on Another System

This guide outlines the minimum commands and configurations required to set up and run the RBS RAG Multi-Tenant SaaS Web Application on a clean system.

---

## Prerequisites

- **Python**: Version `3.11` or higher installed.
- **API Keys**: Access keys for Gemini, OpenAI, or Anthropic (depending on which model providers you choose to run).

---

## 1. Fast Setup Commands

Open a terminal in the project root directory and execute:

```bash
# 1. (Recommended) Install package with local ML support
pip install -e ".[local-ml]"

# Or minimal install:
pip install -e .

# Set Python path (Windows PowerShell):
$env:PYTHONPATH="src"

# 2. Initialize configuration
rag init

# 3. Start the web server
python -m rbs_rag.web_run
```

---

## 2. Platform Access

Once the server boots up, navigate to:

- **Admin Web Dashboard**: [http://localhost:8100](http://localhost:8100)
- **Interactive OpenAPI Documentation**: [http://localhost:8100/docs](http://localhost:8100/docs)
- **Embeddable Chat Interface**: [http://localhost:8100/widget](http://localhost:8100/widget)

---

## 3. Deployment Directory Structure

When running, the server automatically manages isolated workspaces under `.rbs_rag`:

```
.rbs_rag/
├── admin.db                 # Global SaaS settings & client configs
└── tenants/
    ├── client-alpha/        # Isolated directory for Client Alpha
    │   ├── rag.db           # Client Alpha's isolated vector and chat database
    │   └── documents/       # Raw uploaded files (PDF, DOCX, etc.)
    └── client-beta/
        ├── rag.db
        └── documents/
```

---

## 4. Minimum Client Integration Example

To test the system from external applications, clients can use this basic HTML snippet to load a floating chat widget. Just replace `YOUR_API_KEY` with the key generated in the dashboard:

```html
<!DOCTYPE html>
<html>
<head>
    <title>Customer Web Page</title>
</head>
<body>
    <h1>Welcome to Acme Corp</h1>

    <!-- Paste the code below to render the RAG chatbot -->
    <script>
      (function() {
        var iframe = document.createElement('iframe');
        iframe.src = "http://localhost:8000/widget?api_key=YOUR_API_KEY";
        iframe.style = "position: fixed; bottom: 20px; right: 20px; width: 380px; height: 600px; border: none; z-index: 999999; border-radius: 16px; box-shadow: 0 10px 40px rgba(0,0,0,0.5);";
        document.body.appendChild(iframe);
      })();
    </script>
</body>
</html>
```
