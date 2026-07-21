import path from 'path';
import { fileURLToPath } from 'url';
import express from 'express';
import cors from 'cors';
import helmet from 'helmet';
import compression from 'compression';
import { PrismaClient } from '@prisma/client';
import { QdrantClient } from '@qdrant/js-client-rest';
import { loadConfig } from './config.js';
import { AdminStore } from './adminStore.js';
import { DbStore } from './store.js';
import { createEngineFromTenant, RagEngine } from './engine.js';
import { routes } from './routes/index.js';

// Prevent crashes from unhandled rejections (e.g. Qdrant not available)
process.on('unhandledRejection', (reason) => {
  console.warn('Unhandled rejection:', (reason as Error)?.message || reason);
});

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const config = loadConfig();

if (!process.env.DATABASE_URL) {
  process.env.DATABASE_URL = 'file:./dev.db';
}

let prisma: PrismaClient;
try {
  prisma = new PrismaClient();
} catch {
  console.error('Failed to initialize Prisma. Ensure DATABASE_URL is set.');
  process.exit(1);
}

const adminStore = new AdminStore(prisma);
const dbStore = new DbStore(prisma);

const app = express();
const engineCache = new Map<string, RagEngine>();

app.use(helmet({ crossOriginResourcePolicy: false, contentSecurityPolicy: false }));
app.use(cors({ origin: '*' }));
app.use(compression());
app.use(express.json({ limit: '50mb' }));
app.use(express.urlencoded({ extended: true }));

const staticDir = path.resolve(__dirname, '../static');

const oneYear = 365 * 24 * 60 * 60 * 1000;
app.use('/assets', express.static(path.join(staticDir, 'assets'), {
  maxAge: oneYear,
  immutable: true,
}));
app.use(express.static(staticDir));

app.use('/api/v1', routes(config, adminStore, dbStore, engineCache));

// Serve client.html for /client route
app.get('/client', (req, res) => {
  res.sendFile(path.join(staticDir, 'client.html'));
});

// Serve widget.html for /widget route
app.get('/widget', (req, res) => {
  res.sendFile(path.join(staticDir, 'widget.html'));
});

app.get('/api/v1/health', async (_req, res) => {
  let qdrantStatus = 'disconnected';
  try {
    const qdrantUrl = `${config.qdrant?.https ? 'https' : 'http'}://${config.qdrant?.host || 'localhost'}:${config.qdrant?.port || 6333}`;
    const qdrant = new QdrantClient({ url: qdrantUrl, apiKey: config.qdrant?.apiKey || undefined, checkCompatibility: false });
    await qdrant.getCollections();
    qdrantStatus = 'connected';
  } catch { /* qdrant not available */ }
  res.json({
    status: 'ok',
    db: 'connected',
    qdrant: qdrantStatus,
    version: '1.0.0',
    uptime_seconds: Math.round(process.uptime()),
  });
});

// Serve index.html (SPA) for all other non-API routes
app.get('*', (req, res, next) => {
  if (req.path.startsWith('/api/v1')) return next();
  res.sendFile(path.join(staticDir, 'index.html'));
});

const PORT = config.port;
app.listen(PORT, () => {
  console.log(`RAG Node server running on http://localhost:${PORT}`);
  console.log(`Dashboard: http://localhost:${PORT}`);
  console.log(`Widget: http://localhost:${PORT}/widget`);
});

process.on('SIGINT', async () => {
  await prisma.$disconnect();
  process.exit(0);
});
process.on('SIGTERM', async () => {
  await prisma.$disconnect();
  process.exit(0);
});
