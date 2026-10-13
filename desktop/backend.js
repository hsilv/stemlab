// Starting, waiting for and stopping the local StemLab server. No Electron in here, so it can be
// tested with plain Node.
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const path = require("node:path");

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

// The interpreter of a virtual environment folder.
function venvPython(envDir, platform = process.platform) {
  return platform === "win32"
    ? path.join(envDir, "Scripts", "python.exe")
    : path.join(envDir, "bin", "python");
}

// The Python the "full" installer carries: its interpreter and the packages beside it. null when
// this build has none (the first start then creates an environment instead).
function bundledRuntime(resourcesDir, platform = process.platform) {
  const root = path.join(resourcesDir, "runtime");
  const names = platform === "win32" ? ["python.exe"] : [path.join("bin", "python3"), path.join("bin", "python")];
  const python = names.map((name) => path.join(root, "python", name)).find((file) => fs.existsSync(file));
  const sitePackages = path.join(root, "site-packages");
  return python && fs.existsSync(sitePackages) ? { python, sitePackages } : null;
}

// What the server needs to know: where its data lives, which port, the bundled tools (ffmpeg,
// ffprobe) ahead of anything on PATH, and, for a bundled runtime, where its packages are.
function backendEnv({
  dataDir,
  port,
  toolsDir,
  pythonPath = [],
  base = process.env,
  platform = process.platform,
}) {
  const delimiter = platform === "win32" ? ";" : ":";
  const env = {
    ...base,
    STEMLAB_DATA_DIR: dataDir,
    STEMLAB_PORT: String(port),
    TORCH_HOME: path.join(dataDir, "models"),
    PYTHONUNBUFFERED: "1",
    STEMLAB_EXIT_WITH_PARENT: "1",
  };
  if (toolsDir && fs.existsSync(toolsDir)) {
    env.PATH = [toolsDir, base.PATH ?? ""].filter(Boolean).join(delimiter);
  }
  if (pythonPath.length) {
    env.PYTHONPATH = [...pythonPath, base.PYTHONPATH ?? ""].filter(Boolean).join(delimiter);
  }
  return env;
}

function startBackend({ python, env, cwd, log }) {
  fs.mkdirSync(cwd, { recursive: true });
  const child = spawn(python, ["-m", "stemlab.local"], {
    cwd,
    env,
    // stdin stays open: when this program goes away the server sees it close and stops too.
    stdio: ["pipe", "pipe", "pipe"],
    windowsHide: true,
  });
  child.stdout.on("data", (chunk) => log?.(chunk.toString()));
  child.stderr.on("data", (chunk) => log?.(chunk.toString()));
  return child;
}

function ping(url) {
  return new Promise((resolve) => {
    const request = http.get(url, (response) => {
      response.resume();
      resolve(response.statusCode === 200);
    });
    request.on("error", () => resolve(false));
    request.setTimeout(1500, () => {
      request.destroy();
      resolve(false);
    });
  });
}

// Resolves when the server answers, rejects when it exits first or the time runs out.
async function waitUntilReady(port, { child, timeoutMs = 120000, intervalMs = 300 } = {}) {
  const url = `http://127.0.0.1:${port}/health/live`;
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (child && child.exitCode !== null) {
      throw new Error(`The StemLab server stopped (exit code ${child.exitCode}).`);
    }
    if (await ping(url)) return;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error("The StemLab server did not start in time.");
}

// Ask it to stop (the launcher stops its worker and API), then make sure.
function stopBackend(child, { graceMs = 20000 } = {}) {
  return new Promise((resolve) => {
    if (!child || child.exitCode !== null) return resolve();
    const timer = setTimeout(() => child.kill("SIGKILL"), graceMs);
    child.once("exit", () => {
      clearTimeout(timer);
      resolve();
    });
    child.kill("SIGTERM");
  });
}

// Jobs that would be interrupted by quitting: running ones become retryable on the next start.
async function activeJobs(port) {
  return new Promise((resolve) => {
    http
      .get(`http://127.0.0.1:${port}/api/jobs`, (response) => {
        let body = "";
        response.on("data", (chunk) => (body += chunk));
        response.on("end", () => {
          try {
            const rows = JSON.parse(body);
            resolve(rows.filter((row) => ["queued", "running", "cancelling"].includes(row.status)).length);
          } catch {
            resolve(0);
          }
        });
      })
      .on("error", () => resolve(0));
  });
}

module.exports = {
  activeJobs,
  backendEnv,
  bundledRuntime,
  freePort,
  startBackend,
  stopBackend,
  venvPython,
  waitUntilReady,
};
