const fs = require('fs');
const path = require('path');

const adminTsxPath = path.join(__dirname, 'src/routes/admin.tsx');
let content = fs.readFileSync(adminTsxPath, 'utf8');

// 1. Add Console tab to tabs list
if (!content.includes('{ id: "console"')) {
    content = content.replace(
        /\{ id: "integration", label: "Integration API", icon: Code2 \},/,
        `{ id: "integration", label: "Integration API", icon: Code2 },
  { id: "console", label: "Console Terminal", icon: Webhook },`
    );
}

// 2. Add ConsoleTab to rendering logic
if (!content.includes('tab === "console"')) {
    content = content.replace(
        /\{tab === "integration" && <IntegrationTab tenantId=\{active\.id\} \/>\}/,
        `{tab === "integration" && <IntegrationTab tenantId={active.id} />}
              {tab === "console" && <ConsoleTab tenant={active} />}`
    );
}

// 3. Add ConsoleTab component definition
if (!content.includes('function ConsoleTab')) {
    content += `\n\n
import { useEffect, useRef } from "react";
import { Terminal } from "xterm";
import { FitAddon } from "@xterm/addon-fit";
import "xterm/css/xterm.css";

function ConsoleTab({ tenant }: { tenant: Tenant }) {
  const terminalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!terminalRef.current) return;
    
    const term = new Terminal({
      theme: { background: "#0c0a09" },
      fontFamily: "JetBrains Mono, monospace",
      fontSize: 13,
      cursorBlink: true,
    });
    
    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    
    term.open(terminalRef.current);
    fitAddon.fit();

    term.writeln(\`Connected to \${tenant.name} console.\`);
    term.writeln("Terminal ready.");
    term.write("$ ");
    
    // Resize handler
    const resizeObserver = new ResizeObserver(() => fitAddon.fit());
    resizeObserver.observe(terminalRef.current);

    return () => {
      resizeObserver.disconnect();
      term.dispose();
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
`;
}

// 4. Update the Tenant type
content = content.replace(
    /tier: "Starter" \| "Growth" \| "Premium" \| "Enterprise";/,
    `tier: "Starter" | "Growth" | "Premium" | "Enterprise" | "basic" | "premium";`
);

fs.writeFileSync(adminTsxPath, content);
console.log("admin.tsx patched successfully!");
