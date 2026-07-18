import { createFileRoute, Link } from "@tanstack/react-router";
import { useState, useEffect, useRef } from "react";
import { ArrowLeft, Minus, Send, X, Loader2 } from "lucide-react";
import { streamChat, StreamChunk } from "@/lib/streaming";
import { renderMarkdown } from "@/lib/markdown-renderer";

export const Route = createFileRoute("/widget")({
  head: () => ({
    meta: [
      { title: "Chat Widget Preview — TenBit RAG" },
      { name: "description", content: "Preview of the embeddable TenBit RAG chat widget." },
    ],
  }),
  component: WidgetPage,
});

function WidgetPage() {
  return (
    <div className="min-h-screen">
      <header className="mx-auto flex max-w-5xl items-center justify-between px-6 py-6">
        <Link to="/" className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" /> Back
        </Link>
        <div className="text-sm text-muted-foreground">Widget preview</div>
      </header>

      <div className="mx-auto max-w-5xl px-6 pb-16">
        <div className="text-center">
          <h1 className="text-3xl font-bold tracking-tight md:text-4xl">
            Your customers see this <span className="gradient-text">on any page</span>.
          </h1>
          <p className="mt-3 text-muted-foreground">A branded assistant with cited answers. Add ?api_key=YOUR_KEY to the URL.</p>
        </div>

        {/* Mock browser + widget */}
        <div className="panel mx-auto mt-10 max-w-4xl overflow-hidden">
          <div className="flex items-center gap-2 border-b border-border bg-elevated/60 px-4 py-2.5">
            <span className="h-3 w-3 rounded-full bg-destructive/60" />
            <span className="h-3 w-3 rounded-full bg-warning/60" />
            <span className="h-3 w-3 rounded-full bg-success/60" />
            <div className="mx-auto rounded-md border border-border bg-panel px-3 py-1 text-xs text-muted-foreground">
              acme.com
            </div>
          </div>
          <div className="relative h-[520px] bg-[radial-gradient(600px_400px_at_10%_10%,rgba(99,102,241,0.15),transparent),radial-gradient(600px_400px_at_90%_20%,rgba(56,189,248,0.1),transparent)]">
            <div className="p-10 opacity-40">
              <div className="h-8 w-40 rounded bg-elevated" />
              <div className="mt-6 h-3 w-64 rounded bg-elevated" />
              <div className="mt-2 h-3 w-80 rounded bg-elevated" />
              <div className="mt-2 h-3 w-72 rounded bg-elevated" />
              <div className="mt-8 grid grid-cols-3 gap-4">
                <div className="h-24 rounded-lg bg-elevated" />
                <div className="h-24 rounded-lg bg-elevated" />
                <div className="h-24 rounded-lg bg-elevated" />
              </div>
            </div>

            <div className="absolute bottom-6 right-6 w-[360px] max-w-[90%]">
              <Widget />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
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
  sources?: Source[];
  isStreaming?: boolean;
}

function Widget() {
  const [apiKey, setApiKey] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string>("");
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: "bot", text: "Hello! I can answer questions grounded in our verified database. How can I help you today?" },
  ]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when messages update
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const key = urlParams.get("api_key");
    if (key) {
      setApiKey(key);
    }

    let sid = localStorage.getItem("rbs_rag_widget_session");
    if (!sid) {
      sid = crypto.randomUUID();
      localStorage.setItem("rbs_rag_widget_session", sid);
    }
    setSessionId(sid);
  }, []);

  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    const q = input.trim();
    if (!q || !apiKey) return;
    setInput("");
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
        { query: q, session_id: sessionId, user_id: "widget-user" },
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

  const clearConversation = () => {
    const newSessionId = crypto.randomUUID();
    localStorage.setItem("rbs_rag_widget_session", newSessionId);
    setSessionId(newSessionId);
    setMessages([
      { role: "bot", text: "Hello! I can answer questions grounded in our verified database. How can I help you today?" },
    ]);
  };

  return (
    <div className="flex h-[440px] flex-col overflow-hidden rounded-2xl border border-border bg-panel shadow-2xl backdrop-blur">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border bg-[image:var(--gradient-subtle)] px-4 py-3">
        <div className="flex items-center gap-2.5">
          <div className="grid h-8 w-8 place-items-center rounded-md bg-[image:var(--gradient-primary)] text-sm font-bold text-primary-foreground">
            A
          </div>
          <div>
            <div className="text-sm font-semibold">Acme Assistant</div>
            <div className="flex items-center gap-1.5 text-[10px] text-success">
              <span className="h-1.5 w-1.5 rounded-full bg-success" /> Online
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1 text-muted-foreground">
          <button className="rounded p-1 hover:bg-elevated"><Minus className="h-3.5 w-3.5" /></button>
          <button className="rounded p-1 hover:bg-elevated"><X className="h-3.5 w-3.5" /></button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {messages.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="flex justify-end">
              <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-primary px-3 py-2 text-sm text-primary-foreground">
                {m.text}
              </div>
            </div>
          ) : (
            <div key={i} className="max-w-[85%] space-y-2">
              <div className="rounded-2xl rounded-tl-sm border border-border bg-elevated px-3 py-2 text-sm">
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
                <div className="flex flex-wrap gap-1 px-3">
                  {m.sources.map((s, idx) => (
                    <span
                      key={idx}
                      className="cursor-pointer rounded bg-accent-teal/10 px-1.5 py-0.5 text-xs font-semibold text-accent-teal hover:bg-accent-teal hover:text-background"
                      title={s.section ? `${s.document_name} - ${s.section}` : s.document_name}
                    >
                      [{idx + 1}]
                    </span>
                  ))}
                </div>
              )}
            </div>
          ),
        )}
        <div ref={messagesEndRef} />
      </div>

      <form onSubmit={send} className="flex items-center gap-2 border-t border-border p-3">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type your question…"
          className="input flex-1 text-sm"
          disabled={isLoading || !apiKey}
        />
        <button
          type="submit"
          className="grid h-9 w-9 place-items-center rounded-md bg-[image:var(--gradient-primary)] text-primary-foreground hover:opacity-90 disabled:opacity-50"
          disabled={isLoading || !apiKey}
        >
          {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
        </button>
      </form>
    </div>
  );
}
