import { spawn, spawnSync } from "node:child_process";
import http from "node:http";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const viteCli = path.join(frontendDir, "node_modules", "vite", "bin", "vite.js");
const playwrightCli = path.join(frontendDir, "node_modules", "playwright", "cli.js");

function reserveFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") {
        server.close(() => reject(new Error("Could not allocate a visual-audit port.")));
        return;
      }
      server.close((error) => (error ? reject(error) : resolve(address.port)));
    });
  });
}

function stopProcessTree(child) {
  if (!child.pid || child.exitCode !== null) return;
  if (process.platform === "win32") {
    spawnSync("taskkill", ["/pid", String(child.pid), "/t", "/f"], {
      stdio: "ignore",
      windowsHide: true,
    });
    return;
  }
  child.kill("SIGTERM");
}

function waitForServer(child, auditUrl, timeoutMs = 60_000) {
  const startedAt = Date.now();
  return new Promise((resolve, reject) => {
    const tryRequest = () => {
      if (child.exitCode !== null) {
        reject(new Error(`Synthetic visual-audit server exited with code ${child.exitCode}.`));
        return;
      }
      const request = http.get(auditUrl, (response) => {
        response.resume();
        if ((response.statusCode ?? 500) < 500) {
          resolve();
          return;
        }
        setTimeout(tryRequest, 200);
      });
      request.on("error", () => {
        if (Date.now() - startedAt >= timeoutMs) {
          reject(new Error("Synthetic visual-audit server did not become ready in time."));
          return;
        }
        setTimeout(tryRequest, 200);
      });
    };
    tryRequest();
  });
}

const auditPort = await reserveFreePort();
const auditUrl = `http://127.0.0.1:${auditPort}`;
const vite = spawn(
  process.execPath,
  [viteCli, "--host", "127.0.0.1", "--port", String(auditPort), "--strictPort"],
  {
    cwd: frontendDir,
    stdio: ["ignore", "ignore", "inherit"],
    windowsHide: true,
  },
);

const stop = () => stopProcessTree(vite);
process.once("SIGINT", () => {
  stop();
  process.exitCode = 130;
});
process.once("SIGTERM", () => {
  stop();
  process.exitCode = 143;
});

let exitCode = 1;
try {
  await waitForServer(vite, auditUrl);
  const playwright = spawn(
    process.execPath,
    [playwrightCli, "test", "--config", "playwright.visual.config.ts", ...process.argv.slice(2)],
    {
      cwd: frontendDir,
      env: { ...process.env, HERMES_VISUAL_AUDIT_BASE_URL: auditUrl },
      stdio: "inherit",
      windowsHide: true,
    },
  );
  exitCode = await new Promise((resolve) => {
    playwright.once("exit", (code) => resolve(code ?? 1));
  });
} finally {
  stop();
}

process.exit(exitCode);
