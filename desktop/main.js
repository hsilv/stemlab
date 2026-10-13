// StemLab desktop shell: runs the local server and shows its page in a window. The interface is
// the same Svelte app the browser gets; nothing here touches audio.
const { app, BrowserWindow, dialog, ipcMain, shell } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const backend = require("./backend.js");

// An AppImage cannot ship the setuid sandbox helper, and some distributions (Ubuntu 23.10 and
// later) refuse the unprivileged alternative, so the window would not open. The window only
// shows this program's own local page.
if (process.env.APPIMAGE) app.commandLine.appendSwitch("no-sandbox");

const packaged = app.isPackaged;
// Packaged: the app's files sit in resources/app. From a checkout: the repository root.
const appRoot = packaged ? path.join(process.resourcesPath, "app") : path.join(__dirname, "..");
const toolsDir = packaged ? path.join(process.resourcesPath, "bin") : path.join(__dirname, "resources", "bin");
// The full installer carries its own Python and packages; the small one builds an environment on
// first start.
const runtime = packaged ? backend.bundledRuntime(process.resourcesPath) : null;
const userData = app.getPath("userData");
const envDir = process.env.STEMLAB_ENV_DIR || (packaged ? path.join(userData, "venv") : path.join(appRoot, ".venv"));
const dataDir = process.env.STEMLAB_DATA_DIR || path.join(userData, "data");
const stampFile = path.join(userData, "environment.json");

let child = null;
let port = 0;
let quitting = false;
let starting = true;
let window = null;

function uvPath() {
  const name = process.platform === "win32" ? "uv.exe" : "uv";
  const bundled = path.join(toolsDir, name);
  return fs.existsSync(bundled) ? bundled : name;
}

function environmentReady() {
  const python = backend.venvPython(envDir);
  if (!fs.existsSync(python)) return false;
  // From a checkout the environment is the developer's own; it is never rebuilt from here.
  if (!packaged) return true;
  try {
    const stamp = JSON.parse(fs.readFileSync(stampFile, "utf8"));
    return stamp.version === app.getVersion() && stamp.appRoot === appRoot;
  } catch {
    return false;
  }
}

function showSetup() {
  const setup = new BrowserWindow({
    width: 640,
    height: 420,
    title: "StemLab: first start",
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true },
  });
  setup.setMenuBarVisibility(false);
  setup.loadFile(path.join(__dirname, "setup.html"));
  return setup;
}

// Creates the Python environment (a few GB the first time) and reports what uv prints. uv also
// provides the Python that runs the script, so nothing needs to be installed beforehand.
function runBootstrap(report) {
  return new Promise((resolve, reject) => {
    const script = path.join(appRoot, "scripts", "bootstrap.py");
    const args = [
      "run", "--no-project", "--python", "3.12", script,
      "--project", appRoot, "--env", envDir, "--uv", uvPath(),
    ];
    const run = spawn(uvPath(), args, {
      env: { ...process.env, PATH: [toolsDir, process.env.PATH ?? ""].join(path.delimiter) },
      windowsHide: true,
    });
    run.stdout.on("data", (chunk) => report(chunk.toString()));
    run.stderr.on("data", (chunk) => report(chunk.toString()));
    run.on("error", reject);
    run.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`Setup failed (exit code ${code}).`))));
  });
}

async function ensureEnvironment() {
  if (runtime || environmentReady()) return;
  const setup = showSetup();
  const report = (text) => setup.webContents.send("setup-log", text);
  await new Promise((resolve) => setup.webContents.once("did-finish-load", resolve));
  try {
    await runBootstrap(report);
  } catch (error) {
    report(`\n${error.message}\n`);
    await dialog.showMessageBox(setup, {
      type: "error",
      title: "StemLab",
      message: "StemLab could not finish its first-time setup.",
      detail: `${error.message}\nCheck your internet connection and start the app again.`,
    });
    app.exit(1);
    return;
  }
  fs.mkdirSync(userData, { recursive: true });
  fs.writeFileSync(stampFile, JSON.stringify({ version: app.getVersion(), appRoot }));
  setup.close();
}

async function openWindow() {
  window = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: "#0b0c0e",
    title: "StemLab",
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  window.setMenuBarVisibility(false);
  const origin = `http://127.0.0.1:${port}`;
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (!url.startsWith(origin)) shell.openExternal(url);
    return { action: "deny" };
  });
  window.webContents.on("will-navigate", (event, url) => {
    if (!url.startsWith(origin)) {
      event.preventDefault();
      shell.openExternal(url);
    }
  });
  await window.loadURL(origin);
}

async function start() {
  await ensureEnvironment();
  port = await backend.freePort();
  const env = backend.backendEnv({
    dataDir,
    port,
    toolsDir,
    pythonPath: runtime ? [runtime.sitePackages, path.join(appRoot, "src")] : [],
  });
  fs.mkdirSync(dataDir, { recursive: true });
  child = backend.startBackend({
    python: runtime ? runtime.python : backend.venvPython(envDir),
    env,
    cwd: dataDir,
    log: (text) => process.stdout.write(text),
  });
  try {
    await backend.waitUntilReady(port, { child });
  } catch (error) {
    await dialog.showMessageBox({
      type: "error",
      title: "StemLab",
      message: "StemLab could not start.",
      detail: error.message,
    });
    app.exit(1);
    return;
  }
  await openWindow();
  starting = false;
}

app.on("before-quit", async (event) => {
  if (quitting || !child) return;
  event.preventDefault();
  const active = await backend.activeJobs(port);
  if (active > 0) {
    const { response } = await dialog.showMessageBox(window ?? undefined, {
      type: "question",
      buttons: ["Keep working", "Quit anyway"],
      defaultId: 0,
      cancelId: 0,
      title: "StemLab",
      message: `${active} job${active === 1 ? " is" : "s are"} still waiting or running.`,
      detail: "Waiting jobs continue next time. A running job stops and can be retried.",
    });
    if (response === 0) return;
  }
  quitting = true;
  await backend.stopBackend(child);
  app.quit();
});

// Closing the setup window must not quit: the main window opens right after it.
app.on("window-all-closed", () => {
  if (!starting) app.quit();
});

// A terminal's Ctrl+C or a system shutdown: stop the server, no questions asked.
for (const name of ["SIGINT", "SIGTERM"]) {
  process.on(name, async () => {
    quitting = true;
    await backend.stopBackend(child);
    app.exit(0);
  });
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (window) {
      if (window.isMinimized()) window.restore();
      window.focus();
    }
  });
  ipcMain.handle("app-version", () => app.getVersion());
  app.whenReady().then(start);
}
