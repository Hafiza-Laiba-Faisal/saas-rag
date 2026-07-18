import { createFileRoute, Link } from "@tanstack/react-router";
import { useState, useEffect, useRef } from "react";
import { ArrowLeft, Copy, Check, Play, RefreshCw, Code2 } from "lucide-react";

export const Route = createFileRoute("/widget")({
  head: () => ({
    meta: [
      { title: "Chat Widget — TenBit RAG" },
      { name: "description", content: "Embed the TenBit RAG chat widget on any page." },
    ],
  }),
  component: WidgetPage,
});

// Track injected script so we can re-inject when config changes
let injectedScript: HTMLScriptElement | null = null;

function injectWidgetScript(apiUrl: string, tenant: string, key: string, botName: string) {
  // Remove existing widget if present
  if (injectedScript && injectedScript.parentNode) {
    injectedScript.parentNode.removeChild(injectedScript);
    injectedScript = null;
  }
  // Also remove leftover DOM from previous run
  document.getElementById("rbs-widget-btn")?.remove();
  document.getElementById("rbs-widget-box")?.remove();
  document.querySelectorAll("style").forEach((s) => {
    if (s.textContent?.includes("rbs-widget-btn")) s.remove();
  });
  // Reset guard so widget.js re-runs
  (window as any).__RBSWidgetLoaded = false;

  const script = document.createElement("script");
  script.src = `${apiUrl}/widget.js?t=${Date.now()}`;
  script.setAttribute("data-key", key);
  script.setAttribute("data-tenant", tenant);
  script.setAttribute("data-api-url", apiUrl);
  script.setAttribute("data-name", botName || "Assistant");
  document.body.appendChild(script);
  injectedScript = script;
}

function WidgetPage() {
  const [apiUrl, setApiUrl]   = useState("http://localhost:3001");
  const [tenant, setTenant]   = useState("");
  const [apiKey, setApiKey]   = useState("");
  const [botName, setBotName] = useState("Assistant");

  const [tested,  setTested]  = useState(false);
  const [copied,  setCopied]  = useState(false);
  const [error,   setError]   = useState("");

  // Restore from localStorage on mount
  useEffect(() => {
    setApiUrl(localStorage.getItem("wt_api_url")   || "http://localhost:3001");
    setTenant(localStorage.getItem("wt_tenant")    || "");
    setApiKey(localStorage.getItem("wt_api_key")   || "");
    setBotName(localStorage.getItem("wt_bot_name") || "Assistant");
  }, []);

  // Cleanup widget when leaving page
  useEffect(() => {
    return () => {
      injectedScript?.remove();
      injectedScript = null;
      document.getElementById("rbs-widget-btn")?.remove();
      document.getElementById("rbs-widget-box")?.remove();
      (window as any).__RBSWidgetLoaded = false;
    };
  }, []);

  const embedCode =
`<script
  src="${apiUrl}/widget.js"
  data-tenant="${tenant}"
  data-key="${apiKey}"
  data-api-url="${apiUrl}"
  data-name="${botName}"
></script>`;

  const handleTest = (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!apiKey.trim() || !tenant.trim()) {
      setError("Tenant ID and API Key are required.");
      return;
    }
    localStorage.setItem("wt_api_url",   apiUrl.trim());
    localStorage.setItem("wt_tenant",    tenant.trim());
    localStorage.setItem("wt_api_key",   apiKey.trim());
    localStorage.setItem("wt_bot_name",  botName.trim());

    injectWidgetScript(apiUrl.trim(), tenant.trim(), apiKey.trim(), botName.trim());
    setTested(true);
  };

  const handleReset = () => {
    injectedScript?.remove();
    injectedScript = null;
    document.getElementById("rbs-widget-btn")?.remove();
    document.getElementById("rbs-widget-box")?.remove();
    (window as any).__RBSWidgetLoaded = false;
    setTested(false);
  };

  const copyEmbed = () => {
    navigator.clipboard.writeText(embedCode);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="min-h-screen">
      {/* ── Nav ── */}
      <header className="mx-auto flex max-w-3xl items-center justify-between px-6 py-6">
        <Link
          to="/"
          className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" /> Back
        </Link>
        <div className="text-sm text-muted-foreground">Widget Embed Tester</div>
      </header>

      <div className="mx-auto max-w-3xl space-y-6 px-6 pb-20">
        {/* ── Hero ── */}
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            Test &amp; Embed the Chat Widget
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Fill in your details, click <strong>Run Test</strong> — the chat bubble appears
            on this page so you can verify it works. Then copy the embed snippet.
          </p>
        </div>

        {/* ── Config Form ── */}
        <div className="panel p-6">
          <div className="mb-5 flex items-center justify-between">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Configuration
            </h2>
            {tested && (
              <button
                onClick={handleReset}
                className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-elevated hover:text-foreground"
              >
                <RefreshCw className="h-3 w-3" /> Reset
              </button>
            )}
          </div>

          <form onSubmit={handleTest} className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              {/* API URL */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                  API Base URL
                </label>
                <input
                  type="url"
                  value={apiUrl}
                  onChange={(e) => setApiUrl(e.target.value)}
                  placeholder="http://localhost:3001"
                  className="input w-full"
                  disabled={tested}
                  required
                />
              </div>

              {/* Bot name */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                  Bot Name <span className="opacity-50">(optional)</span>
                </label>
                <input
                  type="text"
                  value={botName}
                  onChange={(e) => setBotName(e.target.value)}
                  placeholder="Assistant"
                  className="input w-full"
                  disabled={tested}
                />
              </div>

              {/* Tenant */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                  Tenant ID <span className="text-destructive">*</span>
                </label>
                <input
                  type="text"
                  value={tenant}
                  onChange={(e) => setTenant(e.target.value)}
                  placeholder="test3"
                  className="input w-full font-mono text-sm"
                  disabled={tested}
                  required
                />
              </div>

              {/* API Key */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                  API Key <span className="text-destructive">*</span>
                </label>
                <input
                  type="text"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="rbs_rag_sk_xxxxxxxxxxxxxxxx"
                  className="input w-full font-mono text-sm"
                  disabled={tested}
                  required
                />
              </div>
            </div>

            {error && (
              <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                {error}
              </p>
            )}

            {!tested ? (
              <button
                type="submit"
                className="inline-flex items-center gap-2 rounded-md bg-[image:var(--gradient-primary)] px-5 py-2.5 text-sm font-semibold text-primary-foreground hover:opacity-90"
              >
                <Play className="h-4 w-4" />
                Run Test
              </button>
            ) : (
              <div className="flex items-center gap-2 rounded-md border border-success/30 bg-success/10 px-4 py-2.5 text-sm text-success">
                <span className="h-2 w-2 rounded-full bg-success animate-pulse" />
                Widget injected — look for the chat bubble at the bottom-right of this page.
              </div>
            )}
          </form>
        </div>

        {/* ── Embed Code ── */}
        <div className="panel p-6">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Code2 className="h-4 w-4 text-muted-foreground" />
              <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Embed Snippet
              </h2>
            </div>
            <button
              onClick={copyEmbed}
              disabled={!apiKey.trim() || !tenant.trim()}
              className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-elevated hover:text-foreground disabled:opacity-40"
            >
              {copied
                ? <><Check className="h-3 w-3 text-success" /> Copied!</>
                : <><Copy className="h-3 w-3" /> Copy</>
              }
            </button>
          </div>

          <pre className="overflow-x-auto rounded-lg border border-border bg-elevated/50 p-4 font-mono text-xs leading-relaxed text-foreground whitespace-pre">
            {embedCode}
          </pre>

          <p className="mt-3 text-xs text-muted-foreground">
            Paste this before the closing{" "}
            <code className="rounded bg-elevated px-1 py-0.5">&lt;/body&gt;</code>{" "}
            tag on any webpage. No framework required — works on plain HTML,
            WordPress, Webflow, etc.
          </p>
        </div>

        {/* ── How it works ── */}
        <div className="panel p-6">
          <h2 className="mb-4 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            How it works
          </h2>
          <ol className="space-y-3 text-sm text-muted-foreground">
            {[
              ["Get your API key", "Copy a tenant API key from the Admin dashboard → Tenants."],
              ["Add the snippet", "Paste the embed code into any page's HTML before </body>."],
              ["Widget loads", "A floating chat bubble appears. Visitors click it to ask questions."],
              ["Streamed answers", "Responses come from your RAG pipeline with source citations."],
            ].map(([title, desc], i) => (
              <li key={i} className="flex gap-3">
                <span className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full bg-primary/20 text-[10px] font-bold text-primary">
                  {i + 1}
                </span>
                <span>
                  <strong className="text-foreground">{title}</strong> — {desc}
                </span>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </div>
  );
}
