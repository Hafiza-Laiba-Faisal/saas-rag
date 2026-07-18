import { createFileRoute, Link } from "@tanstack/react-router";
import {
  ArrowRight,
  Layers,
  MessageSquare,
  ShieldCheck,
  Sparkles,
  Users,
  Zap,
} from "lucide-react";

export const Route = createFileRoute("/")({
  component: Landing,
});

const surfaces = [
  {
    to: "/admin" as const,
    title: "Admin Dashboard",
    desc: "Onboard tenants, configure LLMs, chunk documents, monitor health.",
    icon: ShieldCheck,
    tag: "Operator console",
  },
  {
    to: "/client" as const,
    title: "Client Workspace",
    desc: "Upload docs, run the playground, tune retrieval — per API key.",
    icon: Users,
    tag: "Tenant view",
  },
  {
    to: "/widget" as const,
    title: "Chat Widget",
    desc: "Embeddable assistant with the customer's brand and citations.",
    icon: MessageSquare,
    tag: "Embed",
  },
];

const features = [
  { icon: Layers, title: "Multi-tenant isolation", body: "Every client gets a scoped index, keys, and quota." },
  { icon: Zap, title: "Streaming answers", body: "Sub-second retrieval with source citations." },
  { icon: Sparkles, title: "BYO LLM", body: "OpenAI, Anthropic, Groq, or local — swap per tenant." },
];

function Landing() {
  return (
    <div className="min-h-screen">
      {/* Nav */}
      <header className="mx-auto flex max-w-7xl items-center justify-between px-6 py-6">
        <div className="flex items-center gap-2">
          <div className="grid h-9 w-9 place-items-center rounded-lg bg-[image:var(--gradient-primary)] font-bold text-primary-foreground glow">
            T
          </div>
          <span className="text-lg font-bold tracking-tight">TenBit<span className="text-primary">.RAG</span></span>
        </div>
        <nav className="hidden items-center gap-6 text-sm text-muted-foreground md:flex">
          <a href="#platform" className="hover:text-foreground">Platform</a>
          <a href="#features" className="hover:text-foreground">Features</a>
          <Link to="/admin" className="hover:text-foreground">Admin</Link>
          <Link to="/client" className="hover:text-foreground">Client</Link>
        </nav>
        <Link
          to="/admin"
          className="inline-flex items-center gap-2 rounded-lg bg-[image:var(--gradient-primary)] px-4 py-2 text-sm font-semibold text-primary-foreground glow transition hover:opacity-90"
        >
          Open Dashboard <ArrowRight className="h-4 w-4" />
        </Link>
      </header>

      {/* Hero */}
      <section className="mx-auto max-w-7xl px-6 pb-16 pt-10 md:pt-20">
        <div className="mx-auto max-w-3xl text-center">
          <span className="inline-flex items-center gap-2 rounded-full border border-border bg-panel px-3 py-1 text-xs font-medium text-muted-foreground">
            <span className="h-1.5 w-1.5 rounded-full bg-success" /> Multi-tenant RAG, production ready
          </span>
          <h1 className="mt-6 text-4xl font-bold leading-tight tracking-tight md:text-6xl">
            Enterprise <span className="gradient-text">Retrieval-Augmented</span> Generation, without the plumbing.
          </h1>
          <p className="mt-5 text-lg text-muted-foreground">
            Onboard clients, ingest their documents, and ship an embeddable assistant — all from a single, isolated control plane.
          </p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
            <Link
              to="/admin"
              className="inline-flex items-center gap-2 rounded-lg bg-[image:var(--gradient-primary)] px-5 py-2.5 text-sm font-semibold text-primary-foreground glow transition hover:opacity-90"
            >
              Launch Admin <ArrowRight className="h-4 w-4" />
            </Link>
            <Link
              to="/widget"
              className="inline-flex items-center gap-2 rounded-lg border border-border bg-panel px-5 py-2.5 text-sm font-semibold transition hover:bg-elevated"
            >
              Preview Widget
            </Link>
          </div>
        </div>

        {/* Surfaces */}
        <div id="platform" className="mt-20 grid gap-5 md:grid-cols-3">
          {surfaces.map((s) => (
            <Link
              key={s.to}
              to={s.to}
              className="panel group relative overflow-hidden p-6 transition hover:-translate-y-1 hover:border-primary/40"
            >
              <div className="pointer-events-none absolute inset-x-0 -top-24 h-40 bg-[image:var(--gradient-subtle)] opacity-0 transition group-hover:opacity-100" />
              <div className="relative">
                <span className="text-xs font-medium uppercase tracking-wider text-primary/80">{s.tag}</span>
                <div className="mt-3 flex items-center gap-3">
                  <div className="grid h-10 w-10 place-items-center rounded-lg bg-elevated text-primary">
                    <s.icon className="h-5 w-5" />
                  </div>
                  <h3 className="text-lg font-semibold">{s.title}</h3>
                </div>
                <p className="mt-3 text-sm text-muted-foreground">{s.desc}</p>
                <div className="mt-6 inline-flex items-center gap-1 text-sm font-medium text-primary">
                  Explore <ArrowRight className="h-4 w-4 transition group-hover:translate-x-0.5" />
                </div>
              </div>
            </Link>
          ))}
        </div>

        {/* Features */}
        <div id="features" className="mt-20 grid gap-6 rounded-2xl border border-border bg-panel p-8 md:grid-cols-3">
          {features.map((f) => (
            <div key={f.title}>
              <div className="grid h-9 w-9 place-items-center rounded-md bg-elevated text-primary">
                <f.icon className="h-4 w-4" />
              </div>
              <h4 className="mt-4 font-semibold">{f.title}</h4>
              <p className="mt-1 text-sm text-muted-foreground">{f.body}</p>
            </div>
          ))}
        </div>
      </section>

      <footer className="mx-auto max-w-7xl px-6 py-10 text-sm text-muted-foreground">
        © {new Date().getFullYear()} TenBit RAG. All rights reserved.
      </footer>
    </div>
  );
}
