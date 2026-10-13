// Puts the uv executable for this build machine's platform in resources/bin, where the packaged
// app finds it. uv creates the Python environment on the user's first start.
import { createWriteStream, existsSync, mkdirSync, rmSync, chmodSync, renameSync, readdirSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { pipeline } from "node:stream/promises";

const VERSION = "0.8.22"; // the version the lock file was made with (see .github/workflows/ci.yml)
const TARGETS = {
  "linux-x64": ["x86_64-unknown-linux-gnu", "tar.gz", "uv"],
  "linux-arm64": ["aarch64-unknown-linux-gnu", "tar.gz", "uv"],
  "win32-x64": ["x86_64-pc-windows-msvc", "zip", "uv.exe"],
};

const key = `${process.platform}-${process.arch}`;
const target = TARGETS[key];
if (!target) {
  console.error(`No uv build is listed for ${key}.`);
  process.exit(1);
}
const [triple, archive, binary] = target;
const here = dirname(fileURLToPath(import.meta.url));
const bin = join(here, "..", "resources", "bin");
mkdirSync(bin, { recursive: true });
if (existsSync(join(bin, binary))) {
  console.log(`uv already in ${bin}`);
  process.exit(0);
}

const url = `https://github.com/astral-sh/uv/releases/download/${VERSION}/uv-${triple}.${archive}`;
const file = join(bin, `uv.${archive}`);
console.log(`Downloading ${url}`);
const response = await fetch(url);
if (!response.ok) throw new Error(`Download failed: ${response.status}`);
await pipeline(response.body, createWriteStream(file));

const unpacked = join(bin, "unpacked");
mkdirSync(unpacked, { recursive: true });
if (archive === "zip") {
  execFileSync("tar", ["-xf", file, "-C", unpacked]); // bsdtar ships with Windows 10 and later
} else {
  execFileSync("tar", ["-xzf", file, "-C", unpacked]);
}
const found = readdirSync(unpacked, { recursive: true }).find((name) => name.endsWith(binary));
if (!found) throw new Error(`${binary} not found in the download.`);
renameSync(join(unpacked, found), join(bin, binary));
if (process.platform !== "win32") chmodSync(join(bin, binary), 0o755);
rmSync(unpacked, { recursive: true, force: true });
rmSync(file);
console.log(`uv ${VERSION} ready in ${bin}`);
