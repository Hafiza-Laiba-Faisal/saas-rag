import path from 'path';
import { fileURLToPath } from 'url';
import express from 'express';
import cors from 'cors';
import helmet from 'helmet';
import compression from 'compression';
import { PrismaClient } from '@prisma/client';
import { loadConfig } from './config.js';
import { AdminStore } from './adminStore.js';
import { DbStore } from './store.js';
import { createEngineFromTenant, RagEngine } from './engine.js';
import { routes } from './routes/index.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const config = loadConfig();
const prisma = new PrismaClient();
const adminStore = new AdminStore(prisma);
const dbStore = new DbStore(prisma);

const app = express();
const engineCache = new Map<string, RagEngine>();

app.use(helmet({ crossOriginResourcePolicy: false }));
app.use(cors({ origin: '*' }));
app.use(compression());
app.use(express.json({ limit: '50mb' }));
app.use(express.urlencoded({ extended: true }));

// Static files
const staticDir = path.resolve(__dirname, '../static');
app.use('/static', express.static(staticDir));

// SPA routes
app.get('/', (_req, res) => res.sendFile(path.join(staticDir, 'index.html')));
app.get('/client', (_req, res) => res.sendFile(path.join(staticDir, 'client.html')));
app.get('/widget', (_req, res) => res.sendFile(path.join(staticDir, 'widget.html')));

// Mount all API routes
app.use('/api/v1', routes(config, adminStore, dbStore, engineCache));

// Health endpoint
app.get('/api/v1/health', (_req, res) => {
  res.json({
    status: 'ok',
    db: 'connected',
    version: '1.0.0',
    uptime_seconds: Math.round(process.uptime()),
  });
});

const PORT = config.port;
app.listen(PORT, () => {
  console.log(`RAG Node server running on http://localhost:${PORT}`);
  console.log(`Dashboard: http://localhost:${PORT}`);
  console.log(`Widget: http://localhost:${PORT}/widget`);
});

// Graceful shutdown
process.on('SIGINT', async () => {
  await prisma.$disconnect();
  process.exit(0);
});
process.on('SIGTERM', async () => {
  await prisma.$disconnect();
  process.exit(0);
});
