const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const backend = require("../backend.js");

test("venvPython follows the platform", () => {
  assert.equal(backend.venvPython("/e", "linux"), path.join("/e", "bin", "python"));
  assert.equal(backend.venvPython("C:\\e", "win32"), path.join("C:\\e", "Scripts", "python.exe"));
});

test("backendEnv points the server at its own data and the bundled tools", () => {
  const tools = fs.mkdtempSync(path.join(os.tmpdir(), "tools-"));
  const env = backend.backendEnv({
    dataDir: "/d",
    port: 4321,
    toolsDir: tools,
    base: { PATH: "/usr/bin" },
    platform: "linux",
  });
  assert.equal(env.STEMLAB_DATA_DIR, "/d");
  assert.equal(env.STEMLAB_PORT, "4321");
  assert.equal(env.TORCH_HOME, path.join("/d", "models"));
  assert.equal(env.PATH, `${tools}:/usr/bin`);
  const without = backend.backendEnv({ dataDir: "/d", port: 1, toolsDir: "/nope", base: { PATH: "/usr/bin" } });
  assert.equal(without.PATH, "/usr/bin");
});

test("freePort gives a port nobody is using", async () => {
  const port = await backend.freePort();
  assert.ok(port > 1024 && port < 65536);
});

test("waitUntilReady fails fast when the server exits first", async () => {
  const fake = { exitCode: 3 };
  await assert.rejects(backend.waitUntilReady(await backend.freePort(), { child: fake }), /exit code 3/);
});

test("waitUntilReady gives up after the time limit", async () => {
  await assert.rejects(
    backend.waitUntilReady(await backend.freePort(), { timeoutMs: 400, intervalMs: 100 }),
    /did not start in time/,
  );
});

test("bundledRuntime finds the interpreter and the packages, or says there are none", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "res-"));
  assert.equal(backend.bundledRuntime(root, "linux"), null);
  fs.mkdirSync(path.join(root, "runtime", "python", "bin"), { recursive: true });
  fs.mkdirSync(path.join(root, "runtime", "site-packages"), { recursive: true });
  assert.equal(backend.bundledRuntime(root, "linux"), null);
  const python = path.join(root, "runtime", "python", "bin", "python3");
  fs.writeFileSync(python, "");
  assert.deepEqual(backend.bundledRuntime(root, "linux"), {
    python,
    sitePackages: path.join(root, "runtime", "site-packages"),
  });
});

test("backendEnv puts the bundled packages on PYTHONPATH", () => {
  const env = backend.backendEnv({
    dataDir: "/d",
    port: 1,
    pythonPath: ["/r/site-packages", "/r/app/src"],
    base: { PATH: "/usr/bin" },
    platform: "linux",
  });
  assert.equal(env.PYTHONPATH, "/r/site-packages:/r/app/src");
});
