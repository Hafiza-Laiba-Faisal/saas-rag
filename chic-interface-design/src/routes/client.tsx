import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useState, useEffect, useRef } from "react";
import { ArrowLeft, Cloud, Database, FileText, Globe, KeyRound, Loader2, MessageSquare, Send, Trash2, Upload, X, Zap } from "lucide-react";
import { streamChat, StreamChunk } from "@/lib/streaming";
import { parseLLMResponse, ParsedContent } from "@/lib/text-parser";
import { renderMarkdown } from "@/lib/markdown-renderer";

export const Route = createFileRoute("/client")({
  head: () => ({
    meta: [
      { title: "Client Workspace — TenBit RAG" },
      { name: "description", content: "Tenant workspace: manage documents and test retrieval with your API key." },
    ],
  }),
  component: ClientPage,
});

interface Document {
  name: string;
  type?: string;
  size_bytes?: number;
  chunks?: number;
  ingested?: boolean;
  ingested_at?: number;
  source?: string;
}

interface Source {
  document_name: string;
  chunk_id: string;
  score?: number;
  content?: string;
  index?: number;
  section?: string;
}

interface ChatMessage {
  role: "bot" | "user";
  text: string;
  parsed?: ParsedContent;
  sources?: Source[];
  isStreaming?: boolean;
}

function ClientPage() {
  const navigate = useNavigate();
  // Initialize from URL param first, then localStorage, then default to empty
  const [apiKey, setApiKey] = useState(() => {
    // Check URL first: ?api_key=xxx
    const urlParams = new URLSearchParams(window.location.search);
    const urlKey = urlParams.get("api_key");
    if (urlKey) return urlKey;
    // Fallback to localStorage for convenience
    return localStorage.getItem("client-api-key") ?? "";
  });
  const [isLoading, setIsLoading] = useState(false);
  const [tab, setTab] = useState<"documents" | "playground">("documents");
  const [docs, setDocs] = useState<Document[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: "bot", text: "Hi! I'm connected to your indexed documents. Ask me anything to test retrieval." },
  ]);
    const [input, setInput] = useState("");
    const [systemPrompt, setSystemPrompt] = useState("");
  const [selectedSource, setSelectedSource] = useState<Source | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const latestSources = messages
    .slice()
    .reverse()
    .find((m) => m.role === "bot" && m.sources && m.sources.length > 0)?.sources ?? [];

  // Auto-scroll to bottom when messages update
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (apiKey) {
      localStorage.setItem("client-api-key", apiKey);
      loadDocuments(apiKey);
    }
  }, [apiKey]);

  const loadDocuments = async (key: string) => {
    try {
      const res = await fetch("/api/v1/client/documents", {
        headers: { "X-API-Key": key },
      });
      if (res.ok) {
        const data = await res.json();
        setDocs(data || []);
      }
    } catch (e) {
      console.error("Failed to load documents:", e);
    }
  };

  const handleApiKeySubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const key = apiKey.trim();
    if (!key) return;
    localStorage.setItem("client-api-key", key);
    setApiKey(key);
    loadDocuments(key);
  };

  const formatFileSize = (bytes?: number) => {
    if (!bytes) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    let size = bytes;
    let i = 0;
    while (size >= 1024 && i < 3) {
      size /= 1024;
      i++;
    }
    return `${size.toFixed(i > 0 ? 1 : 0)} ${units[i]}`;
  };

   const send = async (e: React.FormEvent, systemPrompt?: string) => {
    e.preventDefault();
    const q = input.trim();
    if (!q || !apiKey) return;
    setInput("");
    setSelectedSource(null);
    // Append user message + empty bot placeholder in one update to avoid index drift
    setMessages((m) => [
      ...m,
      { role: "user", text: q },
      { role: "bot", text: "", isStreaming: true },
    ]);
    setIsLoading(true);

    try {
      await streamChat(
        "/api/v1/chat/stream",
        { query: q },
        { "X-API-Key": apiKey },
        {
          onChunk: (chunk: StreamChunk) => {
            setMessages((m) => {
              const updated = [...m];
              const last = updated[updated.length - 1];
              if (last?.role === "bot") {
                updated[updated.length - 1] = {
                  ...last,
                  text: last.text + chunk.text,
                  isStreaming: !chunk.done,
                };
              }
              return updated;
            });
          },
          onComplete: (_fullText, citations) => {
            // Parse the response for structured display
            setMessages((m) => {
              const updated = [...m];
              const last = updated[updated.length - 1];
              if (last?.role === "bot") {
                const parsed = parseLLMResponse(last.text);
                updated[updated.length - 1] = {
                  ...last,
                  isStreaming: false,
                  parsed,
                  sources: citations?.map((c) => ({
                    document_name: c.document_name,
                    chunk_id: c.chunk_id,
                    index: c.index,
                    section: c.section,
                  })),
                };
              }
              return updated;
            });
            setIsLoading(false);
          },
          onError: (error) => {
            setMessages((m) => {
              const updated = [...m];
              const last = updated[updated.length - 1];
              if (last?.role === "bot") {
                updated[updated.length - 1] = {
                  role: "bot",
                  text: `Error: ${error.message}`,
                  isStreaming: false,
                };
              }
              return updated;
            });
            setIsLoading(false);
          },
        }
      );
    } catch (e) {
      setMessages((m) => [
        ...m.slice(0, -1),
        { role: "bot", text: `Error: ${e instanceof Error ? e.message : "Failed to connect"}` },
      ]);
      setIsLoading(false);
    }
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || !apiKey) return;
    const formData = new FormData();
    for (let i = 0; i < files.length; i++) {
      formData.append("files", files[i]);
    }
    setIsLoading(true);
    try {
      const res = await fetch("/api/v1/client/documents", {
        method: "POST",
        headers: { "X-API-Key": apiKey },
        body: formData,
      });
      if (res.ok) {
        loadDocuments(apiKey);
      }
    } catch (e) {
      console.error("Upload failed:", e);
    } finally {
      setIsLoading(false);
    }
  };

  const handleDelete = async (docName: string) => {
    if (!apiKey) return;
    try {
      await fetch(`/api/v1/client/documents/${docName}`, {
        method: "DELETE",
        headers: { "X-API-Key": apiKey },
      });
      loadDocuments(apiKey);
    } catch (e) {
      console.error("Delete failed:", e);
    }
  };

  if (!apiKey) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-panel/20">
        <div className="panel w-full max-w-md p-8">
          <div className="mb-6 text-center">
            <div className="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-lg bg-[image:var(--gradient-primary)] text-xl font-bold text-primary-foreground">
              TB
            </div>
            <h2 className="text-xl font-bold">TenBit RAG</h2>
            <p className="mt-2 text-sm text-muted-foreground">Enter your API key to access your workspace</p>
          </div>
          <form onSubmit={handleApiKeySubmit} className="space-y-4">
            <div>
              <label className="mb-2 block text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                API Key
              </label>
              <input
                type="text"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="Enter your API key"
                className="input w-full"
                required
              />
            </div>
            <button
              type="submit"
              className="w-full rounded-md bg-[image:var(--gradient-primary)] px-4 py-2.5 text-sm font-semibold text-primary-foreground hover:opacity-90"
            >
              Connect
            </button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col">
      {/* Header */}
      <header className="flex flex-wrap items-center justify-between gap-4 border-b border-border bg-panel/40 px-6 py-4 backdrop-blur">
        <div className="flex items-center gap-3">
          <Link to="/" className="rounded-md border border-border bg-panel p-2 text-muted-foreground hover:bg-elevated hover:text-foreground">
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div className="grid h-9 w-9 place-items-center rounded-md bg-[image:var(--gradient-primary)] font-bold text-primary-foreground">
            TB
                </div>
                <div>
                  <button onClick={() => {
                    setMessages([]);
                    setInput("");
                    setSystemPrompt("");
                  }} className="rounded-md border border-border bg-panel px-3 py-1.5 text-xs text-muted-foreground hover:bg-elevated hover:text-foreground">
                  </button>
            <div className="text-[11px] font-semibold uppercase tracking-wider text-primary">Client Workspace</div>
            <h1 className="text-lg font-bold">TenBit RAG</h1>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <KeyRound className="h-3.5 w-3.5" />
            <span className="font-mono">pk_live_••••{apiKey.slice(-4)}</span>
          </div>
          <button
            onClick={() => {
              localStorage.removeItem("client-api-key");
              setApiKey("");
            }}
            className="rounded-md border border-border bg-panel px-3 py-1.5 text-xs text-muted-foreground hover:bg-elevated hover:text-foreground"
          >
            Disconnect
          </button>
        </div>
      </header>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-border bg-panel/20 px-6">
        {[
          { id: "documents" as const, label: "Documents", icon: FileText },
          { id: "playground" as const, label: "Playground", icon: MessageSquare },
        ].map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition ${
              tab === t.id ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            <t.icon className="h-4 w-4" /> {t.label}
          </button>
        ))}
      </div>

      <main className="flex-1 px-6 py-6">
        {tab === "documents" ? (
          <ClientDocumentsTab apiKey={apiKey} docs={docs} onDocsChange={() => loadDocuments(apiKey)} />
        ) : (
          <div className="grid h-[calc(100vh-220px)] gap-4 xl:grid-cols-[1.4fr_320px]">
            <div className="panel flex flex-col">
              <div className="border-b border-border px-5 py-3 text-sm font-semibold">Playground</div>
              <div className="flex-1 space-y-4 overflow-y-auto px-5 py-5">
                {messages.map((m, i) =>
                  m.role === "user" ? (
                    <div key={i} className="flex justify-end">
                      <div className="max-w-[75%] rounded-2xl rounded-br-sm bg-primary px-4 py-2.5 text-sm text-primary-foreground">
                        {m.text}
                      </div>
                    </div>
                  ) : (
                    <div key={i} className="flex gap-3">
                      <div className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-md bg-[image:var(--gradient-primary)] text-xs font-bold text-primary-foreground">
                        TB
                      </div>
                      <div className="max-w-[90%] space-y-2">
                        <div className="break-words whitespace-pre-wrap rounded-2xl rounded-tl-sm border border-border bg-elevated px-4 py-2.5 text-sm">
                          {m.isStreaming ? (
                            <>
                              {m.text ? renderMarkdown(m.text) : <Loader2 className="h-4 w-4 animate-spin" />}
                              {m.text && <span className="inline-block ml-1 w-2 h-4 bg-primary animate-pulse" />}
                            </>
                          ) : (
                            renderMarkdown(m.text)
                          )}
                        </div>
                        {m.sources && m.sources.length > 0 && !m.isStreaming && (
                          <div className="flex flex-wrap gap-1.5">
                            {m.sources.map((s, idx) => (
                              <button
                                key={idx}
                                type="button"
                                onClick={() => setSelectedSource(s)}
                                className="cursor-pointer rounded bg-accent-teal/10 px-1.5 py-0.5 text-xs font-semibold text-accent-teal hover:bg-accent-teal hover:text-background"
                                title={s.section ? `${s.document_name} - ${s.section}` : s.document_name}
                              >
                                [{idx + 1}]
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  ),
                )}
                <div ref={messagesEndRef} />
              </div>
               <form onSubmit={(e) => send(e, systemPrompt)} className="flex items-center gap-2 border-t border-border px-4 py-3">
                 <div className="flex flex-col sm:flex-row gap-2">
                   <input
                     value={systemPrompt || ""}
                     onChange={(e) => setSystemPrompt(e.target.value)}
                     className="input flex-1"
                     placeholder="System prompt (optional)"
                     disabled={isLoading}
                   />
                 </div>
                 <input
                   value={input}
                   onChange={(e) => setInput(e.target.value)}
                   className="input flex-1"
                   placeholder="Type your query to test retrieval…"
                   disabled={isLoading}
                 />
                 <button
                   type="submit"
                   className="inline-flex items-center gap-1.5 rounded-md bg-[image:var(--gradient-primary)] px-4 py-2 text-sm font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50"
                   disabled={isLoading}
                 >
                   {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                   {isLoading ? "Sending..." : "Send"}
                 </button>
              </form>
            </div>

            <div className="panel flex flex-col p-4">
               <div className="mb-3 flex items-center justify-between gap-3">
                 <div>
                    <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Retrieved Context</div>
                    <div className="text-sm font-semibold">Sources</div>
                  </div>
                  <button onClick={() => {
                    setMessages([]);
                    setInput("");
                    setSystemPrompt("");
                    setSelectedSource(null);
                 }} className="rounded-md border border-border bg-panel px-3 py-1.5 text-xs text-muted-foreground hover:bg-elevated hover:text-foreground">
                    Clear
                  </button>
               </div>
               <div className="flex-1 overflow-y-auto space-y-2 pt-2">
                {latestSources.length === 0 ? (
                  <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
                    No sources retrieved yet.
                  </div>
                ) : (
                  latestSources.map((source, idx) => (
                    <button
                      key={`${source.chunk_id}-${idx}`}
                      type="button"
                      onClick={() => setSelectedSource(source)}
                      className="w-full rounded-lg border border-border bg-elevated/50 p-3 text-left transition hover:border-primary/50"
                    >
                      <div className="mb-1 flex items-center justify-between">
                        <span className="text-[10px] font-semibold uppercase tracking-wider text-primary">
                          {source.document_name}
                        </span>
                        <span className="text-[10px] text-muted-foreground">[{idx + 1}]</span>
                      </div>
                      <div className="mb-1 text-[11px] text-muted-foreground">{source.section || "General"}</div>
                      <p className="whitespace-pre-wrap break-words text-xs text-muted-foreground">
                        {source.content ? source.content : "Open to inspect the full chunk."}
                      </p>
                    </button>
                  ))
                )}
              </div>
            </div>
          </div>
        )}
      </main>
      {selectedSource && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm" onClick={() => setSelectedSource(null)}>
          <div className="absolute right-0 top-0 h-full w-[380px] border-l border-border bg-panel p-6 shadow-2xl overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="mb-6 flex items-center justify-between">
              <h3 className="text-sm font-bold uppercase tracking-wider text-primary">Context Details</h3>
              <button onClick={() => setSelectedSource(null)} className="text-muted-foreground hover:text-foreground">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="mb-3 rounded-lg border border-border bg-elevated/50 p-4">
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Source Document</div>
              <div className="text-sm text-primary">{selectedSource.document_name}</div>
            </div>
            <div className="mb-3 rounded-lg border border-border bg-elevated/50 p-4">
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Section</div>
              <div className="text-sm">{selectedSource.section || "General"}</div>
            </div>
            {selectedSource.score != null && (
              <div className="mb-3 rounded-lg border border-border bg-elevated/50 p-4">
                <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Score</div>
                <div className="font-mono text-sm text-success">{selectedSource.score.toFixed(4)}</div>
              </div>
            )}
            <div className="rounded-lg border border-border bg-elevated/50 p-4">
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Indexed Text</div>
              <div className="whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">
                {selectedSource.content || "No chunk preview available."}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Helper components ────────────────────────────────────────────────────────

function ClientField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-medium text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

function ClientPill({ status }: { status: string }) {
  const map: Record<string, string> = {
    indexed: "bg-success/15 text-success",
    queued: "bg-muted-foreground/15 text-muted-foreground",
    error: "bg-destructive/15 text-destructive",
  };
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium capitalize ${map[status] ?? map.queued}`}>
      {status}
    </span>
  );
}

// ─── ClientDocumentsTab ───────────────────────────────────────────────────────

function ClientDocumentsTab({
  apiKey,
  docs,
  onDocsChange,
}: {
  apiKey: string;
  docs: Document[];
  onDocsChange: () => void;
}) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [source, setSource] = useState<"files" | "web" | "cloud">("files");
  const [uploading, setUploading] = useState(false);
  const [applyOcr, setApplyOcr] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [ingestProgress, setIngestProgress] = useState<{
    status: string; progress: number; logs: string[]; summary?: any;
  } | null>(null);
  const [scrapeUrl, setScrapeUrl] = useState("");
  const [scrapeDepth, setScrapeDepth] = useState(3);
  const [scrapePages, setScrapePages] = useState(100);
  const [scraping, setScraping] = useState(false);
  const [scrapeResult, setScrapeResult] = useState<any>(null);
  const [crawlToggle, setCrawlToggle] = useState(false);
  const [viewDoc, setViewDoc] = useState<string | null>(null);
  const [chunks, setChunks] = useState<any[]>([]);
  const [chunksLoading, setChunksLoading] = useState(false);
  const [cloudSyncOpen, setCloudSyncOpen] = useState(false);

  async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files;
    if (!files || !files.length) return;
    setUploading(true);
    try {
      const form = new FormData();
      for (let i = 0; i < files.length; i++) form.append("files", files[i]);
      await fetch(`/api/v1/client/documents?apply_ocr=${applyOcr}`, {
        method: "POST",
        headers: { "X-API-Key": apiKey },
        body: form,
      });
      onDocsChange();
      // Auto-trigger ingest after upload
      handleIngest(applyOcr);
    } catch (e: any) {
      alert("Upload failed: " + e.message);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function handleIngest(withOcr = false) {
    setIngesting(true);
    setIngestProgress({ status: "starting", progress: 0, logs: [] });
    try {
      await fetch(`/api/v1/client/ingest?apply_ocr=${withOcr}`, {
        method: "POST",
        headers: { "X-API-Key": apiKey },
      });
      const poll = setInterval(async () => {
        try {
          const res = await fetch("/api/v1/client/ingest/status", { headers: { "X-API-Key": apiKey } });
          const data = await res.json();
          setIngestProgress(data);
          if (["completed", "error", "idle"].includes(data.status)) {
            clearInterval(poll);
            setIngesting(false);
            onDocsChange();
          }
        } catch { clearInterval(poll); setIngesting(false); }
      }, 1500);
    } catch (e: any) {
      setIngesting(false);
      alert("Ingest failed: " + e.message);
    }
  }

  async function handleScrape() {
    if (!scrapeUrl) return;
    setScraping(true);
    setScrapeResult(null);
    try {
      const res = await fetch("/api/v1/client/scrape", {
        method: "POST",
        headers: { "X-API-Key": apiKey, "Content-Type": "application/json" },
        body: JSON.stringify({ url: scrapeUrl, max_depth: scrapeDepth, max_pages: scrapePages, crawl: crawlToggle }),
      });
      setScrapeResult(await res.json());
      onDocsChange();
    } catch (e: any) {
      setScrapeResult({ status: "failed", error: e.message });
    } finally {
      setScraping(false);
    }
  }

  async function handleDelete(filename: string) {console.log("Deleting document:", filename);
    if (!confirm(`Delete ${filename}?`)) return;
    try {
      await fetch(`/api/v1/client/documents/${encodeURIComponent(filename)}`, {
        method: "DELETE",
        headers: { "X-API-Key": apiKey },
      });
      onDocsChange();
    } catch (e: any) {
      alert("Delete failed: " + e.message);
    }
  }

  async function handleViewChunks(filename: string) {
     setViewDoc(filename);
     setChunksLoading(true);
     setChunks([]);
     try {
       const res = await fetch(`/api/v1/client/documents/${encodeURIComponent(filename)}/chunks`, {
         headers: { "X-API-Key": apiKey },
       });
       const data = await res.json();
       setChunks(Array.isArray(data) ? data : []);
     } catch (e) {
       setChunks([]);
     }
     finally { setChunksLoading(false); }
    setViewDoc(filename);
    setChunksLoading(true);
    setChunks([]);
    try {
      const res = await fetch(`/api/v1/client/documents/${encodeURIComponent(filename)}/chunks`, {
        headers: { "X-API-Key": apiKey },
      });
      const data = await res.json();
      setChunks(Array.isArray(data) ? data : []);
    } catch { setChunks([]); }
    finally { setChunksLoading(false); }
  }

  function formatSize(bytes?: number) {
    if (!bytes) return "—";
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  const srcColors: Record<string, string> = {
    upload: "bg-[color:var(--accent-violet)]/10 text-[color:var(--accent-violet)] border-[color:var(--accent-violet)]/20",
    scrape: "bg-[color:var(--accent-sky)]/10 text-[color:var(--accent-sky)] border-[color:var(--accent-sky)]/20",
    cloud: "bg-success/10 text-success border-success/20",
  };

  return (
    <div className="space-y-6">
      {/* Source cards */}
      <div className="grid gap-3 md:grid-cols-3">
        {[
          { id: "files" as const, label: "File upload", desc: "PDF, DOCX, MD, TXT, CSV, HTML", icon: Upload, color: "#f59e0b" },
          { id: "web" as const, label: "Web scraping", desc: "Crawl a URL and index it.", icon: Globe, color: "#0ea5e9" },
          { id: "cloud" as const, label: "Cloud sync", desc: "Google Drive, Notion, S3…", icon: Cloud, color: "#22c55e" },
        ].map(({ id, label, desc, icon: Icon, color }) => (
          <button
            key={id}
            onClick={() => setSource(id)}
            className="relative overflow-hidden rounded-xl p-5 text-left transition"
            style={{
              background: source === id ? color : "var(--panel)",
              color: source === id ? "#fff" : "var(--color-foreground)",
              border: `1px solid ${source === id ? "transparent" : "var(--panel-border)"}`,
              boxShadow: source === id ? `0 12px 34px -14px ${color}66` : undefined,
            } as React.CSSProperties}
          >
            <div className="grid h-10 w-10 place-items-center rounded-lg" style={{ background: source === id ? "rgba(0,0,0,0.18)" : color, color: "#fff" }}>
              <Icon className="h-5 w-5" />
            </div>
            {source === id && <span className="absolute right-3 top-3 rounded-full bg-black/25 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider">Selected</span>}
            <div className="mt-3 text-base font-bold">{label}</div>
            <div className={`mt-1 text-xs ${source === id ? "opacity-85" : "text-muted-foreground"}`}>{desc}</div>
          </button>
        ))}
      </div>

      {/* Files panel */}
      {source === "files" && (
        <div className="panel p-6">
          <div className="rounded-xl border-2 border-dashed border-border bg-elevated/40 p-8 text-center">
            <Upload className="mx-auto h-8 w-8 text-primary" />
            <p className="mt-3 text-sm font-medium">Drop files here or click to browse</p>
            <p className="mt-1 text-xs text-muted-foreground">PDF, DOCX, PPTX, MD, TXT, HTML, CSV, JSON</p>
            <input ref={fileInputRef} type="file" multiple className="hidden" onChange={handleFileUpload} />
            <button disabled={uploading} onClick={() => fileInputRef.current?.click()}
              className="mt-4 inline-flex items-center gap-1.5 rounded-md bg-[image:var(--gradient-primary)] px-4 py-2 text-xs font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50">
              {uploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
              {uploading ? "Uploading..." : "Select files"}
            </button>
            <label className="mt-3 inline-flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={applyOcr} onChange={(e) => setApplyOcr(e.target.checked)} className="accent-primary" />
              <span className="text-xs text-muted-foreground">Apply OCR</span>
            </label>
          </div>
          <div className="mt-4 flex gap-3">
            <button onClick={() => handleIngest(false)} disabled={ingesting}
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-panel px-4 py-2 text-xs font-medium hover:bg-elevated disabled:opacity-50">
              {ingesting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />}
              Ingest pending
            </button>
            <button onClick={() => handleIngest(true)} disabled={ingesting}
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-panel px-4 py-2 text-xs font-medium hover:bg-elevated disabled:opacity-50">
              <FileText className="h-3.5 w-3.5" /> Ingest with OCR
            </button>
          </div>
          {ingestProgress && ingestProgress.status !== "idle" && (
            <div className="mt-4 space-y-3">
              <div className="panel p-4">
                <div className="flex items-center justify-between text-xs mb-2">
                  <span className="font-semibold capitalize">{ingestProgress.status}</span>
                  <span>{ingestProgress.progress}%</span>
                </div>
                <div className="h-2 rounded-full bg-elevated overflow-hidden">
                  <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${ingestProgress.progress}%` }} />
                </div>
              </div>
              {ingestProgress.logs && ingestProgress.logs.length > 0 && (
                <div className="max-h-28 overflow-y-auto rounded bg-[#0a1020] p-2 font-mono text-[10px] leading-relaxed text-foreground/70">
                  {ingestProgress.logs.map((l, i) => <div key={i}>{l}</div>)}
                </div>
              )}
              {ingestProgress.summary && (
                <div className="text-[10px] text-muted-foreground">
                  Docs: {ingestProgress.summary.documents} · Chunks: {ingestProgress.summary.chunks} · Skipped: {ingestProgress.summary.skipped}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Web scrape panel */}
      {source === "web" && (
        <div className="panel p-6">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Scrape a web page</h3>
          <div className="mt-4 grid gap-4 md:grid-cols-[1fr_140px_140px_auto]">
            <ClientField label="URL">
              <input className="input font-mono text-xs" value={scrapeUrl} onChange={(e) => setScrapeUrl(e.target.value)} placeholder="https://docs.example.com/page" />
            </ClientField>
            <ClientField label="Max depth">
              <input className="input" type="number" value={scrapeDepth} onChange={(e) => setScrapeDepth(Number(e.target.value))} />
            </ClientField>
            <ClientField label="Max pages">
              <input className="input" type="number" value={scrapePages} onChange={(e) => setScrapePages(Number(e.target.value))} />
            </ClientField>
            <div className="flex items-end">
              <button disabled={scraping || !scrapeUrl} onClick={handleScrape}
                className="inline-flex h-[38px] items-center gap-1.5 rounded-md bg-[image:var(--gradient-primary)] px-4 text-xs font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50">
                {scraping ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />}
                {scraping ? "Scraping..." : "Start scrape"}
              </button>
            </div>
          </div>
          <label className="mt-3 inline-flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={crawlToggle} onChange={(e) => setCrawlToggle(e.target.checked)} className="accent-primary" />
            <span className="text-xs text-muted-foreground">Crawl linked pages</span>
          </label>
          {scrapeResult && (
            <div className="mt-3 rounded-lg border border-border bg-elevated/50 p-3 text-xs">
              {scrapeResult.status === "completed"
                ? <div className="text-success font-semibold">✅ Scraped {scrapeResult.files_saved} file(s) from {scrapeResult.url}</div>
                : <div className="text-destructive">❌ {scrapeResult.error || "Scrape failed"}</div>}
            </div>
          )}
        </div>
      )}

      {/* Cloud panel */}
      {source === "cloud" && (
        <div className="panel p-6">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Connect a cloud source</h3>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            {["Google Drive", "Notion", "Confluence", "Dropbox", "OneDrive", "S3 Bucket"].map((name) => (
              <button key={name} onClick={() => setCloudSyncOpen(true)}
                className="flex items-center justify-between rounded-lg border border-border bg-elevated/50 px-4 py-3 text-sm hover:border-primary/50 hover:bg-elevated">
                <span className="font-medium">{name}</span>
                <span className="text-xs text-[color:var(--accent-emerald)]">Connect</span>
              </button>
            ))}
          </div>
          {cloudSyncOpen && (
            <div className="mt-4 rounded-xl border border-border bg-elevated/30 p-5">
              <ClientCloudSyncForm apiKey={apiKey} onClose={() => setCloudSyncOpen(false)} onDone={onDocsChange} />
            </div>
          )}
        </div>
      )}

      {/* Documents table */}
      <div className="panel overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <div className="text-sm font-semibold">Documents</div>
          <div className="text-xs text-muted-foreground">{docs.length} files</div>
        </div>
        {docs.length === 0 ? (
          <div className="py-12 text-center text-xs text-muted-foreground">No documents yet. Upload files to get started.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-elevated/60 text-left text-xs uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-5 py-3">Name</th>
                <th className="px-5 py-3">Source</th>
                <th className="px-5 py-3">Size</th>
                <th className="px-5 py-3">Chunks</th>
                <th className="px-5 py-3">Status</th>
                <th className="px-5 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {docs.map((d, i) => {
                const src = d.source || "upload";
                return (
                  <tr key={d.name || i} className="hover:bg-elevated/40">
                    <td className="px-5 py-3 font-medium">
                      <div className="flex items-center gap-2"><FileText className="h-4 w-4 text-primary" /> {d.name}</div>
                    </td>
                    <td className="px-5 py-3">
                      <span className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-bold uppercase border ${srcColors[src] || srcColors.upload}`}>{src}</span>
                    </td>
                    <td className="px-5 py-3 text-muted-foreground text-xs">{formatSize(d.size_bytes)}</td>
                    <td className="px-5 py-3 font-mono text-xs">{d.chunks ?? "—"}</td>
                    <td className="px-5 py-3"><ClientPill status={d.ingested ? "indexed" : "queued"} /></td>
                    <td className="px-5 py-3 text-right">
                      <div className="flex items-center justify-end gap-1">
                        <button onClick={() => handleViewChunks(d.name)} className="rounded p-1.5 text-muted-foreground hover:bg-elevated" title="View chunks">
                          <Database className="h-4 w-4" />
                        </button>
                        <button onClick={() => handleDelete(d.name)} className="rounded p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive" title="Delete">
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Chunk viewer modal */}
      {viewDoc && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 backdrop-blur-sm" onClick={() => setViewDoc(null)}>
          <div className="flex max-h-[80vh] w-full max-w-2xl flex-col rounded-xl border border-border bg-[var(--modal-bg)] shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-border px-6 py-4">
              <div>
                <h2 className="text-base font-bold">Chunks: {viewDoc}</h2>
                <p className="text-xs text-muted-foreground">{chunks.length} chunk{chunks.length !== 1 ? "s" : ""}</p>
              </div>
              <button onClick={() => setViewDoc(null)} className="rounded-md p-1.5 text-muted-foreground hover:bg-elevated"><X className="h-4 w-4" /></button>
            </div>
            <div className="flex-1 overflow-y-auto p-6 space-y-3">
              {chunksLoading ? (
                <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
                  <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading chunks...
                </div>
              ) : chunks.length === 0 ? (
                <div className="py-12 text-center text-xs text-muted-foreground">No chunks found</div>
              ) : (
                chunks.map((c: any, i: number) => (
                  <div key={c.chunk_id || i} className="rounded-lg border border-border bg-elevated/50 p-4">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[10px] font-semibold text-primary">Chunk #{c.ordinal ?? i}</span>
                      <span className="font-mono text-[9px] text-muted-foreground">{c.chunk_id?.substring(0, 12)}...</span>
                    </div>
                    <p className="text-xs leading-relaxed text-foreground/80 whitespace-pre-wrap">{c.text}</p>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ClientCloudSyncForm({ apiKey, onClose, onDone }: { apiKey: string; onClose: () => void; onDone: () => void }) {
  const [provider, setProvider] = useState("direct_url");
  const [urlOrId, setUrlOrId] = useState("");
  const [token, setToken] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [result, setResult] = useState<any>(null);

  async function handleSync(e: React.FormEvent) {
    e.preventDefault();
    if (!urlOrId.trim()) return;
    setSyncing(true); setResult(null);
    try {
      const res = await fetch("/api/v1/client/cloud-sync", {
        method: "POST",
        headers: { "X-API-Key": apiKey, "Content-Type": "application/json" },
        body: JSON.stringify({ provider, cloud_url_or_id: urlOrId.trim(), api_key_or_token: token || null, auto_ingest: true }),
      });
      setResult(await res.json());
      onDone();
    } catch (e: any) {
      setResult({ status: "failed", errors: [e.message] });
    } finally { setSyncing(false); }
  }

  return (
    <form onSubmit={handleSync} className="space-y-4">
      <ClientField label="Provider">
        <select className="input" value={provider} onChange={(e) => setProvider(e.target.value)}>
          <option value="direct_url">Direct URL</option>
          <option value="google_drive">Google Drive</option>
          <option value="onedrive">OneDrive</option>
        </select>
      </ClientField>
      <ClientField label={provider === "direct_url" ? "File URL" : "File ID or URL"}>
        <input className="input font-mono text-xs" value={urlOrId} onChange={(e) => setUrlOrId(e.target.value)} placeholder="https://example.com/file.pdf" />
      </ClientField>
      {provider !== "direct_url" && (
        <ClientField label="Token (optional)">
          <input className="input font-mono text-xs" value={token} onChange={(e) => setToken(e.target.value)} placeholder="API key or OAuth token" />
        </ClientField>
      )}
      <div className="flex gap-3">
        <button type="submit" disabled={syncing || !urlOrId}
          className="inline-flex items-center gap-2 rounded-md bg-[image:var(--gradient-primary)] px-5 py-2 text-sm font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50">
          {syncing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Cloud className="h-4 w-4" />}
          {syncing ? "Syncing..." : "Start Sync"}
        </button>
        <button type="button" onClick={onClose} className="rounded-md border border-border bg-panel px-4 py-2 text-sm font-medium hover:bg-elevated">Cancel</button>
      </div>
      {result && (
        <div className={`rounded-lg p-3 text-xs ${result.status === "success" ? "bg-success/10 text-success" : "bg-destructive/10 text-destructive"}`}>
          {result.status === "success" ? `✅ Synced ${result.count} file(s)` : `❌ ${result.errors?.join(" | ") || "Sync failed"}`}
        </div>
      )}
    </form>
  );
}
