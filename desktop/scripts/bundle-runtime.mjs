// Builds the Python runtime that the "full" installer carries, so the first start needs no
// download: a standalone Python 3.12 plus every locked package for the chosen PyTorch build.
//
//   node scripts/bundle-runtime.mjs            # NVIDIA (CUDA) build, the default
//   node scripts/bundle-runtime.mjs inference  # CPU build
//
// It must run on the platform being packaged: wheels are platform specific. Output:
//   resources/runtime/python           the interpreter and its standard library
//   resources/runtime/site-packages    the locked packages (not the app itself)
import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const extra = process.argv[2] ?? "cuda";
if (!["cuda", "inference"].includes(extra)) {
  console.error('The build is "cuda" or "inference".');
  process.exit(1);
}
const here = dirname(fileURLToPath(import.meta.url));
const desktop = join(here, "..");
const project = join(desktop, "..");
const windows = process.platform === "win32";
const uv = join(desktop, "resources", "bin", windows ? "uv.exe" : "uv");
if (!existsSync(uv)) {
  console.error("uv is missing. Run `npm run fetch-uv` first.");
  process.exit(1);
}

const run = (args, env = {}) => execFileSync(uv, args, { cwd: project, env: { ...process.env, ...env }, encoding: "utf8" });
const runtime = join(desktop, "resources", "runtime");
const scratch = join(desktop, "resources", ".build-env");
rmSync(runtime, { recursive: true, force: true });
rmSync(scratch, { recursive: true, force: true });
mkdirSync(runtime, { recursive: true });

console.log("Installing the standalone Python 3.12 ...");
run(["python", "install", "3.12"]);
const interpreter = run(["python", "find", "3.12", "--managed-python"]).trim();
// <prefix>/bin/python3.12 on Linux, <prefix>\python.exe on Windows.
const prefix = windows ? dirname(interpreter) : dirname(dirname(interpreter));

console.log(`Installing the locked packages (${extra}) ...`);
run(
  ["sync", "--frozen", "--extra", extra, "--no-install-project", "--python", interpreter],
  { UV_PROJECT_ENVIRONMENT: scratch },
);

console.log("Copying the runtime ...");
cpSync(prefix, join(runtime, "python"), { recursive: true, verbatimSymlinks: true });
const packages = windows
  ? join(scratch, "Lib", "site-packages")
  : join(scratch, "lib", "python3.12", "site-packages");
cpSync(packages, join(runtime, "site-packages"), { recursive: true, verbatimSymlinks: true });
rmSync(scratch, { recursive: true, force: true });
console.log(`Runtime ready in ${runtime}`);
