import { createFileRoute, Link } from "@tanstack/react-router";
import { useMemo, useState, useEffect, useRef } from "react";
import {
  Activity,
  ArrowLeft,
  BookOpen,
  ChevronDown,
  ChevronRight,
  Cloud,
  Code2,
  Copy,
  Database,
  FileText,
  Gauge,
  Globe,
  KeyRound,
  Link2,
  Loader2,
  MessageSquare,
  Package,
  Plus,
  RefreshCw,
  Search,
  Send,
  Settings,
  Settings2,
  ShieldCheck,
  Sparkles,
  Trash2,
  Upload,
  Webhook,
  X,
  Zap,
} from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch, getAuthToken } from "@/lib/api";
import { renderMarkdown } from "@/lib/markdown-renderer";


export const Route = createFileRoute("/admin")({
  head: () => ({
    meta: [
      { title: "Admin Dashboard — TenBit RAG" },
      { name: "description", content: "Operator console: manage tenants, LLM providers, documents, and system health." },
    ],
  }),
  component: AdminPage,
});

type Tenant = {
  id: string;
  name: string;
  tier: string;
  status: string;
  docs: number;
  fee: number;
  apiKey?: string;
};

const tabs = [
  { id: "config", label: "Configuration", icon: Settings },
  { id: "documents", label: "Documents", icon: FileText },
  { id: "playground", label: "Playground", icon: MessageSquare },
  { id: "health", label: "Health", icon: Activity },
  { id: "integration", label: "Integration API", icon: Code2 },
  { id: "settings", label: "Settings", icon: Settings2 },
  { id: "console", label: "Console Terminal", icon: Webhook },
] as const;

type TabId = (typeof tabs)[number]["id"];

function AdminPage() {
  useEffect(() => {
    const token = getAuthToken();
    if (!token) {
      window.location.href = '/login';
    }
  }, []);

  const { data: serverTenants, isLoading } = useQuery({
    queryKey: ["tenants"],
    queryFn: async () => {
      const res = await apiFetch("/tenants");
      const data = await res.json();
      return data.map((t: any) => ({
        id: t.tenantId,
        name: t.name || t.tenantId,
        tier: t.subscriptionTier || t.subscription_tier || "basic",
        status: t.status || "active",
        docs: t.docCount ?? 0,
        fee: t.monthlyFee ?? 0,
        apiKey: t.apiKey,
      })) as Tenant[];
    },
  });

  const tenants = serverTenants || [];
  const [activeId, setActiveId] = useState<string | null>(null);
  const [tab, setTab] = useState<TabId>("config");
  const [query, setQuery] = useState("");
  const [showAddTenant, setShowAddTenant] = useState(false);
  const [showCloudSync, setShowCloudSync] = useState(false);
  const [showSystemLogs, setShowSystemLogs] = useState(false);

  // Select the first tenant if none is active
  useEffect(() => {
    if (!activeId && tenants.length > 0) {
      setActiveId(tenants[0].id);
    }
  }, [tenants, activeId]);

  const active = useMemo(() => tenants.find((t) => t.id === activeId) ?? null, [tenants, activeId]);
  const filtered = tenants.filter((t) => t.name.toLowerCase().includes(query.toLowerCase()));

  return (
    <div className="grid min-h-screen grid-cols-[280px_1fr]">
      {/* Sidebar */}
      <aside className="flex flex-col border-r border-border bg-panel/60 backdrop-blur">
        <div className="flex items-center justify-between px-5 py-5">
          <Link to="/" className="flex items-center gap-2">
            <div className="grid h-8 w-8 place-items-center rounded-md bg-[image:var(--gradient-primary)] text-sm font-bold text-primary-foreground">T</div>
            <div>
              <div className="text-sm font-semibold">TenBit RAG</div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Admin</div>
            </div>
          </Link>
          <Link to="/" className="rounded-md p-1.5 text-muted-foreground hover:bg-elevated hover:text-foreground">
            <ArrowLeft className="h-4 w-4" />
          </Link>
        </div>

        <div className="px-4 pb-3">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search tenants…"
              className="w-full rounded-md border border-border bg-elevated py-2 pl-8 pr-3 text-sm outline-none placeholder:text-muted-foreground focus:border-primary/60"
            />
          </div>
        </div>

        <div className="px-4 pb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Subscribers · {filtered.length}
        </div>

        <div className="flex-1 space-y-1 overflow-y-auto px-2">
          {filtered.map((t) => (
            <button
              key={t.id}
              onClick={() => setActiveId(t.id)}
              className={`group flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm transition ${
                activeId === t.id ? "bg-primary/15 text-foreground" : "text-muted-foreground hover:bg-elevated hover:text-foreground"
              }`}
            >
              <div className="min-w-0">
                <div className="truncate font-medium">{t.name}</div>
                <div className="mt-0.5 flex items-center gap-1.5 text-[11px]">
                  <StatusDot status={t.status} />
                  <span className="text-muted-foreground">{t.tier}</span>
                </div>
              </div>
              <ChevronRight className="h-4 w-4 opacity-0 transition group-hover:opacity-60" />
            </button>
          ))}
        </div>

        <div className="border-t border-border p-4">
          <button onClick={() => setShowAddTenant(true)} className="flex w-full items-center justify-center gap-2 rounded-md bg-[image:var(--gradient-primary)] px-3 py-2 text-sm font-semibold text-primary-foreground transition hover:opacity-90">
            <Plus className="h-4 w-4" /> Add New Client
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex flex-col overflow-hidden">
        {active ? (
          <>
            <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border bg-panel/40 px-8 py-5 backdrop-blur">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-wider text-primary">Workspace</div>
                <h1 className="mt-0.5 text-2xl font-bold tracking-tight">{active.name}</h1>
                <div className="mt-1 flex items-center gap-3 text-xs text-muted-foreground">
                  <span className="inline-flex items-center gap-1.5"><StatusDot status={active.status} /> {active.status}</span>
                  <span>·</span>
                  <span>Tier: <span className="text-foreground">{active.tier}</span></span>
                  <span>·</span>
                  <span>{active.docs.toLocaleString()} documents</span>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <GhostBtn icon={Cloud} onClick={() => setShowCloudSync(true)}>Cloud Sync</GhostBtn>
                <GhostBtn icon={Activity} onClick={() => setShowSystemLogs(true)}>System Logs</GhostBtn>
                <GhostBtn icon={Trash2} tone="danger">Delete</GhostBtn>
              </div>
            </div>

            {/* Tabs */}
            <div className="flex gap-1 border-b border-border bg-panel/20 px-8">
              {tabs.map((t) => (
                <button
                  key={t.id}
                  onClick={() => setTab(t.id)}
                  className={`flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition ${
                    tab === t.id
                      ? "border-primary text-foreground"
                      : "border-transparent text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <t.icon className="h-4 w-4" /> {t.label}
                </button>
              ))}
            </div>

            <div className="flex-1 overflow-y-auto px-8 py-6">
              {tab === "config" && <ConfigTab tenant={active} />}
              {tab === "documents" && <DocumentsTab tenantId={active?.id} />}
              {tab === "playground" && <PlaygroundTab tenantId={active?.id} />}
              {tab === "health" && <HealthTab />}
              {tab === "integration" && <IntegrationTab tenantId={active.id} />}
              {tab === "settings" && <SettingsTab />}
              {tab === "console" && <ConsoleTab tenant={active} />}
            </div>
          </>
        ) : (
          <EmptyState />
        )}
      </main>
      {showAddTenant && <AddTenantModal onClose={() => setShowAddTenant(false)} />}
      {showCloudSync && <CloudSyncModal tenantId={active?.id || ""} onClose={() => setShowCloudSync(false)} />}
      {showSystemLogs && <SystemLogsModal tenantId={active?.id} onClose={() => setShowSystemLogs(false)} />}
    </div>
  );
}

function StatusDot({ status }: { status: string }) {
  const cls: Record<string, string> = {
    active: "bg-success",
    trial: "bg-warning",
    suspended: "bg-destructive",
  };
  return <span className={`h-1.5 w-1.5 rounded-full ${cls[status] || "bg-muted-foreground"}`} />;
}

function GhostBtn({
  icon: Icon,
  children,
  tone = "default",
  onClick,
}: {
  icon: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
  tone?: "default" | "danger";
  onClick?: () => void;
}) {
  const toneCls =
    tone === "danger"
      ? "text-destructive hover:bg-destructive/10 border-destructive/30"
      : "hover:bg-elevated";
  return (
    <button onClick={onClick} className={`inline-flex items-center gap-1.5 rounded-md border border-border bg-panel px-3 py-1.5 text-xs font-medium transition ${toneCls}`}>
      <Icon className="h-3.5 w-3.5" /> {children}
    </button>
  );
}

function AddTenantModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const { data: providerPresets = [] } = useQuery({
    queryKey: ["provider-presets"],
    queryFn: async () => {
      const res = await apiFetch("/admin/providers");
      return res.json();
    },
  });
  const [tid, setTid] = useState("");
  const [name, setName] = useState("");
  const [tier, setTier] = useState("basic");
  const [fee, setFee] = useState(299);
  const [llmProvider, setLlmProvider] = useState("gemini");
  const [llmModel, setLlmModel] = useState(providerDefaults.gemini);
  const [llmUrl, setLlmUrl] = useState("");
  const [llmKey, setLlmKey] = useState("");
  const [embedProvider, setEmbedProvider] = useState("hash");
  const [embedModel, setEmbedModel] = useState("BAAI/bge-small-en-v1.5");
  const [embedDims, setEmbedDims] = useState(384);
  const [embedUrl, setEmbedUrl] = useState("");
  const [embedKey, setEmbedKey] = useState("");
  const [error, setError] = useState("");

  const create = useMutation({
    mutationFn: async () => {
      const res = await apiFetch("/tenants", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: tid, name,
          subscription_tier: tier,
          monthly_fee: fee,
          llm_provider: llmProvider,
          llm_model: llmModel,
          llm_base_url: llmUrl || null,
          llm_api_key: llmKey || null,
          embedding_provider: embedProvider,
          embedding_model: embedModel,
          embedding_dimensions: Number(embedDims),
          embedding_base_url: embedUrl || null,
          embedding_api_key: embedKey || null,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Failed to create tenant");
      }
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tenants"] });
      onClose();
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="w-full max-w-2xl rounded-xl border border-border bg-[var(--modal-bg)] p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-bold">Add New Client</h2>
          <button onClick={onClose} className="rounded-md p-1.5 text-muted-foreground hover:bg-elevated"><X className="h-4 w-4" /></button>
        </div>
        {error && <div className="mb-4 rounded-lg bg-destructive/10 p-3 text-xs text-destructive">{error}</div>}
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Client ID (slug)">
              <input className="input" value={tid} onChange={(e) => setTid(e.target.value)} placeholder="my-company" required />
            </Field>
            <Field label="Client Name">
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="My Company" />
            </Field>
            <Field label="Subscription Tier">
              <select className="input" value={tier} onChange={(e) => setTier(e.target.value)}>
                <option value="basic">Basic ($199/mo)</option>
                <option value="premium">Premium ($299/mo)</option>
                <option value="enterprise">Enterprise ($599/mo)</option>
              </select>
            </Field>
            <Field label="Monthly Fee ($)">
              <input className="input" type="number" value={fee} onChange={(e) => setFee(Number(e.target.value))} />
            </Field>
          </div>
          <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground pt-2">LLM Configuration</h3>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Provider">
              <select className="input" value={llmProvider} onChange={(e) => {
                const p = e.target.value;
                setLlmProvider(p);
                setLlmModel(providerDefaults[p] || llmModel);
              }}>
                <option value="gemini">Google Gemini Cloud</option>
                <option value="mistral">Mistral Cloud</option>
                <option value="openai">OpenAI</option>
                <option value="nvidia">NVIDIA NIM Cloud</option>
                <option value="openrouter">OpenRouter API</option>
                <option value="anthropic">Anthropic Claude</option>
                <option value="openai_compatible">OpenAI-Compatible (Ollama/vLLM)</option>
              </select>
            </Field>
            <Field label="Model">
              <input className="input" value={llmModel} onChange={(e) => setLlmModel(e.target.value)} placeholder={providerDefaults[llmProvider] || "model-name"} list={`modal-models-${llmProvider}`} />
              <datalist id={`modal-models-${llmProvider}`}>
                {(providerPresets as any[]).find((p: any) => p.id === llmProvider)?.models?.map((m: string) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            </Field>
            <Field label="Base URL (optional)">
              <input className="input font-mono text-xs" value={llmUrl} onChange={(e) => setLlmUrl(e.target.value)} placeholder="https://api.openai.com/v1" />
            </Field>
            <Field label="API Key">
              <input className="input font-mono" type="password" value={llmKey} onChange={(e) => setLlmKey(e.target.value)} placeholder="sk-..." />
            </Field>
          </div>
          <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground pt-2">Embedding Configuration</h3>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Provider">
              <select className="input" value={embedProvider} onChange={(e) => setEmbedProvider(e.target.value)}>
                <option value="hash">Local Deterministic Hash (384d)</option>
                <option value="bge">BGE Small (384d)</option>
                <option value="bge_m3">BGE-M3 (1024d)</option>
                <option value="openai">OpenAI (1536d)</option>
                <option value="gemini">Gemini (768d)</option>
                <option value="openai_compatible">OpenAI-Compatible Custom</option>
              </select>
            </Field>
            <Field label="Model">
              <input className="input" value={embedModel} onChange={(e) => setEmbedModel(e.target.value)} placeholder="BAAI/bge-small-en-v1.5" />
            </Field>
            <Field label="Dimensions">
              <input className="input" type="number" value={embedDims} onChange={(e) => setEmbedDims(Number(e.target.value))} />
            </Field>
            <Field label="Base URL (optional)">
              <input className="input font-mono text-xs" value={embedUrl} onChange={(e) => setEmbedUrl(e.target.value)} placeholder="https://api.openai.com/v1" />
            </Field>
            <Field label="API Key (optional)">
              <input className="input font-mono" type="password" value={embedKey} onChange={(e) => setEmbedKey(e.target.value)} placeholder="sk-..." />
            </Field>
          </div>
        </div>
        <div className="mt-6 flex justify-end gap-3">
          <button onClick={onClose} className="rounded-md border border-border bg-panel px-4 py-2 text-sm font-medium hover:bg-elevated">Cancel</button>
          <button onClick={() => create.mutate()} disabled={create.isPending || !tid} className="inline-flex items-center gap-2 rounded-md bg-[image:var(--gradient-primary)] px-5 py-2 text-sm font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50">
            {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Create Client
          </button>
        </div>
      </div>
    </div>
  );
}

const providerDefaults: Record<string, string> = {
  gemini: "gemini-2.5-flash-lite",
  mistral: "mistral-small-latest",
  openai: "gpt-4o-mini",
  nvidia: "meta/llama-3.1-8b-instruct",
  openrouter: "openai/gpt-4o-mini",
  anthropic: "claude-3-5-haiku-latest",
  openai_compatible: "gpt-4o-mini",
};

const accents = {
  amber: { bg: "var(--accent-amber)", fg: "#1a1408", ring: "rgba(245,179,1,0.35)" },
  rose:  { bg: "var(--accent-rose)",  fg: "#fff",   ring: "rgba(229,72,77,0.35)" },
  sky:   { bg: "var(--accent-sky)",   fg: "#04121e",ring: "rgba(14,165,233,0.35)" },
  emerald:{bg: "var(--accent-emerald)",fg: "#fff",  ring: "rgba(22,163,74,0.35)" },
  violet:{ bg: "var(--accent-violet)", fg: "#fff",  ring: "rgba(124,58,237,0.35)" },
} as const;
type AccentKey = keyof typeof accents;

function Stat({
  label, value, sub, icon: Icon, accent,
}: {
  label: string; value: string; sub?: string;
  icon: React.ComponentType<{ className?: string }>;
  accent?: AccentKey;
}) {
  if (accent) {
    const a = accents[accent];
    return (
      <div
        className="relative overflow-hidden rounded-xl p-5 text-[color:var(--fg)]"
        style={{ background: a.bg, color: a.fg, boxShadow: `0 10px 30px -12px ${a.ring}` } as React.CSSProperties}
      >
        <div className="flex items-start justify-between">
          <div className="text-[11px] font-semibold uppercase tracking-wider opacity-80">{label}</div>
          <div className="grid h-9 w-9 place-items-center rounded-full bg-black/15">
            <Icon className="h-4 w-4" />
          </div>
        </div>
        <div className="mt-3 text-3xl font-extrabold tracking-tight">{value}</div>
        {sub && <div className="mt-1 text-xs opacity-85">{sub}</div>}
      </div>
    );
  }
  return (
    <div className="panel p-5">
      <div className="flex items-start justify-between">
        <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{label}</div>
        <div className="grid h-8 w-8 place-items-center rounded-md bg-elevated text-primary">
          <Icon className="h-4 w-4" />
        </div>
      </div>
      <div className="mt-3 text-2xl font-bold tracking-tight">{value}</div>
      {sub && <div className="mt-1 text-xs text-muted-foreground">{sub}</div>}
    </div>
  );
}


function ConfigTab({ tenant }: { tenant: Tenant }) {
  const queryClient = useQueryClient();
  const { data: config, isLoading } = useQuery({
    queryKey: ["config", tenant.id],
    queryFn: async () => {
      const res = await apiFetch(`/tenants/${tenant.id}/config`);
      return res.json();
    },
  });

  const { data: providerPresets = [] } = useQuery({
    queryKey: ["provider-presets"],
    queryFn: async () => {
      const res = await apiFetch("/admin/providers");
      return res.json();
    },
  });

  const [form, setForm] = useState<any>({});
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");

  useEffect(() => {
    if (config) setForm(config);
  }, [config]);

  function upd(field: string, val: any) {
    setForm((prev: any) => ({ ...prev, [field]: val }));
  }

  async function handleSave() {
    setSaving(true);
    setSaveMsg("");
    try {
      const res = await apiFetch(`/tenants/${tenant.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: form.name,
          status: form.status,
          subscription_tier: form.subscriptionTier,
          monthly_fee: form.monthlyFee,
          llm_provider: form.llmProvider,
          llm_model: form.llmModel,
          llm_api_key: form.llmApiKey === "***" ? "***" : form.llmApiKey,
          llm_base_url: form.llmBaseUrl || null,
          reranker_type: form.rerankerType,
          chunking_semantic: form.chunkingSemantic,
          chunking_semantic_threshold: form.chunkingSemanticThreshold,
          embedding_provider: form.embeddingProvider,
          embedding_model: form.embeddingModel,
          embedding_dimensions: Number(form.embeddingDimensions),
          embedding_base_url: form.embeddingBaseUrl || null,
          embedding_api_key: form.embeddingApiKey === "***" ? "***" : (form.embeddingApiKey || null),
          retrieval_top_k: Number(form.retrievalTopK),
          retrieval_rerank_top_k: Number(form.retrievalRerankTopK),
          retrieval_final_context_k: Number(form.retrievalFinalContextK),
          retrieval_dense_weight: Number(form.retrievalDenseWeight),
          retrieval_sparse_weight: Number(form.retrievalSparseWeight),
          chunking_max_tokens: Number(form.chunkingMaxTokens),
          chunking_overlap_tokens: Number(form.chunkingOverlapTokens),
          session_memory_limit: Number(form.sessionMemoryLimit),
          chat_retention_days: Number(form.chatRetentionDays),
          system_prompt: form.systemPrompt || null,
        }),
      });
      if (!res.ok) throw new Error("Save failed");
      queryClient.invalidateQueries({ queryKey: ["config", tenant.id] });
      queryClient.invalidateQueries({ queryKey: ["tenants"] });
      setSaveMsg("Saved successfully");
      setTimeout(() => setSaveMsg(""), 3000);
    } catch (e: any) {
      setSaveMsg("Error: " + e.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!confirm("Delete this client and all associated data? This cannot be undone.")) return;
    try {
      await apiFetch(`/tenants/${tenant.id}`, { method: "DELETE" });
      queryClient.invalidateQueries({ queryKey: ["tenants"] });
    } catch (e: any) {
      setSaveMsg("Delete error: " + e.message);
    }
  }

  if (isLoading) return <div className="panel p-6 text-sm text-muted-foreground">Loading config...</div>;
  if (!form) return null;

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-4">
        <Stat accent="amber"  label="Monthly Fee"  value={`$${form.monthlyFee || tenant.fee}.00`} sub={`Tier: ${form.subscriptionTier || tenant.tier}`} icon={ShieldCheck} />
        <Stat accent="rose"   label="Embedding"    value={form.embeddingModel || "bge-small-en"} sub={`Provider: ${form.embeddingProvider || "Local"}`} icon={Database} />
        <Stat accent="sky"    label="LLM Endpoint" value={form.llmModel || "gemini-2.5-flash-lite"} sub={`Provider: ${form.llmProvider || "OpenAI"}`} icon={Sparkles} />
        <Stat accent="emerald"label="Vector Store" value="Qdrant" sub="Dense + sparse hybrid" icon={Gauge} />
      </div>

      <div className="panel p-6">
        <h3 className="mb-4 text-sm font-semibold uppercase tracking-wider text-muted-foreground">Basic Info</h3>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Client Name">
            <input className="input" value={form.name || ""} onChange={(e) => upd("name", e.target.value)} />
          </Field>
          <Field label="Status">
            <select className="input" value={form.status || "active"} onChange={(e) => upd("status", e.target.value)}>
              <option value="active">Active</option>
              <option value="suspended">Suspended</option>
            </select>
          </Field>
          <Field label="Subscription Tier">
            <select className="input" value={form.subscriptionTier || "basic"} onChange={(e) => upd("subscriptionTier", e.target.value)}>
              <option value="basic">Basic ($199/mo)</option>
              <option value="premium">Premium ($299/mo)</option>
              <option value="enterprise">Enterprise ($599/mo)</option>
            </select>
          </Field>
          <Field label="Monthly Fee ($)">
            <input className="input" type="number" value={form.monthlyFee ?? 299} onChange={(e) => upd("monthlyFee", Number(e.target.value))} />
          </Field>
        </div>
      </div>

      <div className="panel p-6">
        <h3 className="mb-4 text-sm font-semibold uppercase tracking-wider text-muted-foreground">LLM Provider</h3>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Provider">
            <select className="input" value={form.llmProvider || "gemini"} onChange={(e) => {
              const p = e.target.value;
              upd("llmProvider", p);
              const def = providerDefaults[p];
              if (def) upd("llmModel", def);
            }}>
              <option value="gemini">Google Gemini Cloud</option>
              <option value="mistral">Mistral Cloud</option>
              <option value="openai">OpenAI</option>
              <option value="nvidia">NVIDIA NIM Cloud</option>
              <option value="openrouter">OpenRouter API</option>
              <option value="anthropic">Anthropic Claude</option>
              <option value="openai_compatible">OpenAI-Compatible (Ollama/vLLM)</option>
            </select>
          </Field>
          <Field label="Model Name">
            <input className="input" value={form.llmModel || ""} onChange={(e) => upd("llmModel", e.target.value)} placeholder={providerDefaults[form.llmProvider] || "model-name"} list={`models-${form.llmProvider}`} />
            <datalist id={`models-${form.llmProvider}`}>
              {providerPresets.find((p: any) => p.id === form.llmProvider)?.models?.map((m: string) => (
                <option key={m} value={m} />
              ))}
            </datalist>
          </Field>
          <Field label="API Key">
            <input className="input font-mono" type="password" value={form.llmApiKey || ""} onChange={(e) => upd("llmApiKey", e.target.value)} placeholder="*** to keep current" />
          </Field>
          <Field label="Base URL (optional)">
            <input className="input font-mono text-xs" value={form.llmBaseUrl || ""} onChange={(e) => upd("llmBaseUrl", e.target.value)} placeholder="https://api.openai.com/v1" />
          </Field>
          <Field label="Reranker Type">
            <select className="input" value={form.rerankerType || "local"} onChange={(e) => upd("rerankerType", e.target.value)}>
              <option value="local">Local Word-Overlap Reranker</option>
              <option value="bge_cross_encoder">BGE Cross-Encoder</option>
            </select>
          </Field>
          <Field label="Semantic Chunking">
            <select className="input" value={form.chunkingSemantic ? "true" : "false"} onChange={(e) => upd("chunkingSemantic", e.target.value === "true")}>
              <option value="false">Disabled (heading-based)</option>
              <option value="true">Enabled (embedding similarity merge)</option>
            </select>
          </Field>
          <Field label="Semantic Threshold">
            <input className="input" type="number" step="0.05" min="0" max="1" value={form.chunkingSemanticThreshold ?? 0.75} onChange={(e) => upd("chunkingSemanticThreshold", Number(e.target.value))} />
          </Field>
        </div>
      </div>

      <div className="panel p-6">
        <h3 className="mb-4 text-sm font-semibold uppercase tracking-wider text-muted-foreground" style={{ color: "var(--accent-teal)" }}>Core RAG Settings</h3>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Embedding Provider">
            <select className="input" value={form.embeddingProvider || "hash"} onChange={(e) => upd("embeddingProvider", e.target.value)}>
              <option value="hash">Local Deterministic Hash (384d)</option>
              <option value="bge">BGE Small (384d)</option>
              <option value="bge_m3">BGE-M3 (1024d)</option>
              <option value="openai">OpenAI (1536d)</option>
              <option value="gemini">Gemini (768d)</option>
              <option value="openai_compatible">OpenAI-Compatible Custom</option>
            </select>
          </Field>
          <Field label="Embedding Model">
            <input className="input" value={form.embeddingModel || "BAAI/bge-small-en-v1.5"} onChange={(e) => upd("embeddingModel", e.target.value)} />
          </Field>
          <Field label="Embedding Dimensions">
            <input className="input" type="number" value={form.embeddingDimensions ?? 384} onChange={(e) => upd("embeddingDimensions", Number(e.target.value))} />
          </Field>
          <Field label="Embedding Base URL">
            <input className="input font-mono text-xs" value={form.embeddingBaseUrl || ""} onChange={(e) => upd("embeddingBaseUrl", e.target.value)} placeholder="https://api.nvidia.com/v1" />
          </Field>
          <Field label="Embedding API Key">
            <input className="input font-mono" type="password" value={form.embeddingApiKey || ""} onChange={(e) => upd("embeddingApiKey", e.target.value)} placeholder="*** to keep current" />
          </Field>
          <Field label="System Prompt">
            <textarea className="input min-h-[60px] resize-y font-mono text-xs" value={form.systemPrompt || ""} onChange={(e) => upd("systemPrompt", e.target.value)} placeholder="Optional custom system prompt" />
          </Field>
          <Field label="Search Top-K Chunks">
            <input className="input" type="number" value={form.retrievalTopK ?? 20} onChange={(e) => upd("retrievalTopK", Number(e.target.value))} />
          </Field>
          <Field label="Rerank Top-K Candidates">
            <input className="input" type="number" value={form.retrievalRerankTopK ?? 8} onChange={(e) => upd("retrievalRerankTopK", Number(e.target.value))} />
          </Field>
          <Field label="Final Assembly Context K">
            <input className="input" type="number" value={form.retrievalFinalContextK ?? 5} onChange={(e) => upd("retrievalFinalContextK", Number(e.target.value))} />
          </Field>
          <Field label="Dense Retrieve Weight">
            <input className="input" type="number" step="0.05" min="0" max="1" value={form.retrievalDenseWeight ?? 0.55} onChange={(e) => upd("retrievalDenseWeight", Number(e.target.value))} />
          </Field>
          <Field label="Sparse Retrieve Weight">
            <input className="input" type="number" step="0.05" min="0" max="1" value={form.retrievalSparseWeight ?? 0.45} onChange={(e) => upd("retrievalSparseWeight", Number(e.target.value))} />
          </Field>
          <Field label="Chunk Max Tokens">
            <input className="input" type="number" value={form.chunkingMaxTokens ?? 320} onChange={(e) => upd("chunkingMaxTokens", Number(e.target.value))} />
          </Field>
          <Field label="Chunk Overlap Tokens">
            <input className="input" type="number" value={form.chunkingOverlapTokens ?? 48} onChange={(e) => upd("chunkingOverlapTokens", Number(e.target.value))} />
          </Field>
        </div>
      </div>

      <div className="panel p-6">
        <h3 className="mb-4 text-sm font-semibold uppercase tracking-wider text-muted-foreground" style={{ color: "var(--accent-teal)" }}>Memory & Retention Policy</h3>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Active Memory Window">
            <select className="input" value={form.sessionMemoryLimit ?? 8} onChange={(e) => upd("sessionMemoryLimit", Number(e.target.value))}>
              <option value={4}>4 Turns (~150ms overhead)</option>
              <option value={8}>8 Turns (~300ms overhead — Recommended)</option>
              <option value={16}>16 Turns (~600ms overhead)</option>
              <option value={32}>32 Turns (~1.2s overhead)</option>
            </select>
          </Field>
          <Field label="Chat Retention Policy">
            <select className="input" value={form.chatRetentionDays ?? 30} onChange={(e) => upd("chatRetentionDays", Number(e.target.value))}>
              <option value={7}>7 Days</option>
              <option value={30}>30 Days (Default)</option>
              <option value={90}>90 Days</option>
              <option value={365}>1 Year</option>
              <option value={0}>Keep Forever</option>
            </select>
          </Field>
        </div>
      </div>

      <div className="flex items-center justify-between gap-4">
        <button onClick={handleDelete} className="inline-flex items-center gap-2 rounded-md border border-destructive/30 px-4 py-2 text-sm font-medium text-destructive hover:bg-destructive/10">
          <Trash2 className="h-4 w-4" /> Delete Client
        </button>
        <div className="flex items-center gap-3">
          {saveMsg && <span className={`text-xs ${saveMsg.includes("Error") ? "text-destructive" : "text-success"}`}>{saveMsg}</span>}
          <button onClick={handleSave} disabled={saving} className="inline-flex items-center gap-2 rounded-md bg-[image:var(--gradient-primary)] px-6 py-2 text-sm font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50">
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Save Configuration
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-medium text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

function DocumentsTab({ tenantId }: { tenantId?: string }) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [source, setSource] = useState<"files" | "web" | "cloud" | "crawl">("files");
  const [uploading, setUploading] = useState(false);
  const [scrapeUrl, setScrapeUrl] = useState("");
  const [scrapeDepth, setScrapeDepth] = useState(3);
  const [scrapePages, setScrapePages] = useState(100);
  const [scraping, setScraping] = useState(false);
  const [scrapeResult, setScrapeResult] = useState<any>(null);
  const [applyOcrUpload, setApplyOcrUpload] = useState(false);
  const [scrapeMode, setScrapeMode] = useState<string>("smart");
  const [scrapeFormat, setScrapeFormat] = useState<string>("json");
  const [scrapeContentType, setScrapeContentType] = useState<string>("all");
  const [scrapeTimeout, setScrapeTimeout] = useState(30);
  const [scrapeWorkers, setScrapeWorkers] = useState(1);
  const [scrapeRespectRobots, setScrapeRespectRobots] = useState(true);
  const [scrapeIncludePages, setScrapeIncludePages] = useState(true);
  const [scrapeIncludeMedia, setScrapeIncludeMedia] = useState(true);
  const [scrapeFbCUser, setScrapeFbCUser] = useState("");
  const [scrapeFbXs, setScrapeFbXs] = useState("");
  const [scrapeFbMaxPosts, setScrapeFbMaxPosts] = useState(20);
  const [scrapeFbScrollRounds, setScrapeFbScrollRounds] = useState(5);
  const [scrapeFbDateFrom, setScrapeFbDateFrom] = useState("");
  const [scrapeFbDateTo, setScrapeFbDateTo] = useState("");
  const [scrapeProfilePlatform, setScrapeProfilePlatform] = useState("");
  const [scrapeProfileUsername, setScrapeProfileUsername] = useState("");
  const [scrapeDeepCrawl, setScrapeDeepCrawl] = useState(false);
  const [scrapeImages, setScrapeImages] = useState(false);
  const [scrapePdfs, setScrapePdfs] = useState(false);
  const [scrapePlaywright, setScrapePlaywright] = useState(false);
  const [scrapeJobId, setScrapeJobId] = useState<string | null>(null);
  const [scrapeJobStatus, setScrapeJobStatus] = useState<any>(null);
  const [ingesting, setIngesting] = useState(false);
  const [ingestProgress, setIngestProgress] = useState<{ status: string; progress: number; logs: string[]; summary?: any } | null>(null);
  const [viewDoc, setViewDoc] = useState<string | null>(null);
  const [chunks, setChunks] = useState<any[]>([]);
  const [chunksLoading, setChunksLoading] = useState(false);
  const [cloudProvider, setCloudProvider] = useState<string | null>(null);
  const [selectedCrawlSite, setSelectedCrawlSite] = useState<string | null>(null);

  const { data: crawlSites } = useQuery({
    queryKey: ["crawl-sites"],
    queryFn: async () => {
      try {
        const res = await apiFetch("/crawl-output");
        return res.json();
      } catch { return { sites: [] }; }
    },
    enabled: source === "crawl",
  });

  const { data: selectedCrawlSiteData, refetch: refetchCrawlSiteData } = useQuery({
    queryKey: ["crawl-site-data", selectedCrawlSite],
    queryFn: async () => {
      if (!selectedCrawlSite) return null;
      try {
        const res = await apiFetch(`/crawl-output/${selectedCrawlSite}`);
        return res.json();
      } catch { return null; }
    },
    enabled: !!selectedCrawlSite && source === "crawl",
  });

  const { data: scraperHealth } = useQuery({
    queryKey: ["scraper-health"],
    queryFn: async () => {
      try {
        const res = await apiFetch("/scrape/health");
        if (!res.ok) return { alive: false };
        const data = await res.json();
        return { alive: data.service !== 'unavailable', service: data.service, version: data.version };
      } catch { return { alive: false }; }
    },
    refetchInterval: 15000,
  });

  const [scraperLogsExpanded, setScraperLogsExpanded] = useState(true);
  const logsContainerRef = useRef<HTMLDivElement>(null);
  const [scraperLogsAutoScroll, setScraperLogsAutoScroll] = useState(true);

  const { data: scraperLogs = [] } = useQuery({
    queryKey: ["scraper-logs"],
    queryFn: async () => {
      try {
        const res = await apiFetch("/scrape/logs?lines=50");
        if (!res.ok) return [];
        const body = await res.json();
        return body.logs || [];
      } catch { return []; }
    },
    refetchInterval: 3000,
    enabled: scraperHealth?.alive === true,
  });

  useEffect(() => {
    if (scraperLogsAutoScroll && logsContainerRef.current) {
      logsContainerRef.current.scrollTop = logsContainerRef.current.scrollHeight;
    }
  }, [scraperLogs, scraperLogsAutoScroll]);

  const { data: docs = [], refetch: refetchDocs } = useQuery({
    queryKey: ["documents", tenantId],
    queryFn: async () => {
      if (!tenantId) return [];
      const res = await apiFetch(`/tenants/${tenantId}/documents`);
      return res.json();
    },
    enabled: !!tenantId
  });

  async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files;
    if (!files || !files.length || !tenantId) return;
    setUploading(true);
    try {
      const form = new FormData();
      for (let i = 0; i < files.length; i++) form.append("files", files[i]);
      await apiFetch(`/tenants/${tenantId}/documents?apply_ocr=${applyOcrUpload}`, { method: "POST", body: form });
      refetchDocs();
    } catch (e: any) {
      alert("Upload failed: " + e.message);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function handleScrape() {
    if (!scrapeUrl || !tenantId) return;
    setScraping(true);
    setScrapeResult(null);
    setScrapeJobId(null);
    setScrapeJobStatus(null);
    try {
      const body: any = {
        url: scrapeUrl,
        scrape_type: scrapeMode,
        format: scrapeFormat,
        max_depth: scrapeDepth,
        max_pages: scrapePages,
        timeout: scrapeTimeout,
        include_pages: scrapeIncludePages,
        include_media: scrapeIncludeMedia,
        fb_c_user: scrapeFbCUser,
        fb_xs: scrapeFbXs,
        fb_max_posts: scrapeFbMaxPosts,
        fb_scroll_rounds: scrapeFbScrollRounds,
        fb_date_from: scrapeFbDateFrom,
        fb_date_to: scrapeFbDateTo,
        profile_platform: scrapeProfilePlatform,
        profile_username: scrapeProfileUsername,
        workers: scrapeWorkers,
        respect_robots: scrapeRespectRobots,
        deepcrawl: scrapeDeepCrawl,
        playwright: scrapePlaywright,
      };
      if (scrapeContentType !== "all") body.content_type = scrapeContentType;
      if (scrapeImages) body.content_type = 'images';
      if (scrapePdfs) body.content_type = 'pdfs';
      const res = await apiFetch(`/tenants/${tenantId}/scrape/enhanced`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const result = await res.json();
      setScrapeResult(result);
      if ((scrapeMode === "recursive" || scrapeMode === "facebook") && result?.data?.job_id) {
        setScrapeJobId(result.data.job_id);
      }
      refetchDocs();
    } catch (e: any) {
      setScrapeResult({ status: "failed", error: e.message });
    } finally {
      setScraping(false);
    }
  }

  // Poll recursive crawl job status
  useEffect(() => {
    if (!scrapeJobId || !tenantId) return;
    const interval = setInterval(async () => {
      try {
        const res = await apiFetch(`/scrape/recursive/${scrapeJobId}/status`);
        const status = await res.json();
        setScrapeJobStatus(status);
        if (status?.data?.status === "completed" || status?.data?.status === "error") {
          clearInterval(interval);
        }
      } catch {}
    }, 3000);
    return () => clearInterval(interval);
  }, [scrapeJobId, tenantId]);

  async function handleIngest(applyOcr = false) {
    if (!tenantId) return;
    setIngesting(true);
    setIngestProgress({ status: "starting", progress: 0, logs: [] });
    try {
      await apiFetch(`/tenants/${tenantId}/ingest?apply_ocr=${applyOcr}`, { method: "POST" });
      const poll = setInterval(async () => {
        try {
          const res = await apiFetch(`/tenants/${tenantId}/ingest/status`);
          const data = await res.json();
          setIngestProgress(data);
          if (data.status === "completed" || data.status === "error" || data.status === "idle") {
            clearInterval(poll);
            setIngesting(false);
            refetchDocs();
            queryClient.invalidateQueries({ queryKey: ["tenants"] });
          }
        } catch { clearInterval(poll); setIngesting(false); }
      }, 1500);
    } catch (e: any) {
      setIngesting(false);
      alert("Ingest failed: " + e.message);
    }
  }

  async function handleDeleteDoc(filename: string) {
    if (!tenantId) return;
    if (!confirm(`Delete ${filename}? This will remove all chunks and vectors.`)) return;
    try {
      await apiFetch(`/tenants/${tenantId}/documents/${encodeURIComponent(filename)}`, { method: "DELETE" });
      refetchDocs();
      queryClient.invalidateQueries({ queryKey: ["tenants"] });
    } catch (e: any) {
      alert("Delete failed: " + e.message);
    }
  }

  async function handleViewChunks(filename: string) {
    if (!tenantId) return;
    setViewDoc(filename);
    setChunksLoading(true);
    setChunks([]);
    try {
      const res = await apiFetch(`/tenants/${tenantId}/documents/${encodeURIComponent(filename)}/chunks`);
      const data = await res.json();
      setChunks(Array.isArray(data) ? data : []);
    } catch (e: any) {
      alert("Failed to load chunks: " + e.message);
    } finally {
      setChunksLoading(false);
    }
  }

  function formatSize(bytes: number) {
    if (!bytes) return "—";
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  async function handleImportCrawlOutput(site: string) {
    if (!tenantId) return;
    try {
      const res = await apiFetch(`/crawl-output/${site}/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tenantId }),
      });
      const result = await res.json();
      if (result.success) {
        alert(`Imported ${result.imported_count} files from ${site}`);
        refetchDocs();
      } else {
        alert("Import failed: " + (result.error || "Unknown error"));
      }
    } catch (e: any) {
      alert("Import failed: " + e.message);
    }
  }

  function ScrapeHistory({ tenantId }: { tenantId?: string }) {
    const { data: logs = [] } = useQuery({
      queryKey: ["scrape-history", tenantId],
      queryFn: async () => {
        const res = await apiFetch(`/system/logs?tenant_id=${tenantId || ""}&operation=scrape&limit=20`);
        const body = await res.json();
        return (body.logs || body || []).filter((l: any) => l.operation === "scrape" || l.operation === "scrape_ingest");
      },
      enabled: !!tenantId,
      refetchInterval: 10000,
    });
    if (!logs.length) return null;
    return (
      <div className="mt-4">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">Scrape History</h4>
        <div className="max-h-40 overflow-y-auto rounded border border-border divide-y divide-border">
          {logs.map((l: any, i: number) => {
            const details = l.details_json ? (typeof l.details_json === "string" ? JSON.parse(l.details_json) : l.details_json) : {};
            const url = details?.url || l.message?.match(/https?:\/\/[^\s]+/)?.[0] || "";
            return (
              <div key={l.id || i} className="flex items-center gap-3 px-3 py-2 text-[10px] hover:bg-elevated/40">
                <span className={`shrink-0 w-1.5 h-1.5 rounded-full ${l.level === "error" ? "bg-destructive" : "text-success"}`} />
                <span className="font-mono text-muted-foreground shrink-0">{new Date(l.created_at).toLocaleString()}</span>
                <span className="text-foreground/80 truncate">{url || l.message}</span>
                <span className={`ml-auto shrink-0 ${details?.success !== false ? "text-success" : "text-destructive"}`}>
                  {details?.success !== false ? "✅" : "❌"}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-3 md:grid-cols-4">
        <SourceCard active={source === "files"} onClick={() => setSource("files")} accent="amber" icon={Upload} title="File upload" desc="PDF, DOCX, MD, TXT, CSV, HTML" />
        <SourceCard active={source === "web"} onClick={() => setSource("web")} accent="sky" icon={Globe} title="Web scraping" desc="Crawl a URL. Auto-clean, chunk & index." />
        <SourceCard active={source === "cloud"} onClick={() => setSource("cloud")} accent="emerald" icon={Cloud} title="Cloud sync" desc="Google Drive, Notion, Confluence, S3" />
        <SourceCard active={source === "crawl"} onClick={() => setSource("crawl")} accent="violet" icon={Database} title="Crawl output" desc="Browse scraped sites and import content" />
      </div>

      {source === "files" && (
        <div className="panel p-6">
          <div className="rounded-xl border-2 border-dashed border-border bg-elevated/40 p-8 text-center">
            <Upload className="mx-auto h-8 w-8 text-primary" />
            <p className="mt-3 text-sm font-medium">Drop files here or click to browse</p>
            <p className="mt-1 text-xs text-muted-foreground">Supported: PDF, DOCX, PPTX, MD, TXT, HTML, CSV, JSON</p>
            <input ref={fileInputRef} type="file" multiple className="hidden" onChange={handleFileUpload} />
            <button disabled={uploading} onClick={() => fileInputRef.current?.click()} className="mt-4 inline-flex items-center gap-1.5 rounded-md bg-[image:var(--gradient-primary)] px-4 py-2 text-xs font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50">
              {uploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
              {uploading ? "Uploading..." : "Select files"}
            </button>
            <label className="mt-3 inline-flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={applyOcrUpload} onChange={(e) => setApplyOcrUpload(e.target.checked)} className="accent-primary" />
              <span className="text-xs text-muted-foreground">Apply OCR</span>
            </label>
          </div>
          <div className="mt-4 flex items-center gap-3">
            <button onClick={() => handleIngest(false)} disabled={ingesting} className="inline-flex items-center gap-1.5 rounded-md border border-border bg-panel px-4 py-2 text-xs font-medium hover:bg-elevated disabled:opacity-50">
              {ingesting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />}
              Ingest all pending
            </button>
            <button onClick={() => handleIngest(true)} disabled={ingesting} className="inline-flex items-center gap-1.5 rounded-md border border-border bg-panel px-4 py-2 text-xs font-medium hover:bg-elevated disabled:opacity-50">
              <FileText className="h-3.5 w-3.5" /> Ingest with OCR
            </button>
          </div>
          {ingestProgress && ingestProgress.status !== "idle" && (
            <div className="mt-4 space-y-4">
              <div className="panel p-4">
                <div className="flex items-center justify-between text-xs mb-2">
                  <span className="font-semibold capitalize">{ingestProgress.status}</span>
                  <span>{ingestProgress.progress}%</span>
                </div>
                <div className="h-2 rounded-full bg-elevated overflow-hidden">
                  <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${ingestProgress.progress}%` }} />
                </div>
                <div className="mt-3 pipeline-timeline">
                  {[
                    { step: 1, label: "Scan & sync directory" },
                    { step: 2, label: "Extract text & metadata" },
                    { step: 3, label: "Chunk documents" },
                    { step: 4, label: "Generate embeddings" },
                    { step: 5, label: "Store in vector DB" },
                  ].map(({ step, label }) => {
                    const logs = ingestProgress.logs || [];
                    const active = logs.some((l: string) => l.includes(`[Step ${step}]`) || (step === 1 && l.includes("Syncing")) || (step === 2 && l.includes("Extract")) || (step === 3 && l.includes("Segment")) || (step === 4 && l.includes("Comput")) || (step === 5 && l.includes("Upsert")));
                    const done = ingestProgress.status === "completed";
                    return (
                      <div key={step} className={`timeline-step ${done ? "completed" : active ? "active" : ""}`}>
                        <div className="step-node">{step}</div>
                        <div className="step-label">{label}</div>
                      </div>
                    );
                  })}
                </div>
              </div>
              {ingestProgress.logs && ingestProgress.logs.length > 0 && (
                <div className="mt-2 max-h-32 overflow-y-auto rounded bg-[#0a1020] p-2 font-mono text-[10px] leading-relaxed text-foreground/70">
                  {ingestProgress.logs.map((l: string, i: number) => (
                    <div key={i} className={`${l.includes("[Error]") || l.includes("[Critical") ? "text-destructive" : l.includes("finished") || l.includes("Successfully") ? "text-success" : l.includes("[System]") ? "text-[color:var(--accent-teal)]" : l.includes("skipping") || l.includes("already") ? "text-muted-foreground" : ""}`}>{l}</div>
                  ))}
                </div>
              )}
              {ingestProgress.summary && (
                <div className="text-[10px] text-muted-foreground">
                  Docs: {ingestProgress.summary.documents} · Chunks: {ingestProgress.summary.chunks} · Skipped: {ingestProgress.summary.skipped}
                  {ingestProgress.summary.errors?.length > 0 && ` · Errors: ${ingestProgress.summary.errors.length}`}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {source === "web" && (
        <div className="panel p-6">
          {/* Scraper service health indicator */}
          <div className="flex items-center gap-2 mb-4">
            <span className={`w-2 h-2 rounded-full ${scraperHealth?.alive ? "bg-success" : "bg-destructive"}`} />
            <span className="text-xs text-muted-foreground">
              Scraper Service {scraperHealth?.alive ? `${scraperHealth.service} v${scraperHealth.version}` : "Offline"}
            </span>
          </div>

          <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Scrape a web page</h3>

          {/* Mode selector */}
          <div className="mt-4 flex flex-wrap gap-2">
            {[
              { id: "single", label: "Single" },
              { id: "smart", label: "Smart" },
              { id: "recursive", label: "Recursive" },
              { id: "wordpress", label: "WordPress" },
              { id: "facebook", label: "Facebook" },
              { id: "profile", label: "Profile" },
            ].map((m) => (
              <button key={m.id} onClick={() => setScrapeMode(m.id)}
                className={`rounded px-3 py-1.5 text-xs font-medium border ${scrapeMode === m.id ? "bg-primary text-primary-foreground border-primary" : "bg-panel text-muted-foreground border-border hover:bg-elevated"}`}>
                {m.label}
              </button>
            ))}
          </div>

          <div className="mt-4 grid gap-4 md:grid-cols-[1fr_140px_auto]">
            <Field label="URL">
              <input className="input font-mono text-xs" value={scrapeUrl} onChange={(e) => setScrapeUrl(e.target.value)} placeholder="https://example.com/page" />
            </Field>
            {(scrapeMode === "recursive" || scrapeMode === "single" || scrapeMode === "smart") && (
              <>
                <Field label="Max depth">
                  <input className="input" type="number" value={scrapeDepth} onChange={(e) => setScrapeDepth(Number(e.target.value))} />
                </Field>
                <Field label="Max pages">
                  <input className="input" type="number" value={scrapePages} onChange={(e) => setScrapePages(Number(e.target.value))} />
                </Field>
              </>
            )}
            <div className="flex items-end">
              <button disabled={scraping || !scrapeUrl} onClick={handleScrape} className="inline-flex h-[38px] items-center gap-1.5 rounded-md bg-[image:var(--gradient-primary)] px-4 text-xs font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50">
                {scraping ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />}
                {scraping ? "Scraping..." : "Start scrape"}
              </button>
            </div>
          </div>

          {/* Contextual options based on mode */}
          <div className="mt-4 grid gap-4 md:grid-cols-3">
            {scrapeMode === "smart" && (
              <>
                <Field label="Timeout (s)">
                  <input className="input" type="number" value={scrapeTimeout} onChange={(e) => setScrapeTimeout(Number(e.target.value))} />
                </Field>
                <Field label="Content type">
                  <select className="input text-xs" value={scrapeContentType} onChange={(e) => setScrapeContentType(e.target.value)}>
                    <option value="all">All</option>
                    <option value="text">Text only</option>
                    <option value="images">Images</option>
                    <option value="pdfs">PDFs</option>
                  </select>
                </Field>
                <Field label="Format">
                  <select className="input text-xs" value={scrapeFormat} onChange={(e) => setScrapeFormat(e.target.value)}>
                    <option value="json">JSON</option>
                    <option value="markdown">Markdown</option>
                  </select>
                </Field>
              </>
            )}
            {scrapeMode === "single" && (
              <Field label="Format">
                <select className="input text-xs" value={scrapeFormat} onChange={(e) => setScrapeFormat(e.target.value)}>
                  <option value="json">JSON</option>
                  <option value="markdown">Markdown</option>
                </select>
              </Field>
            )}
            {scrapeMode === "recursive" && (
              <>
                <Field label="Workers">
                  <input className="input" type="number" value={scrapeWorkers} onChange={(e) => setScrapeWorkers(Number(e.target.value))} min={1} max={10} />
                </Field>
                <label className="flex items-center gap-2 mt-6 cursor-pointer">
                  <input type="checkbox" checked={scrapeRespectRobots} onChange={(e) => setScrapeRespectRobots(e.target.checked)} className="accent-primary" />
                  <span className="text-xs text-muted-foreground">Respect robots.txt</span>
                </label>
              </>
            )}
            {scrapeMode === "wordpress" && (
              <>
                <Field label="Max pages">
                  <input className="input" type="number" value={scrapePages} onChange={(e) => setScrapePages(Number(e.target.value))} />
                </Field>
                <label className="flex items-center gap-2 mt-6 cursor-pointer">
                  <input type="checkbox" checked={scrapeIncludePages} onChange={(e) => setScrapeIncludePages(e.target.checked)} className="accent-primary" />
                  <span className="text-xs text-muted-foreground">Include pages</span>
                </label>
                <label className="flex items-center gap-2 mt-6 cursor-pointer">
                  <input type="checkbox" checked={scrapeIncludeMedia} onChange={(e) => setScrapeIncludeMedia(e.target.checked)} className="accent-primary" />
                  <span className="text-xs text-muted-foreground">Include media</span>
                </label>
              </>
            )}
            {scrapeMode === "facebook" && (
              <>
                <Field label="C User">
                  <input className="input font-mono text-xs" value={scrapeFbCUser} onChange={(e) => setScrapeFbCUser(e.target.value)} placeholder="Facebook cookie c_user" />
                </Field>
                <Field label="XS">
                  <input className="input font-mono text-xs" value={scrapeFbXs} onChange={(e) => setScrapeFbXs(e.target.value)} placeholder="Facebook cookie xs" />
                </Field>
                <Field label="Max posts">
                  <input className="input" type="number" value={scrapeFbMaxPosts} onChange={(e) => setScrapeFbMaxPosts(Number(e.target.value))} />
                </Field>
                <Field label="Scroll rounds">
                  <input className="input" type="number" value={scrapeFbScrollRounds} onChange={(e) => setScrapeFbScrollRounds(Number(e.target.value))} />
                </Field>
                <Field label="Date from">
                  <input className="input text-xs" type="date" value={scrapeFbDateFrom} onChange={(e) => setScrapeFbDateFrom(e.target.value)} />
                </Field>
                <Field label="Date to">
                  <input className="input text-xs" type="date" value={scrapeFbDateTo} onChange={(e) => setScrapeFbDateTo(e.target.value)} />
                </Field>
              </>
            )}
            {scrapeMode === "profile" && (
              <>
                <Field label="Platform">
                  <select className="input text-xs" value={scrapeProfilePlatform} onChange={(e) => setScrapeProfilePlatform(e.target.value)}>
                    <option value="">Select platform</option>
                    <option value="instagram">Instagram</option>
                    <option value="twitter">Twitter / X</option>
                    <option value="facebook">Facebook</option>
                    <option value="reddit">Reddit</option>
                    <option value="github">GitHub</option>
                    <option value="tiktok">TikTok</option>
                    <option value="pinterest">Pinterest</option>
                  </select>
                </Field>
                <Field label="Username">
                  <input className="input font-mono text-xs" value={scrapeProfileUsername} onChange={(e) => setScrapeProfileUsername(e.target.value)} placeholder="username" />
                </Field>
              </>
            )}
          </div>

          {/* Additional Options — sab modes ke liye common */}
          <div className="mt-4 pt-4 border-t border-border">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">Additional Options</h4>
            <div className="flex flex-wrap gap-x-6 gap-y-2">
              <label className="inline-flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={scrapeDeepCrawl} onChange={(e) => setScrapeDeepCrawl(e.target.checked)} className="accent-primary" />
                <span className="text-xs text-muted-foreground">DeepCrawl (bypass bot protection)</span>
              </label>
              <label className="inline-flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={scrapeImages} onChange={(e) => setScrapeImages(e.target.checked)} className="accent-primary" />
                <span className="text-xs text-muted-foreground">Images</span>
              </label>
              <label className="inline-flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={scrapePdfs} onChange={(e) => setScrapePdfs(e.target.checked)} className="accent-primary" />
                <span className="text-xs text-muted-foreground">PDFs</span>
              </label>
              <label className="inline-flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={scrapePlaywright} onChange={(e) => setScrapePlaywright(e.target.checked)} className="accent-primary" />
                <span className="text-xs text-muted-foreground">Playwright (browser rendering)</span>
              </label>
            </div>
          </div>

          {/* Scrape result */}
          {scrapeResult && (
            <div className="mt-4 rounded-lg border border-border bg-elevated/50 p-3 text-xs">
              {scrapeResult?.data?.title ? (
                <div>
                  <div className="text-success font-semibold mb-1">✅ {scrapeResult.data.title}</div>
                  <div className="text-muted-foreground">Links: {scrapeResult.data.links_count} | Adapter: {scrapeResult.data.adapter_used} | Quality: {scrapeResult.data.quality_score}/{scrapeResult.data.quality_level}</div>
                  <div className="mt-1 flex flex-wrap gap-2">
                    {scrapeResult.data.content_type && <span className="rounded bg-elevated px-1.5 py-0.5 text-[10px]">Type: {scrapeResult.data.content_type}</span>}
                    {scrapeResult.data.html_length && <span className="rounded bg-elevated px-1.5 py-0.5 text-[10px]">HTML: {scrapeResult.data.html_length}B</span>}
                    {scrapeResult.data.elapsed_ms && <span className="rounded bg-elevated px-1.5 py-0.5 text-[10px]">Time: {scrapeResult.data.elapsed_ms}ms</span>}
                  </div>
                  {scrapeResult.data.error && <div className="text-destructive mt-1">{scrapeResult.data.error}</div>}
                </div>
              ) : scrapeResult?.data?.stats?.title ? (
                <div>
                  <div className="text-success font-semibold mb-1">✅ {scrapeResult.data.stats.title}</div>
                  <div className="text-muted-foreground">
                    WordPress: {scrapeResult.data.is_wordpress ? "Yes" : "No"} | Posts: {scrapeResult.data.stats.posts_found} | Pages: {scrapeResult.data.stats.pages_found} | Media: {scrapeResult.data.stats.media_found} | PDFs: {scrapeResult.data.stats.pdf_count}
                  </div>
                  {scrapeResult.data.posts?.length > 0 && (
                    <div className="mt-2">
                      <span className="text-[10px] text-muted-foreground">Posts:</span>
                      <div className="max-h-24 overflow-y-auto space-y-1 mt-1">
                        {scrapeResult.data.posts.slice(0, 10).map((p: any, i: number) => (
                          <div key={i} className="flex items-center gap-2 text-muted-foreground text-[10px]">
                            <span className="text-success">●</span>
                            <span className="truncate">{p.title}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {scrapeResult.data.error && <div className="text-destructive mt-1">{scrapeResult.data.error}</div>}
                  {scrapeResult.data.elapsed_ms && <div className="text-muted-foreground mt-1 text-[10px]">Time: {scrapeResult.data.elapsed_ms}ms</div>}
                </div>
              ) : scrapeResult.status === "completed" ? (
                <div>
                  <div className="text-success font-semibold mb-1">✅ Scraped {scrapeResult.files_saved} file(s) from {scrapeResult.url}</div>
                  {scrapeResult.files?.length > 0 && (
                    <div className="mt-2 max-h-24 overflow-y-auto space-y-1">
                      {scrapeResult.files.map((f: any, i: number) => (
                        <div key={i} className="flex items-center gap-2 text-muted-foreground">
                          <span className="text-success">●</span>
                          <span className="font-mono">{f.file || f}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-destructive">❌ {scrapeResult.error || scrapeResult?.data?.error || "Scrape failed"}</div>
              )}
            </div>
          )}

          {/* Job status */}
          {scrapeJobStatus && (
            <div className="mt-3 rounded-lg border border-border bg-elevated/50 p-3 text-xs">
              <div className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full ${scrapeJobStatus.data?.status === "completed" ? "bg-success" : scrapeJobStatus.data?.status === "error" ? "bg-destructive" : "bg-amber-400 animate-pulse"}`} />
                <span className="font-semibold capitalize">{scrapeJobStatus.data?.status || "running"}</span>
              </div>
              {scrapeJobStatus.data?.message && <div className="mt-1 text-muted-foreground">{scrapeJobStatus.data.message}</div>}
              {scrapeJobStatus.data?.progress !== undefined && (
                <div className="mt-2 h-1.5 rounded-full bg-elevated overflow-hidden">
                  <div className="h-full rounded-full bg-primary" style={{ width: `${scrapeJobStatus.data.progress}%` }} />
                </div>
              )}
            </div>
          )}

          {/* ── Scrape History ── */}
          <ScrapeHistory tenantId={tenantId} />

          {/* ── Live Scraper Logs ── */}
          {scraperHealth?.alive && (
            <div className="mt-4 rounded-lg border border-border overflow-hidden">
              <button
                onClick={() => setScraperLogsExpanded(!scraperLogsExpanded)}
                className="flex w-full items-center justify-between px-3 py-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground hover:bg-elevated/40"
              >
                <span>Live Scraper Logs</span>
                <span className="text-[10px]">{scraperLogsExpanded ? "[-]" : "[+]"}</span>
              </button>
              {scraperLogsExpanded && (
                <div className="border-t border-border">
                  <div
                    ref={logsContainerRef}
                    className="max-h-48 overflow-y-auto bg-[#0d1117] p-2 font-mono text-[11px] leading-relaxed"
                    style={{ scrollBehavior: "smooth" }}
                  >
                    {scraperLogs.length === 0 ? (
                      <div className="text-muted-foreground italic">No scraper logs available</div>
                    ) : (
                      scraperLogs.map((log: any, i: number) => {
                        const levelColor =
                          log.level === "ERROR"   ? "text-red-400" :
                          log.level === "WARNING" ? "text-yellow-400" :
                          log.level === "INFO"    ? "text-green-400" :
                          "text-gray-400";
                        return (
                          <div key={i} className="flex gap-2">
                            <span className="shrink-0 text-gray-500 select-none">
                              {log.timestamp?.split(".")[0]?.split("T")?.[1]?.slice(0, 8) || ""}
                            </span>
                            <span className={`shrink-0 w-14 ${levelColor}`}>{log.level}</span>
                            <span className="text-gray-400 shrink-0">{log.name?.split(".").pop()}</span>
                            <span className="text-gray-200">{log.message}</span>
                          </div>
                        );
                      })
                    )}
                  </div>
                  <div className="flex items-center justify-between border-t border-border px-3 py-1">
                    <label className="flex items-center gap-1.5 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={scraperLogsAutoScroll}
                        onChange={(e) => setScraperLogsAutoScroll(e.target.checked)}
                        className="accent-primary"
                      />
                      <span className="text-[10px] text-muted-foreground">Auto-scroll</span>
                    </label>
                    <span className="text-[10px] text-muted-foreground">
                      Refreshing every 3s · {scraperLogs.length} lines
                    </span>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {source === "crawl" && (
        <div className="panel p-6">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Crawl Output</h3>
          <p className="mt-2 text-xs text-muted-foreground">Browse scraped sites from the scraper service and import content to tenant documents.</p>

          {!selectedCrawlSite ? (
            <div className="mt-4 space-y-3">
              {crawlSites?.sites && crawlSites.sites.length > 0 ? (
                <div className="grid gap-2">
                  {crawlSites.sites.map((site: any) => (
                    <button
                      key={site.site}
                      onClick={() => setSelectedCrawlSite(site.site)}
                      className="flex items-center justify-between rounded-lg border border-border bg-elevated/50 px-4 py-3 text-sm hover:border-primary/50 hover:bg-elevated"
                    >
                      <div className="flex items-center gap-3">
                        <Globe className="h-4 w-4 text-primary" />
                        <div className="text-left">
                          <div className="font-medium">{site.site}</div>
                          <div className="text-[10px] text-muted-foreground">
                            {site.metadata?.site || "Unknown site"}
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                        {site.hasImages && <span className="rounded bg-elevated px-1.5 py-0.5">Images</span>}
                        {site.hasPdfs && <span className="rounded bg-elevated px-1.5 py-0.5">PDFs</span>}
                        {site.hasPages && <span className="rounded bg-elevated px-1.5 py-0.5">Pages</span>}
                      </div>
                    </button>
                  ))}
                </div>
              ) : (
                <div className="py-8 text-center text-xs text-muted-foreground">
                  No crawl output found. Run a crawl first to generate content.
                </div>
              )}
            </div>
          ) : (
            <div className="mt-4 space-y-4">
              <button
                onClick={() => setSelectedCrawlSite(null)}
                className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground"
              >
                <ArrowLeft className="h-3 w-3" />
                Back to sites
              </button>

              {selectedCrawlSiteData && (
                <>
                  <div className="panel p-4">
                    <div className="flex items-center gap-3 mb-3">
                      <Globe className="h-5 w-5 text-primary" />
                      <div>
                        <div className="font-semibold text-sm">{selectedCrawlSiteData.site}</div>
                        <div className="text-[10px] text-muted-foreground">
                          {selectedCrawlSiteData.metadata?.site || "Unknown site"}
                        </div>
                      </div>
                    </div>
                    {selectedCrawlSiteData.metadata && (
                      <div className="grid gap-2 text-[10px] text-muted-foreground">
                        <div>Strategy: {selectedCrawlSiteData.metadata.strategy}</div>
                        <div>WordPress: {selectedCrawlSiteData.metadata.is_wordpress ? "Yes" : "No"}</div>
                        <div>Languages: {selectedCrawlSiteData.metadata.languages_found?.join(", ") || "—"}</div>
                        <div>Crawled: {selectedCrawlSiteData.metadata.crawled_at}</div>
                      </div>
                    )}
                  </div>

                  <div className="grid gap-4 md:grid-cols-3">
                    <div className="panel p-4">
                      <div className="text-xs font-semibold mb-2">Pages ({selectedCrawlSiteData.files?.pages?.length || 0})</div>
                      <div className="max-h-32 overflow-y-auto space-y-1">
                        {selectedCrawlSiteData.files?.pages?.map((page: string, i: number) => (
                          <div key={i} className="text-[10px] text-muted-foreground truncate font-mono">
                            {page}
                          </div>
                        ))}
                      </div>
                    </div>
                    <div className="panel p-4">
                      <div className="text-xs font-semibold mb-2">Images ({selectedCrawlSiteData.files?.images?.length || 0})</div>
                      <div className="max-h-32 overflow-y-auto space-y-1">
                        {selectedCrawlSiteData.files?.images?.slice(0, 10).map((img: string, i: number) => (
                          <div key={i} className="text-[10px] text-muted-foreground truncate font-mono">
                            {img}
                          </div>
                        ))}
                        {selectedCrawlSiteData.files?.images?.length > 10 && (
                          <div className="text-[10px] text-muted-foreground">
                            +{selectedCrawlSiteData.files.images.length - 10} more
                          </div>
                        )}
                      </div>
                    </div>
                    <div className="panel p-4">
                      <div className="text-xs font-semibold mb-2">PDFs ({selectedCrawlSiteData.files?.pdfs?.length || 0})</div>
                      <div className="max-h-32 overflow-y-auto space-y-1">
                        {selectedCrawlSiteData.files?.pdfs?.map((pdf: string, i: number) => (
                          <div key={i} className="text-[10px] text-muted-foreground truncate font-mono">
                            {pdf}
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>

                  <button
                    onClick={() => handleImportCrawlOutput(selectedCrawlSite)}
                    disabled={!tenantId}
                    className="inline-flex items-center gap-1.5 rounded-md bg-[image:var(--gradient-primary)] px-4 py-2 text-xs font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50"
                  >
                    <Upload className="h-3.5 w-3.5" />
                    Import all content to tenant documents
                  </button>
                </>
              )}
            </div>
          )}
        </div>
      )}

      {source === "cloud" && (
        <div className="panel p-6">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Connect a cloud source</h3>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            {[
              { name: "Google Drive", provider: "google_drive" },
              { name: "Notion", provider: "direct_url" },
              { name: "Confluence", provider: "direct_url" },
              { name: "Dropbox", provider: "direct_url" },
              { name: "OneDrive", provider: "onedrive" },
              { name: "S3 Bucket", provider: "direct_url" },
            ].map(({ name, provider }) => (
              <button
                key={name}
                onClick={() => setCloudProvider(provider)}
                className="flex items-center justify-between rounded-lg border border-border bg-elevated/50 px-4 py-3 text-sm hover:border-primary/50 hover:bg-elevated"
              >
                <span className="font-medium">{name}</span>
                <span className="text-xs text-[color:var(--accent-emerald)]">Connect</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="panel overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <div className="text-sm font-semibold">Documents</div>
          <div className="text-xs text-muted-foreground">{docs.length} files</div>
        </div>
        {docs.length === 0 ? (
          <div className="py-12 text-center text-xs text-muted-foreground">No documents uploaded yet</div>
        ) : (
            <table className="w-full text-sm">
            <thead className="bg-elevated/60 text-left text-xs uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-5 py-3">Name</th>
                <th className="px-5 py-3">Source</th>
                <th className="px-5 py-3">Size</th>
                <th className="px-5 py-3">Chunks</th>
                <th className="px-5 py-3">Ingested</th>
                <th className="px-5 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {docs.map((d: any, i: number) => {
                const src = d.source || "upload";
                const srcColors: Record<string, string> = {
                  upload: "bg-[color:var(--accent-violet)]/10 text-[color:var(--accent-violet)] border-[color:var(--accent-violet)]/20",
                  scrape: "bg-[color:var(--accent-sky)]/10 text-[color:var(--accent-sky)] border-[color:var(--accent-sky)]/20",
                  cloud: "bg-success/10 text-success border-success/20",
                  googledrive: "bg-[#4285f4]/10 text-[#4285f4] border-[#4285f4]/20",
                  onedrive: "bg-[#0078d4]/10 text-[#0078d4] border-[#0078d4]/20",
                  s3: "bg-[#ff9900]/10 text-[#ff9900] border-[#ff9900]/20",
                };
                return (
                <tr key={d.name || i} className="hover:bg-elevated/40">
                  <td className="px-5 py-3 font-medium">
                    <div className="flex items-center gap-2"><FileText className="h-4 w-4 text-primary" /> {d.name}</div>
                  </td>
                  <td className="px-5 py-3">
                    <span className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${srcColors[src] || srcColors.upload} border`}>{src}</span>
                  </td>
                  <td className="px-5 py-3 text-muted-foreground text-xs">{formatSize(d.size_bytes)}</td>
                  <td className="px-5 py-3 font-mono text-xs">{d.chunks ?? "—"}</td>
                  <td className="px-5 py-3"><Pill status={d.ingested ? "indexed" : "queued"} /></td>
                  <td className="px-5 py-3 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <button onClick={() => handleViewChunks(d.name)} className="rounded p-1.5 text-muted-foreground hover:bg-elevated" title="View chunks">
                        <Database className="h-4 w-4" />
                      </button>
                      <button onClick={() => handleDeleteDoc(d.name)} className="rounded p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive" title="Delete">
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

      {viewDoc && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 backdrop-blur-sm" onClick={() => setViewDoc(null)}>
          <div className="flex max-h-[80vh] w-full max-w-2xl flex-col rounded-xl border border-border bg-[var(--modal-bg)] shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-border px-6 py-4">
              <div>
                <h2 className="text-base font-bold">Chunks: {viewDoc}</h2>
                <p className="text-xs text-muted-foreground">{chunks.length} chunk{chunks.length !== 1 ? 's' : ''}</p>
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
                    {c.metadata && Object.keys(c.metadata).length > 0 && (
                      <div className="mt-2 text-[10px] text-muted-foreground">
                        {Object.entries(c.metadata).map(([k, v]) => (
                          <span key={k} className="mr-3"><span className="font-medium">{k}:</span> {String(v)}</span>
                        ))}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}

      {cloudProvider && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 backdrop-blur-sm" onClick={() => setCloudProvider(null)}>
          <div className="w-full max-w-lg rounded-xl border border-border bg-[var(--modal-bg)] p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-bold">Cloud Sync — {cloudProvider}</h2>
              <button onClick={() => setCloudProvider(null)} className="rounded-md p-1.5 text-muted-foreground hover:bg-elevated"><X className="h-4 w-4" /></button>
            </div>
            <CloudSyncInline tenantId={tenantId} initialProvider={cloudProvider} onClose={() => setCloudProvider(null)} />
          </div>
        </div>
      )}
    </div>
  );
}

function SourceCard({
  active, onClick, accent, icon: Icon, title, desc,
}: {
  active: boolean; onClick: () => void; accent: AccentKey;
  icon: React.ComponentType<{ className?: string }>; title: string; desc: string;
}) {
  const a = accents[accent];
  return (
    <button
      onClick={onClick}
      className={`relative overflow-hidden rounded-xl p-5 text-left transition ${active ? "" : "opacity-80 hover:opacity-100"}`}
      style={{
        background: active ? a.bg : "var(--panel)",
        color: active ? a.fg : "var(--color-foreground)",
        border: `1px solid ${active ? "transparent" : "var(--panel-border)"}`,
        boxShadow: active ? `0 12px 34px -14px ${a.ring}` : undefined,
      } as React.CSSProperties}
    >
      <div className="flex items-start justify-between">
        <div className="grid h-10 w-10 place-items-center rounded-lg" style={{ background: active ? "rgba(0,0,0,0.18)" : a.bg, color: active ? a.fg : a.fg }}>
          <Icon className="h-5 w-5" />
        </div>
        {active && <span className="rounded-full bg-black/25 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider">Selected</span>}
      </div>
      <div className="mt-3 text-base font-bold">{title}</div>
      <div className={`mt-1 text-xs ${active ? "opacity-85" : "text-muted-foreground"}`}>{desc}</div>
    </button>
  );
}


function Pill({ status }: { status: string }) {
  const map: Record<string, string> = {
    indexed: "bg-success/15 text-success",
    indexing: "bg-warning/15 text-warning",
    crawling: "bg-[color:var(--accent-sky)]/20 text-[color:var(--accent-sky)]",
    scheduled: "bg-[color:var(--accent-violet)]/20 text-[color:var(--accent-violet)]",
    queued: "bg-muted-foreground/15 text-muted-foreground",
    error: "bg-destructive/15 text-destructive",
  };
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium capitalize ${map[status] ?? map.queued}`}>
      {status}
    </span>
  );
}


function PlaygroundTab({ tenantId }: { tenantId?: string }) {
  const { data: sessions = [], refetch: refetchSessions } = useQuery({
    queryKey: ["sessions", tenantId],
    queryFn: async () => {
      if (!tenantId) return [];
      const res = await apiFetch(`/tenants/${tenantId}/sessions`);
      const data = await res.json();
      return data.sessions || [];
    },
    enabled: !!tenantId
  });

  const [selectedSession, setSelectedSession] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState("");
  const [chatTurns, setChatTurns] = useState<Array<{ role: string; content: string }>>([]);
  const [contexts, setContexts] = useState<any[]>([]);
  const [systemPrompt, setSystemPrompt] = useState("");
  const [showPromptSection, setShowPromptSection] = useState(false);
  const [drawerContext, setDrawerContext] = useState<any>(null);
  const turnsLoaded = useRef(false);
  const prevSessionRef = useRef<string | null>(null);

  const { data: sessionTurns } = useQuery({
    queryKey: ["session-turns", tenantId, selectedSession],

    queryFn: async () => {
      if (!tenantId || !selectedSession) return [];
      const res = await apiFetch(`/tenants/${tenantId}/sessions/${selectedSession}/turns`);
      const data = await res.json();
      return data.turns || [];
    },
    enabled: !!tenantId && !!selectedSession
  });

  const { data: tenantConfig } = useQuery({
    queryKey: ["tenant-config", tenantId],
    queryFn: async () => {
      if (!tenantId) return null;
      const res = await apiFetch(`/tenants/${tenantId}/config`);
      return res.json();
    },
    enabled: !!tenantId,
  });

  useEffect(() => {
    if (tenantConfig?.systemPrompt) setSystemPrompt(tenantConfig.systemPrompt);
  }, [tenantConfig]);

  useEffect(() => {
    if (selectedSession !== prevSessionRef.current) {
      prevSessionRef.current = selectedSession;
      turnsLoaded.current = false;
    }
    if (!selectedSession) {
      setChatTurns([]);
      setContexts([]);
    } else if (sessionTurns && sessionTurns.length > 0 && !turnsLoaded.current) {
      setChatTurns(sessionTurns.map((t: any) => ({ role: t.role, content: t.content })));
      turnsLoaded.current = true;
    }
  }, [sessionTurns, selectedSession]);

  const queryClient = useQueryClient();

  async function handleChat(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim() || !tenantId || loading || streaming) return;
    const userMsg = query.trim();
    const sessionId = selectedSession || `session-${Date.now()}`;
    const isNewSession = !selectedSession;
    setQuery("");
    setError("");
    setChatTurns((prev) => [...prev, { role: "user", content: userMsg }]);
    setStreaming(true);
    setLoading(true);
    try {
      const streamRes = await fetch("/api/v1" + `/tenants/${tenantId}/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${getAuthToken()}`,
        },
        body: JSON.stringify({
          query: userMsg,
          session_id: sessionId,
          system_prompt: systemPrompt || null,
        }),
      });

      if (!streamRes.ok) {
        const errData = await streamRes.json().catch(() => ({}));
        throw new Error(errData.detail || `Stream error ${streamRes.status}`);
      }

      const reader = streamRes.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let fullText = "";
      let citations: any[] = [];

      setChatTurns((prev) => [...prev, { role: "assistant", content: "" }]);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const dataStr = line.slice(6).trim();
          if (!dataStr) continue;

          try {
            const data = JSON.parse(dataStr);
            if (data.text) {
              fullText += data.text;
              setChatTurns((prev) => {
                const updated = [...prev];
                updated[updated.length - 1] = { role: "assistant", content: fullText };
                return updated;
              });
            }
            if (data.citations) {
              citations = data.citations;
              const ctxMap: any[] = [];
              citations.forEach((c: any, i: number) => {
                ctxMap[c.index || i] = { metadata: { document_name: c.document_name, section: c.section }, text: `[Citation ${c.index || i}]`, score: 1, dense_score: 0, sparse_score: 0 };
              });
              setContexts(ctxMap);
            }
            if (data.error) {
              setError(data.error);
            }
          } catch { /* skip parse errors */ }
        }
      }

      // Final update — mark streaming done
      setChatTurns((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = { role: "assistant", content: fullText };
        return updated;
      });

      setStreaming(false);
      setLoading(false);
      if (isNewSession) {
        setSelectedSession(sessionId);
        turnsLoaded.current = true;
        queryClient.invalidateQueries({ queryKey: ["sessions", tenantId] });
      }
    } catch (e: any) {
      setError(e.message);
      setChatTurns((prev) => [...prev, { role: "assistant", content: `Error: ${e.message}` }]);
      setStreaming(false);
      setLoading(false);
    }
  }

  function handleNewSession() {
    setSelectedSession(null);
    setChatTurns([]);
    setContexts([]);
  }

  async function handleDeleteSession(sessionId: string) {
    if (!tenantId) return;
    if (!confirm(`Delete chat session '${sessionId}' and all its turns?`)) return;
    try {
      await apiFetch(`/tenants/${tenantId}/sessions/${sessionId}`, { method: "DELETE" });
      if (selectedSession === sessionId) handleNewSession();
      refetchSessions();
    } catch (e: any) {
      alert("Delete failed: " + e.message);
    }
  }

  function formatCitations(text: string) {
    return text.replace(/\[(\d+)\]/g, (match, num) => {
      return `<span class="citation-tag" data-citation="${num}">[${num}]</span>`;
    });
  }

  function renderProfiler(profile: any) {
    if (!profile) return "";
    const p = profile;
    const sub = p.subspans || {};
    const ret = sub.retrieval || {};
    const isLlmSlow = p.llm_ms > 10000;
    return `<div style="margin-top:12px;border:1px solid var(--panel-border);border-radius:10px;background:rgba(0,0,0,0.25);overflow:hidden;">
      <details style="padding:10px 14px;">
        <summary style="cursor:pointer;outline:none;font-size:11.5px;font-weight:700;color:var(--color-primary);display:flex;justify-content:space-between;align-items:center;user-select:none;">
          <span>⚡ Pipeline Profiler (${p.total_ms} ms)</span>
          <span style="font-size:10.5px;color:var(--color-muted-foreground);">▾</span>
        </summary>
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;font-size:11px;margin:10px 0 12px 0;padding-bottom:10px;border-bottom:1px dashed var(--panel-border);">
          <div>🔍 Retrieval: <b>${p.retrieval_ms} ms</b></div>
          <div>🧠 Memory: <b>${p.memory_ms} ms</b></div>
          <div>🤖 LLM: <b style="color:${isLlmSlow ? "var(--color-warning)" : "var(--color-success)"};">${p.llm_ms} ms</b></div>
        </div>
        <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:4px;font-size:10.5px;font-family:var(--font-mono);background:rgba(0,0,0,0.2);padding:8px;border-radius:6px;">
          <span>DB Fetch: ${ret.db_chunks_fetch_ms || 0}ms</span>
          <span>Embedding: ${ret.dense_embedding_ms || 0}ms</span>
          <span>Vector Sim: ${ret.vector_similarity_ms || 0}ms</span>
          <span>BM25: ${ret.bm25_keyword_ms || 0}ms</span>
          <span>Rerank: ${ret.reranking_ms || 0}ms</span>
          <span>Scanned: ${ret.total_chunks_scanned || 0}</span>
          <span>Provider: ${p.llm_provider || ""}</span>
          <span>Model: ${p.llm_model || ""}</span>
        </div>
      </details>
    </div>`;
  }

  function renderValidation(v: any) {
    if (!v) return "";
    const confColor = v.confidence === "high" ? "var(--color-success)" : v.confidence === "medium" ? "var(--color-warning)" : "var(--color-destructive)";
    return `<div class="validation-metrics">
      <span class="validation-pill" style="color:${confColor}">🛡️ Grounding: ${(v.confidence || "unknown").toUpperCase()}</span>
      <span>|</span>
      <span>Sufficient: <b>${v.sufficient ? "Yes" : "No"}</b></span>
      <span>|</span>
      <span>Score: <b>${(v.confidence_score || 0).toFixed(2)}</b></span>
    </div>`;
  }

  return (
    <div className="grid h-[calc(100vh-260px)] gap-4 lg:grid-cols-[220px_1fr_320px]" style={{ position: "relative" }}>
      <div className="panel flex flex-col p-4">
        <div className="mb-3 flex items-center justify-between">
          <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Sessions</div>
          <button className="text-[10px] text-primary hover:underline" onClick={handleNewSession}>+ New</button>
        </div>
        <div className="space-y-1 overflow-y-auto flex-1">
          {sessions.length === 0 ? (
            <div className="text-center py-8 text-xs text-muted-foreground">No sessions yet</div>
          ) : (
            sessions.map((s: any, i: number) => (
              <div key={s.sessionId || i} className="flex items-center gap-1">
                <button
                  className={`flex-1 rounded-md px-3 py-2 text-left text-sm ${selectedSession === s.sessionId ? "bg-primary/15" : "hover:bg-elevated"}`}
                  onClick={() => setSelectedSession(s.sessionId)}
                >
                  <div className="truncate font-medium">{s.sessionId}</div>
                  <div className="text-[10px] text-muted-foreground">{s.turns || 0} turns</div>
                </button>
                <button onClick={() => handleDeleteSession(s.sessionId)} className="rounded p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive" title="Delete session">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="panel flex flex-col">
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <div className="text-sm font-semibold">{selectedSession || "New Chat"}</div>
          {error && <div className="text-xs text-destructive">{error}</div>}
        </div>
        <div className="border-b border-border px-5 py-2">
          <button
            onClick={() => setShowPromptSection(!showPromptSection)}
            className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground hover:text-foreground transition"
          >
            <Settings2 className="h-3 w-3" />
            System Prompt
            <ChevronDown className={`h-3 w-3 transition ${showPromptSection ? 'rotate-180' : ''}`} />
          </button>
          {showPromptSection && (
            <div className="mt-2 flex gap-2">
              <textarea
                className="input flex-1 resize-none font-mono text-xs min-h-[80px]"
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                placeholder="Custom system prompt for test queries..."
              />
              <button
                onClick={async () => {
                  if (!tenantId) return;
                  try {
                    await apiFetch(`/tenants/${tenantId}`, {
                      method: "PUT",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ system_prompt: systemPrompt || null }),
                    });
                  } catch (e: any) { setError("Save failed: " + e.message); }
                }}
                className="self-start rounded-md bg-[image:var(--gradient-primary)] px-3 py-1.5 text-[11px] font-semibold text-primary-foreground hover:opacity-90"
              >
                Save
              </button>
            </div>
          )}
        </div>
        <div className="flex-1 space-y-4 overflow-y-auto px-5 py-5" id="chat-container">
          {chatTurns.length === 0 ? (
            <Bubble role="bot">👋 Ask a question about this tenant's indexed corpus.</Bubble>
          ) : (
            chatTurns.map((turn, i) => {
              // During streaming the last assistant turn starts empty — skip it,
              // the spinner bubble below handles that state
              const isStreamingPlaceholder =
                streaming && turn.role === "assistant" && i === chatTurns.length - 1 && !turn.content;
              if (isStreamingPlaceholder) return null;
              return (
                <Bubble key={i} role={turn.role === "user" ? "user" : "bot"}>
                  {turn.role === "assistant" ? (
                    <>
                      {renderMarkdown(turn.content)}
                      {streaming && i === chatTurns.length - 1 && turn.content && (
                        <span className="inline-block ml-1 w-2 h-4 bg-primary animate-pulse align-middle" />
                      )}
                    </>
                  ) : (
                    turn.content
                  )}
                </Bubble>
              );
            })
          )}
          {(loading || streaming) && (
            <Bubble role="bot">
              <span className="inline-flex items-center gap-2"><Loader2 className="h-3.5 w-3.5 animate-spin" /> {streaming ? "Streaming..." : "Thinking..."}</span>
            </Bubble>
          )}
        </div>
        <form className="flex items-center gap-2 border-t border-border px-4 py-3" onSubmit={handleChat}>
          <input className="input flex-1" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Type your query to test retrieval…" disabled={loading} />
          <button disabled={loading || streaming || !query.trim()} className="inline-flex items-center gap-1.5 rounded-md bg-[image:var(--gradient-primary)] px-4 py-2 text-sm font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            Send
          </button>
        </form>
      </div>

      <div className="panel flex flex-col p-4">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-3">
          Retrieved Chunks
        </div>
        <div className="space-y-3 overflow-y-auto flex-1 text-sm">
          {contexts.length === 0 ? (
            <div className="text-center py-8 text-xs text-muted-foreground">Send a query to see retrieved chunks</div>
          ) : (
            contexts.map((ctx: any, i: number) => (
              <div key={i} className="rounded-lg border border-border bg-elevated/50 p-3" style={{ cursor: "pointer" }} onClick={() => setDrawerContext(ctx)}>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[10px] font-semibold text-primary">{ctx.document_name || ctx.metadata?.document_name || "Document"}</span>
                  <span className="text-[10px] text-muted-foreground">
                    {ctx.dense_score != null && `D:${ctx.dense_score.toFixed(3)} `}
                    {ctx.sparse_score != null && `S:${ctx.sparse_score.toFixed(3)} `}
                    {ctx.score != null && `R:${ctx.score.toFixed(3)}`}
                  </span>
                </div>
                <p className="text-[11px] text-muted-foreground line-clamp-3">{ctx.text || ctx.content || "—"}</p>
              </div>
            ))
          )}
        </div>
      </div>

      {drawerContext && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm" onClick={() => setDrawerContext(null)}>
          <div className="absolute right-0 top-0 h-full w-[380px] bg-panel border-l border-border shadow-2xl overflow-y-auto p-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-sm font-bold text-primary uppercase tracking-wider">🔍 Context Details</h3>
              <button onClick={() => setDrawerContext(null)} className="text-muted-foreground hover:text-foreground"><X className="h-5 w-5" /></button>
            </div>
            {drawerContext.metadata && (
              <>
                <div className="rounded-lg border border-border bg-elevated/50 p-4 mb-3">
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-1">Source Document</div>
                  <div className="text-sm" style={{ color: "var(--color-primary)" }}>{drawerContext.metadata.document_name || "Unknown"}</div>
                </div>
                <div className="rounded-lg border border-border bg-elevated/50 p-4 mb-3">
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-1">Section</div>
                  <div className="text-sm">{drawerContext.metadata.section || "General"}</div>
                </div>
              </>
            )}
            <div className="rounded-lg border border-border bg-elevated/50 p-4 mb-3">
              <div className="grid grid-cols-2 gap-3">
                {drawerContext.dense_score != null && (
                  <div><div className="text-[10px] text-muted-foreground uppercase font-semibold">Dense Score</div><div className="font-mono text-sm">{drawerContext.dense_score.toFixed(4)}</div></div>
                )}
                {drawerContext.sparse_score != null && (
                  <div><div className="text-[10px] text-muted-foreground uppercase font-semibold">Sparse Score</div><div className="font-mono text-sm">{drawerContext.sparse_score.toFixed(4)}</div></div>
                )}
                {drawerContext.score != null && (
                  <div className="col-span-2"><div className="text-[10px] text-muted-foreground uppercase font-semibold">Reranker Score</div><div className="font-mono text-sm" style={{ color: "var(--color-success)" }}>{drawerContext.score.toFixed(4)}</div></div>
                )}
              </div>
            </div>
            <div className="rounded-lg border border-border bg-elevated/50 p-4">
              <div className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-1">Indexed text segment</div>
              <div className="text-xs text-muted-foreground leading-relaxed whitespace-pre-wrap" style={{ borderLeft: "2px solid var(--color-primary)", paddingLeft: 10 }}>{drawerContext.text || drawerContext.content || "—"}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Bubble({ role, children }: { role: "bot" | "user"; children: React.ReactNode }) {
  if (role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[75%] rounded-2xl rounded-br-sm bg-primary px-4 py-2.5 text-sm text-primary-foreground">
          {children}
        </div>
      </div>
    );
  }
  return (
    <div className="flex gap-3">
      <div className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-md bg-[image:var(--gradient-primary)] text-xs font-bold text-primary-foreground">
        T
      </div>
      <div className="max-w-[75%] rounded-2xl rounded-tl-sm border border-border bg-elevated px-4 py-2.5 text-sm">
        {children}
      </div>
    </div>
  );
}

function HealthTab() {
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: async () => {
      const res = await apiFetch("/health");
      return res.json();
    },
    refetchInterval: 15000,
  });

  const { data: system } = useQuery({
    queryKey: ["system-status"],
    queryFn: async () => {
      const res = await apiFetch("/system/status");
      return res.json();
    },
    refetchInterval: 30000,
  });

  const [isolation, setIsolation] = useState<any>(null);
  const [isolationLoading, setIsolationLoading] = useState(false);

  async function runIsolationAudit() {
    setIsolationLoading(true);
    try {
      const res = await apiFetch("/isolation-check");
      setIsolation(await res.json());
    } catch { setIsolation({ status: "error", score_percent: 0 }); }
    finally { setIsolationLoading(false); }
  }

  const uptime = health?.uptime_seconds ?? system?.uptime_seconds ?? 0;
  const uptimeStr = uptime < 3600
    ? `${Math.floor(uptime / 60)}m`
    : uptime < 86400
      ? `${Math.floor(uptime / 3600)}h ${Math.floor((uptime % 3600) / 60)}m`
      : `${Math.floor(uptime / 86400)}d ${Math.floor((uptime % 86400) / 3600)}h`;

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-4">
        <Stat accent="emerald" label="Uptime"          value={uptimeStr} sub={`v${health?.version || system?.version || "—"}`} icon={ShieldCheck} />
        <Stat accent="sky"     label="Total Docs"      value={String(system?.total_documents ?? "—")} sub="across all tenants" icon={FileText} />
        <Stat accent="amber"   label="Total Chunks"    value={String(system?.total_chunks ?? "—")} sub="in vector store" icon={Database} />
        <Stat accent="rose"    label="Tenants"         value={String(system?.tenants ?? "—")} sub={health?.db === "connected" ? "DB connected" : "DB: " + (health?.db || "unknown")} icon={Activity} />
      </div>

      <div className="panel overflow-hidden">
        <div className="border-b border-border px-5 py-3 text-sm font-semibold">Core services</div>
        <div className="divide-y divide-border text-sm">
          {[
            { name: "API Gateway", status: health?.status === "ok" ? "operational" : "down", latency: "—" },
            { name: "Database (SQLite)", status: health?.db === "connected" ? "operational" : "down", latency: "—" },
            { name: "Vector Store (Qdrant)", status: health?.qdrant === "connected" ? "operational" : "down", latency: "—" },
            { name: "Document Storage", status: "operational", latency: "—" },
          ].map((s, i) => (
            <div key={s.name} className="flex items-center justify-between px-5 py-3">
              <div className="flex items-center gap-2">
                <span className={`h-2 w-2 rounded-full ${s.status === "operational" ? "bg-success" : "bg-destructive"}`} />
                {s.name}
              </div>
              <div className="flex items-center gap-6 text-xs text-muted-foreground">
                <span className="font-mono">{s.latency}</span>
                <span className="capitalize">{s.status}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="panel p-5">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Client Isolation Verification Matrix</h3>
            <p className="text-xs text-muted-foreground mt-1">Multi-tenant data isolation audit</p>
          </div>
          <button onClick={runIsolationAudit} disabled={isolationLoading} className="inline-flex items-center gap-2 rounded-md bg-[image:var(--gradient-primary)] px-4 py-2 text-xs font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50">
            {isolationLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ShieldCheck className="h-3.5 w-3.5" />}
            {isolationLoading ? "Auditing..." : "Run Audit"}
          </button>
        </div>
        {isolation && (
          <div className={`mt-4 rounded-lg p-4 text-sm ${isolation.score_percent === 100 ? "bg-success/10 text-success border border-success/20" : isolation.status === "error" ? "bg-destructive/10 text-destructive border border-destructive/20" : "bg-warning/10 text-warning border border-warning/20"}`}>
            <div className="flex items-center gap-2 font-bold text-base">
              {isolation.score_percent === 100 ? "🛡️" : isolation.status === "error" ? "⚠️" : "⚡"}
              {isolation.score_percent === 100 ? `100% Isolated & Secured (${isolation.score_percent}%)` : isolation.status === "error" ? "Audit Connection Error" : `Isolation Score: ${isolation.score_percent}%`}
            </div>
            <div className="mt-2 text-xs opacity-85">
              {isolation.verified_isolated != null && `${isolation.verified_isolated}/${isolation.total_tenants} client DBs isolated`}
              {isolation.details?.length > 0 && (
                <div className="mt-2 space-y-1">
                  {isolation.details.map((d: any, i: number) => (
                    <div key={i} className="flex items-center gap-2">
                      <span className={`h-1.5 w-1.5 rounded-full ${d.isolated ? "bg-success" : "bg-destructive"}`} />
                      <span className="font-mono">{d.tenant}</span>
                      <span className="text-muted-foreground">docs_dir: {d.docs_dir_exists ? "✓" : "✗"}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

const endpoints = [
  { method: "POST", path: "/v1/query",              desc: "Retrieval-augmented answer" },
  { method: "POST", path: "/v1/documents",          desc: "Upload & index a document" },
  { method: "POST", path: "/v1/scrape",             desc: "Enqueue a web scrape job" },
  { method: "GET",  path: "/v1/documents",          desc: "List indexed documents" },
  { method: "DELETE",path:"/v1/documents/{id}",     desc: "Remove a document + chunks" },
  { method: "GET",  path: "/v1/usage",              desc: "Query & token usage" },
];

const hooks: { url: string; event: string; status: string }[] = [];

function CopyBtn({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1200); }}
      className="inline-flex items-center gap-1 rounded-md border border-border bg-panel px-2 py-1 text-[11px] font-medium hover:bg-elevated"
    >
      <Copy className="h-3 w-3" /> {copied ? "Copied" : "Copy"}
    </button>
  );
}

function IntegrationTab({ tenantId }: { tenantId: string }) {
  const { data: tenantData } = useQuery({
    queryKey: ["tenant", tenantId],
    queryFn: async () => {
      const res = await apiFetch(`/tenants/${tenantId}`);
      return res.json();
    },
  });

  const { data: config } = useQuery({
    queryKey: ["config", tenantId],
    queryFn: async () => {
      const res = await apiFetch(`/tenants/${tenantId}/config`);
      return res.json();
    },
  });

  const { data: docs = [] } = useQuery({
    queryKey: ["documents", tenantId],
    queryFn: async () => {
      const res = await apiFetch(`/tenants/${tenantId}/documents`);
      return res.json();
    },
  });

  const { data: sessions = [] } = useQuery({
    queryKey: ["sessions", tenantId],
    queryFn: async () => {
      const res = await apiFetch(`/tenants/${tenantId}/sessions`);
      const data = await res.json();
      return data.sessions || [];
    },
  });

  const apiKey = tenantData?.apiKey || "••••••••";
  const baseUrl = window.location.origin + "/api/v1";
  const indexedDocs = (docs as any[]).filter((d: any) => d.ingested).length;
  const totalChunks = (docs as any[]).reduce((sum: number, d: any) => sum + (d.chunks || 0), 0);

  const snippet = `<script
  src="${baseUrl.replace('/api/v1', '')}/widget"
  data-tenant="${tenantId}"
  data-key="${apiKey}">
</script>`;
  const apiCall = `curl ${baseUrl}/chat \\
  -H "X-API-Key: ${apiKey}" \\
  -H "Content-Type: application/json" \\
  -d '{"query":"What is our refund policy?"}'`;

  const sdks = [
    { name: "Node.js", cmd: "npm i @tenbit/rag" },
    { name: "Python",  cmd: "pip install tenbit-rag" },
    { name: "Go",      cmd: "go get github.com/tenbit/rag-go" },
    { name: "REST",    cmd: "https://api.tenbit.rag/v1" },
  ];

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-4">
        <Stat accent="sky"     label="Indexed Docs"   value={String(indexedDocs)} sub={`${(docs as any[]).length} total uploaded`} icon={FileText} />
        <Stat accent="amber"   label="Total Chunks"   value={String(totalChunks)} sub="in vector store" icon={Database} />
        <Stat accent="emerald" label="Chat Sessions"  value={String(sessions.length)} sub="all time" icon={MessageSquare} />
        <Stat accent="violet"  label="LLM Model"      value={config?.llmModel || "—"} sub={`Provider: ${config?.llmProvider || "—"}`} icon={Sparkles} />
      </div>

      <div className="panel p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Base URL</h3>
            <div className="mt-2 flex items-center gap-2 font-mono text-sm">
              <Link2 className="h-4 w-4 text-primary" />
              {baseUrl}
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              Tenant: <span className="font-mono text-foreground">{tenantId}</span> · API Key: <span className="font-mono text-foreground">{apiKey.substring(0, 16)}...</span>
            </p>
          </div>
          <CopyBtn text={baseUrl} />
        </div>
      </div>

      <div className="panel overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <div className="text-sm font-semibold flex items-center gap-2"><KeyRound className="h-4 w-4 text-[color:var(--accent-amber)]" /> API Key</div>
          <CopyBtn text={apiKey} />
        </div>
        <div className="px-5 py-4">
          <div className="font-mono text-sm break-all bg-[#0a1020] rounded-lg p-3 border border-border">{apiKey}</div>
          <p className="mt-2 text-xs text-muted-foreground">Use this key in the <code className="font-mono">X-API-Key</code> header to authenticate API requests from this tenant.</p>
        </div>
      </div>

      <div className="panel overflow-hidden">
        <div className="border-b border-border px-5 py-3 text-sm font-semibold flex items-center gap-2">
          <Code2 className="h-4 w-4 text-[color:var(--accent-sky)]" /> Available endpoints
        </div>
        <div className="divide-y divide-border text-sm">
          {endpoints.map((e, index) => (
            <div key={e.path ? `${e.method}-${e.path}-${index}` : `endpoint-${index}`} className="flex items-center justify-between px-5 py-3 hover:bg-elevated/30">
              <div className="flex items-center gap-3">
                <span
                  className="inline-flex w-16 justify-center rounded-md px-2 py-0.5 text-[11px] font-bold tracking-wide"
                  style={{
                    background:
                      e.method === "GET" ? "rgba(22,163,74,0.15)" :
                      e.method === "POST" ? "rgba(14,165,233,0.18)" :
                      "rgba(229,72,77,0.18)",
                    color:
                      e.method === "GET" ? "var(--accent-emerald)" :
                      e.method === "POST" ? "var(--accent-sky)" :
                      "var(--accent-rose)",
                  }}
                >
                  {e.method}
                </span>
                <span className="font-mono text-xs">{e.path}</span>
              </div>
              <span className="text-xs text-muted-foreground">{e.desc}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="panel p-6">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
          <Package className="h-4 w-4 text-[color:var(--accent-violet)]" /> SDKs & clients
        </h3>
        <div className="mt-4 grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          {sdks.map((s, index) => (
            <div key={s.name ? `${s.name}-${s.cmd}` : `sdk-${index}`} className="rounded-lg border border-border bg-elevated/50 p-3">
              <div className="text-xs font-semibold">{s.name}</div>
              <div className="mt-2 flex items-center justify-between gap-2 rounded-md bg-[#0a1020] px-2 py-1.5 font-mono text-[11px]">
                <span className="truncate">{s.cmd}</span>
                <CopyBtn text={s.cmd} />
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="panel p-6">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Embed the widget</h3>
          <CopyBtn text={snippet} />
        </div>
        <p className="mt-1 text-xs text-muted-foreground">Paste this before &lt;/body&gt; on the client's site.</p>
        <pre className="mt-4 overflow-x-auto rounded-lg border border-border bg-[#0a1020] p-4 text-xs leading-relaxed text-foreground/90">
          <code className="font-mono">{snippet}</code>
        </pre>
      </div>

      <div className="panel p-6">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">REST example</h3>
          <CopyBtn text={apiCall} />
        </div>
        <pre className="mt-4 overflow-x-auto rounded-lg border border-border bg-[#0a1020] p-4 text-xs leading-relaxed text-foreground/90">
          <code className="font-mono">{apiCall}</code>
        </pre>
      </div>

      <div className="panel overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <div className="text-sm font-semibold flex items-center gap-2"><Webhook className="h-4 w-4 text-[color:var(--accent-emerald)]" /> Webhooks</div>
          <button className="inline-flex items-center gap-1.5 rounded-md border border-border bg-panel px-3 py-1.5 text-xs font-medium hover:bg-elevated">
            <Plus className="h-3.5 w-3.5" /> Add endpoint
          </button>
        </div>
        <div className="divide-y divide-border text-sm">
          {hooks.map((h, index) => (
            <div key={h.url ? `${h.url}-${h.event}-${index}` : `hook-${index}`} className="flex items-center justify-between px-5 py-3">
              <div className="min-w-0">
                <div className="truncate font-mono text-xs">{h.url}</div>
                <div className="mt-0.5 text-[11px] text-muted-foreground">event: <span className="font-mono">{h.event}</span></div>
              </div>
              <div className="flex items-center gap-3 text-xs">
                <span className="inline-flex items-center gap-1.5 text-[color:var(--accent-emerald)]">
                  <span className="h-1.5 w-1.5 rounded-full bg-[color:var(--accent-emerald)]" /> {h.status}
                </span>
                <button className="rounded p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"><Trash2 className="h-4 w-4" /></button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="panel flex flex-wrap items-center justify-between gap-3 p-5">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-lg bg-[color:var(--accent-violet)]/15 text-[color:var(--accent-violet)]">
            <BookOpen className="h-5 w-5" />
          </div>
          <div>
            <div className="text-sm font-semibold">Full API reference</div>
            <div className="text-xs text-muted-foreground">OpenAPI 3.1 spec · Postman collection · SDK guides</div>
          </div>
        </div>
        <button className="inline-flex items-center gap-1.5 rounded-md border border-border bg-panel px-3 py-2 text-xs font-medium hover:bg-elevated">
          Open docs <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}


type ProviderPreset = { id: string; name: string; models: string[]; defaultBaseUrl: string };

function SettingsTab() {
  const { data: presets = [], refetch } = useQuery({
    queryKey: ["provider-presets"],
    queryFn: async () => {
      const res = await apiFetch("/admin/providers");
      return res.json();
    },
  });

  const [local, setLocal] = useState<ProviderPreset[]>([]);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const qc = useQueryClient();

  useEffect(() => { if (presets.length) setLocal(JSON.parse(JSON.stringify(presets))); }, [presets]);

  function updModel(pid: string, idx: number, val: string) {
    setLocal(prev => prev.map(p => p.id === pid ? { ...p, models: p.models.map((m, i) => i === idx ? val : m) } : p));
  }

  function addModel(pid: string) {
    setLocal(prev => prev.map(p => p.id === pid ? { ...p, models: [...p.models, ""] } : p));
  }

  function removeModel(pid: string, idx: number) {
    setLocal(prev => prev.map(p => p.id === pid ? { ...p, models: p.models.filter((_, i) => i !== idx) } : p));
  }

  async function handleSave() {
    setSaving(true); setMsg("");
    try {
      const res = await apiFetch("/admin/providers", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(local),
      });
      if (!res.ok) throw new Error("Save failed");
      setMsg("Saved successfully");
      qc.invalidateQueries({ queryKey: ["provider-presets"] });
      setTimeout(() => setMsg(""), 3000);
    } catch (e: any) { setMsg("Error: " + e.message); }
    finally { setSaving(false); }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold">Provider Settings</h2>
          <p className="text-xs text-muted-foreground mt-1">Configure LLM provider models and default base URLs globally</p>
        </div>
        <div className="flex items-center gap-3">
          {msg && <span className={`text-xs ${msg.includes("Error") ? "text-destructive" : "text-success"}`}>{msg}</span>}
          <button onClick={handleSave} disabled={saving} className="inline-flex items-center gap-2 rounded-md bg-[image:var(--gradient-primary)] px-5 py-2 text-sm font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50">
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Save Settings
          </button>
        </div>
      </div>

      {local.map((p) => (
        <div key={p.id} className="panel p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold uppercase tracking-wider">{p.name || p.id}</h3>
            <span className="text-[10px] font-mono text-muted-foreground">{p.id}</span>
          </div>
          <Field label="Default Base URL">
            <input className="input font-mono text-xs" value={p.defaultBaseUrl} onChange={(e) => setLocal(prev => prev.map(x => x.id === p.id ? { ...x, defaultBaseUrl: e.target.value } : x))} placeholder="https://api.openai.com/v1" />
          </Field>
          <div className="mt-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium text-muted-foreground">Models</span>
              <button onClick={() => addModel(p.id)} className="text-[10px] text-primary hover:underline">+ Add model</button>
            </div>
            <div className="space-y-2">
              {p.models.map((m, idx) => (
                <div key={idx} className="flex items-center gap-2">
                  <input className="input flex-1 font-mono text-xs" value={m} onChange={(e) => updModel(p.id, idx, e.target.value)} placeholder="model-name" />
                  <button onClick={() => removeModel(p.id, idx)} className="rounded p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"><X className="h-3.5 w-3.5" /></button>
                </div>
              ))}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="grid flex-1 place-items-center px-8">
      <div className="max-w-md text-center">
        <div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-elevated text-primary">
          <ShieldCheck className="h-6 w-6" />
        </div>
        <h2 className="mt-4 text-xl font-semibold">Select a client workspace</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Choose a tenant from the left to manage metadata, configure LLM endpoints, run chunking, or test queries.
        </p>
      </div>
    </div>
  );
}

function CloudSyncInline({ tenantId, initialProvider = "direct_url", onClose }: { tenantId?: string; initialProvider?: string; onClose: () => void }) {
  const [provider, setProvider] = useState(initialProvider);
  const [urlOrId, setUrlOrId] = useState("");
  const [token, setToken] = useState("");
  const [filename, setFilename] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [result, setResult] = useState<any>(null);

  async function handleSync(e: React.FormEvent) {
    e.preventDefault();
    if (!urlOrId.trim() || !tenantId) return;
    setSyncing(true); setResult(null);
    try {
      const res = await apiFetch(`/tenants/${tenantId}/cloud-sync`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider,
          cloud_url_or_id: urlOrId.trim(),
          api_key_or_token: token.trim() || null,
          custom_filename: filename.trim() || null,
          auto_ingest: true,
        }),
      });
      const data = await res.json();
      setResult(data);
    } catch (e: any) {
      setResult({ status: "failed", errors: [e.message] });
    } finally { setSyncing(false); }
  }

  return (
    <form onSubmit={handleSync} className="space-y-4">
      <Field label="Provider">
        <select className="input" value={provider} onChange={(e) => setProvider(e.target.value)}>
          <option value="direct_url">Direct URL</option>
          <option value="google_drive">Google Drive</option>
          <option value="onedrive">OneDrive</option>
        </select>
      </Field>
      <Field label={provider === "direct_url" ? "File URL" : "File ID or URL"}>
        <input className="input font-mono text-xs" value={urlOrId} onChange={(e) => setUrlOrId(e.target.value)} placeholder={provider === "direct_url" ? "https://example.com/file.pdf" : "Enter file ID or sharing URL"} />
      </Field>
      {provider === "google_drive" && (
        <Field label="API Key / Token (optional)">
          <input className="input font-mono text-xs" value={token} onChange={(e) => setToken(e.target.value)} placeholder="OAuth token or API key" />
        </Field>
      )}
      <Field label="Custom filename (optional)">
        <input className="input font-mono text-xs" value={filename} onChange={(e) => setFilename(e.target.value)} placeholder="my-document.pdf" />
      </Field>
      <div className="flex gap-3">
        <button type="submit" disabled={syncing || !urlOrId} className="inline-flex items-center gap-2 rounded-md bg-[image:var(--gradient-primary)] px-5 py-2 text-sm font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50">
          {syncing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Cloud className="h-4 w-4" />}
          {syncing ? "Syncing..." : "Start Sync"}
        </button>
        <button type="button" onClick={onClose} className="rounded-md border border-border bg-panel px-4 py-2 text-sm font-medium hover:bg-elevated">Cancel</button>
      </div>
      {result && (
        <div className={`rounded-lg p-3 text-xs ${result.status === "success" ? "bg-success/10 text-success" : result.status === "partial" ? "bg-warning/10 text-warning" : "bg-destructive/10 text-destructive"}`}>
          {result.status === "success" && `✅ Downloaded ${result.count} file(s): ${result.downloaded?.join(", ") || ""}`}
          {result.status === "partial" && `⚠️ Partial: ${result.count} file(s), ${result.errors?.length} error(s)`}
          {result.status === "failed" && `❌ ${result.errors?.join(" | ") || "Sync failed"}`}
        </div>
      )}
    </form>
  );
}

function CloudSyncModal({ tenantId, onClose }: { tenantId: string; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="w-full max-w-lg rounded-xl border border-border bg-[var(--modal-bg)] p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold">Cloud Sync</h2>
          <button onClick={onClose} className="rounded-md p-1.5 text-muted-foreground hover:bg-elevated"><X className="h-4 w-4" /></button>
        </div>
        <CloudSyncInline tenantId={tenantId} onClose={onClose} />
      </div>
    </div>
  );
}

function SystemLogsModal({ tenantId, onClose }: { tenantId?: string; onClose: () => void }) {
  const [logs, setLogs] = useState<any[]>([]);
  const [level, setLevel] = useState("");
  const [limit, setLimit] = useState(50);
  const [loading, setLoading] = useState(false);
  const [traceLog, setTraceLog] = useState<any>(null);

  async function fetchLogs() {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: String(limit) });
      if (level) params.set("level", level);
      if (tenantId) params.set("tenant_id", tenantId);
      const res = await apiFetch(`/system/logs?${params}`);
      const data = await res.json();
      setLogs(data.logs || []);
    } catch { setLogs([]); }
    finally { setLoading(false); }
  }

  useEffect(() => { fetchLogs(); }, [level, limit]);

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="flex max-h-[85vh] w-full max-w-5xl flex-col rounded-xl border border-border bg-[var(--modal-bg)] shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <h2 className="text-lg font-bold">System Activity Logs</h2>
          <button onClick={onClose} className="rounded-md p-1.5 text-muted-foreground hover:bg-elevated"><X className="h-4 w-4" /></button>
        </div>
        <div className="flex items-center gap-4 px-6 py-3 border-b border-border bg-elevated/30">
          <Field label="Level">
            <select className="input text-xs" value={level} onChange={(e) => setLevel(e.target.value)}>
              <option value="">All</option>
              <option value="ERROR">Error</option>
              <option value="WARNING">Warning</option>
              <option value="INFO">Info</option>
            </select>
          </Field>
          <Field label="Limit">
            <select className="input text-xs" value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
              <option value={50}>50</option>
              <option value={100}>100</option>
              <option value={250}>250</option>
            </select>
          </Field>
          <button onClick={fetchLogs} className="inline-flex items-center gap-1.5 rounded-md border border-border bg-panel px-3 py-2 text-xs font-medium hover:bg-elevated"><RefreshCw className="h-3.5 w-3.5" /> Refresh</button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center py-12 text-sm text-muted-foreground"><Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading logs...</div>
          ) : logs.length === 0 ? (
            <div className="py-12 text-center text-xs text-muted-foreground">No system activity logs found.</div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-elevated/60 text-left text-xs uppercase tracking-wider text-muted-foreground sticky top-0">
                <tr>
                  <th className="px-5 py-3">Time</th>
                  <th className="px-5 py-3">Level</th>
                  <th className="px-5 py-3">Operation</th>
                  <th className="px-5 py-3">Latency</th>
                  <th className="px-5 py-3">Message</th>
                  <th className="px-5 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {logs.map((l: any) => {
                  const isErr = l.level === "ERROR";
                  const isWarn = l.level === "WARNING";
                  const badgeColor = isErr ? "text-destructive" : isWarn ? "text-warning" : "text-[color:var(--accent-teal)]";
                  const badgeBg = isErr ? "bg-destructive/10" : isWarn ? "bg-warning/10" : "bg-[color:var(--accent-teal)]/10";
                  return (
                    <tr key={l.id} className="hover:bg-elevated/40">
                      <td className="px-5 py-3 font-mono text-[11px] text-muted-foreground">{l.created_at?.replace("T", " ").substring(0, 19)}</td>
                      <td className="px-5 py-3"><span className={`inline-flex rounded px-1.5 py-0.5 text-[10px] font-bold ${badgeBg} ${badgeColor} border ${badgeColor.replace("text-", "border-")}/30`}>{l.level}</span></td>
                      <td className="px-5 py-3 font-mono text-xs">{l.operation}</td>
                      <td className="px-5 py-3 font-mono text-xs text-muted-foreground">{l.latency_ms ? `${l.latency_ms} ms` : "—"}</td>
                      <td className={`px-5 py-3 text-xs max-w-xs truncate ${isErr ? "text-destructive" : "text-muted-foreground"}`}>{l.message}</td>
                      <td className="px-5 py-3 text-right">
                        {(l.traceback || l.details_json) ? (
                          <button onClick={() => setTraceLog(l)} className="rounded px-2 py-1 text-[10px] font-medium text-muted-foreground hover:bg-elevated border border-border">Inspect</button>
                        ) : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
      {traceLog && (
        <div className="fixed inset-0 z-[60] grid place-items-center bg-black/70 backdrop-blur-sm" onClick={() => setTraceLog(null)}>
          <div className="max-h-[70vh] w-full max-w-2xl rounded-xl border border-border bg-[var(--modal-bg)] p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-base font-bold">Traceback Inspector</h3>
                <p className="text-xs text-muted-foreground mt-1">Log ID: {traceLog.id} · Operation: {traceLog.operation} · {traceLog.created_at}</p>
              </div>
              <button onClick={() => setTraceLog(null)} className="rounded-md p-1.5 text-muted-foreground hover:bg-elevated"><X className="h-4 w-4" /></button>
            </div>
            <div className="space-y-4">
              <div>
                <div className="text-xs font-semibold text-muted-foreground mb-1">Exception Traceback</div>
                <pre className="rounded-lg bg-[#0a1020] p-4 text-xs font-mono leading-relaxed text-foreground/80 max-h-40 overflow-y-auto whitespace-pre-wrap">{traceLog.traceback || "No exception traceback recorded."}</pre>
              </div>
              <div>
                <div className="text-xs font-semibold text-muted-foreground mb-1">Details Payload</div>
                <pre className="rounded-lg bg-[#0a1020] p-4 text-xs font-mono leading-relaxed text-foreground/80 max-h-40 overflow-y-auto whitespace-pre-wrap">{traceLog.details_json ? (() => { try { return JSON.stringify(JSON.parse(traceLog.details_json), null, 2); } catch { return traceLog.details_json; } })() : "No extra metadata payload."}</pre>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}



import { Terminal } from "xterm";
import { FitAddon } from "@xterm/addon-fit";
import "xterm/css/xterm.css";

function ConsoleTab({ tenant }: { tenant: Tenant }) {
  const terminalRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<any>(null);
  const cmdBuffer = useRef("");
  const history = useRef<string[]>([]);
  const historyIdx = useRef(-1);

  useEffect(() => {
    if (!terminalRef.current) return;

    const term = new Terminal({
      theme: { background: "#0c0a09" },
      fontFamily: "JetBrains Mono, monospace",
      fontSize: 13,
      cursorBlink: true,
    });
    termRef.current = term;
    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(terminalRef.current);
    fitAddon.fit();

    term.writeln(`\x1b[36mConnected to ${tenant.name} console.\x1b[0m`);
    term.writeln("Type \x1b[33m/help\x1b[0m for available commands.");
    term.write("\r\n$ ");

    term.onKey((e) => {
      const char = e.key;
      if (char === "\r") {
        const cmd = cmdBuffer.current.trim();
        term.write("\r\n");
        if (cmd) {
          history.current.push(cmd);
          historyIdx.current = history.current.length;
          execCommand(term, cmd, tenant.id, cmdBuffer);
        } else {
          term.write("$ ");
        }
      } else if (char === "\x7f") {
        if (cmdBuffer.current.length > 0) {
          cmdBuffer.current = cmdBuffer.current.slice(0, -1);
          term.write("\b \b");
        }
      } else if (char === "\x1b[A") {
        if (historyIdx.current > 0) {
          historyIdx.current--;
          const prev = history.current[historyIdx.current];
          while (cmdBuffer.current.length > 0) {
            term.write("\b \b");
            cmdBuffer.current = cmdBuffer.current.slice(0, -1);
          }
          cmdBuffer.current = prev;
          term.write(prev);
        }
      } else if (char === "\x1b[B") {
        if (historyIdx.current < history.current.length - 1) {
          historyIdx.current++;
          const next = history.current[historyIdx.current];
          while (cmdBuffer.current.length > 0) {
            term.write("\b \b");
            cmdBuffer.current = cmdBuffer.current.slice(0, -1);
          }
          cmdBuffer.current = next;
          term.write(next);
        } else {
          historyIdx.current = history.current.length;
          while (cmdBuffer.current.length > 0) {
            term.write("\b \b");
            cmdBuffer.current = cmdBuffer.current.slice(0, -1);
          }
        }
      } else if (char.length === 1 && char >= " ") {
        cmdBuffer.current += char;
        term.write(char);
      }
    });

    const resizeObserver = new ResizeObserver(() => fitAddon.fit());
    resizeObserver.observe(terminalRef.current);

    return () => {
      resizeObserver.disconnect();
      term.dispose();
      termRef.current = null;
    };
  }, [tenant.id]);

  return (
    <div className="h-full flex flex-col space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold">Console Terminal</h2>
        <span className="text-xs text-muted-foreground font-mono">Status: Connected</span>
      </div>
      <div className="flex-1 panel rounded-xl overflow-hidden p-2" ref={terminalRef}></div>
    </div>
  );
}

async function execCommand(term: any, cmd: string, tenantId: string, cmdBuffer: { current: string }) {
  if (cmd === "clear" || cmd === "/clear") {
    term.clear();
    term.write("\r\n$ ");
    return;
  }
  try {
    const res = await fetch("/api/v1/terminal/exec", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command: cmd, tenant_id: tenantId }),
    });
    const data = await res.json();
    if (data.type === "error") {
      term.writeln(`\x1b[31m${data.output}\x1b[0m`);
    } else if (data.output === "CLEAR") {
      term.clear();
    } else {
      term.writeln(`\x1b[36m${data.output}\x1b[0m`);
    }
  } catch (err: any) {
    term.writeln(`\x1b[31mConnection error: ${err.message}\x1b[0m`);
  }
  cmdBuffer.current = "";
  term.write("$ ");
}
