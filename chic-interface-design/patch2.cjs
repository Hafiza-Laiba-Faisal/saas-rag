const fs = require('fs');
const path = require('path');

const adminTsxPath = path.join(__dirname, 'src/routes/admin.tsx');
let content = fs.readFileSync(adminTsxPath, 'utf8');

// 1. Documents Tab Integration
content = content.replace(
  /function DocumentsTab\(\) \{/,
  `function DocumentsTab({ tenantId }: { tenantId?: string }) {
  const queryClient = import("@tanstack/react-query").then(m => m.useQueryClient());
  const { data: docs = [], refetch } = useQuery({
    queryKey: ["documents", tenantId],
    queryFn: async () => {
      if (!tenantId) return [];
      const res = await apiFetch(\`/tenants/\${tenantId}/documents\`);
      return res.json();
    },
    enabled: !!tenantId
  });
`
);

content = content.replace(
  /<DocumentsTab \/>/,
  `<DocumentsTab tenantId={active?.id} />`
);

// 2. Playground Tab Integration
content = content.replace(
  /function PlaygroundTab\(\) \{/,
  `function PlaygroundTab({ tenantId }: { tenantId?: string }) {
  const { data: sessions = [] } = useQuery({
    queryKey: ["sessions", tenantId],
    queryFn: async () => {
      if (!tenantId) return [];
      const res = await apiFetch(\`/tenants/\${tenantId}/sessions\`);
      const data = await res.json();
      return data.sessions || [];
    },
    enabled: !!tenantId
  });
`
);

content = content.replace(
  /<PlaygroundTab \/>/,
  `<PlaygroundTab tenantId={active?.id} />`
);

fs.writeFileSync(adminTsxPath, content);
console.log("Documents & Playground integrated!");
