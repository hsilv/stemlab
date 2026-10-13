// Copies the build into the Python package, which serves it. Plain Node so it also runs on Windows.
import { cpSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const dist = join(here, "..", "dist");
const target = join(here, "..", "..", "src", "stemlab", "web", "ui");

rmSync(target, { recursive: true, force: true });
mkdirSync(dirname(target), { recursive: true });
cpSync(dist, target, { recursive: true });
console.log(`Interface copied to ${target}`);
