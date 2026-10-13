// Starts the real server from the repository's own environment, so it needs `.venv` made by
// scripts/bootstrap.py. It uses a temporary data folder and a free port.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const backend = require("../backend.js");

const python = backend.venvPython(path.join(__dirname, "..", "..", ".venv"));

function get(url) {
  return new Promise((resolve, reject) => {
    http
      .get(url, (response) => {
        let body = "";
        response.on("data", (chunk) => (body += chunk));
        response.on("end", () => resolve({ status: response.statusCode, body }));
      })
      .on("error", reject);
  });
}

test("the server starts, answers and stops", { skip: !fs.existsSync(python) }, async () => {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "stemlab-shell-"));
  const port = await backend.freePort();
  const child = backend.startBackend({
    python,
    env: backend.backendEnv({ dataDir, port }),
    cwd: dataDir,
  });
  try {
    await backend.waitUntilReady(port, { child, timeoutMs: 60000 });
    const config = await get(`http://127.0.0.1:${port}/api/config`);
    assert.equal(config.status, 200);
    assert.deepEqual(JSON.parse(config.body).input_formats, ["wav", "mp3", "flac"]);
    assert.equal(await backend.activeJobs(port), 0);
  } finally {
    await backend.stopBackend(child);
  }
  assert.notEqual(child.exitCode, null);
  await assert.rejects(get(`http://127.0.0.1:${port}/health/live`));
  assert.ok(fs.existsSync(path.join(dataDir, "jobs.sqlite3")));
});
