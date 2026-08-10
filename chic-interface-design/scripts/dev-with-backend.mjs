import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const frontendDir = path.resolve(__dirname, '..');
const repoRoot = path.resolve(frontendDir, '..');
const backendHealthUrl = 'http://127.0.0.1:3001/api/v1/health';
const backendLogPath = path.join(repoRoot, '.tmp-backend-dev.log');

async function waitForBackend(timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(backendHealthUrl, { signal: AbortSignal.timeout(1500) });
      if (response.ok) return true;
    } catch {
      // backend not ready yet
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  return false;
}

async function ensureBackend() {
  try {
    const response = await fetch(backendHealthUrl, { signal: AbortSignal.timeout(1500) });
    if (response.ok) {
      console.log('Backend already available on http://127.0.0.1:3001');
      return;
    }
  } catch {
    // fall through to start backend
  }

  console.log('Starting backend on http://127.0.0.1:3001...');
  const startCommand = `
set -a
if [ -f .env ]; then
  . ./.env
fi
set +a
export PYTHONPATH="${repoRoot}/src"
export RAG_ROOT_DIR="${repoRoot}/.rbs_rag"
export QDRANT_HOST=localhost
export QDRANT_PORT=6333
export RAG_REDIS_HOST=localhost
export REDIS_HOST=localhost
export REDIS_PORT=6379
export REDIS_ENABLED=true
export SCRAPER_SERVICE_URL=http://localhost:8002
. .venv/bin/activate
.venv/bin/uvicorn rbs_rag.web.server:app --host 127.0.0.1 --port 3001 --reload --reload-dir "${repoRoot}/src" > "${backendLogPath}" 2>&1
`;

  const child = spawn('bash', ['-lc', startCommand], {
    cwd: repoRoot,
    detached: true,
    stdio: 'ignore',
  });
  child.unref();

  const ready = await waitForBackend();
  if (!ready) {
    const logTail = fs.existsSync(backendLogPath)
      ? fs.readFileSync(backendLogPath, 'utf8').trim().split('\n').slice(-20).join('\n')
      : 'No backend log available';
    console.error('Backend did not become ready in time.');
    console.error(logTail);
    process.exit(1);
  }

  console.log('Backend is ready.');
}

async function main() {
  await ensureBackend();

  const viteBin = process.platform === 'win32' ? 'npx.cmd' : 'npx';
  const vite = spawn(viteBin, ['vite', '--config', 'vite.spa.config.ts'], {
    cwd: frontendDir,
    stdio: 'inherit',
    env: process.env,
  });

  vite.on('exit', (code) => {
    process.exit(code ?? 0);
  });

  process.on('SIGINT', () => {
    vite.kill('SIGINT');
    process.exit(0);
  });

  process.on('SIGTERM', () => {
    vite.kill('SIGTERM');
    process.exit(0);
  });
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
