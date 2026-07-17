const fs = require('fs');
const path = require('path');

const staticDir = path.resolve(__dirname, 'static');
const assetsDir = path.join(staticDir, 'assets');

let cssFiles = [];
let jsFiles = [];

fs.readdirSync(assetsDir).forEach(file => {
    if (file.endsWith('.css')) cssFiles.push(file);
    if (file.endsWith('.js')) jsFiles.push(file);
});

// Find the main client entry point (could be index or client)
// Usually in TanStack Start, client entry is the one we want, but Vite also creates routes.
// Actually, let's just include all JS files as modules? No, that might run things multiple times.
// Let's include client.js, index.js, or routes.js.
// We can just use a <script type="module" src="/assets/client-...js"> 

// Let's check which JS file is the main entry. In Vite, usually index.js or client.js.
const mainJs = jsFiles.find(f => f.startsWith('client-')) || jsFiles.find(f => f.startsWith('index-'));

let html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <link rel="icon" href="/favicon.ico" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>TenBit RAG — Enterprise Retrieval Platform</title>
  ${cssFiles.map(f => `<link rel="stylesheet" crossorigin href="/assets/${f}" />`).join('\n  ')}
</head>
<body>
  <div id="root"></div>
  <script type="module" crossorigin src="/assets/${mainJs}"></script>
</body>
</html>`;

fs.writeFileSync(path.join(staticDir, 'index.html'), html);
console.log('Created index.html with JS:', mainJs);
