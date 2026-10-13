// Puts ffmpeg and ffprobe for this build machine's platform in resources/bin, where the packaged
// app puts them on the server's PATH. MP3 export and the Tags booth use them.
//
// These are BtbN's "lgpl" builds (they include libmp3lame, which is LGPL). Ship the license text
// that comes with them with your installer, and read https://ffmpeg.org/legal.html.
import { chmodSync, copyFileSync, existsSync, mkdirSync, readdirSync, rmSync, createWriteStream } from "node:fs";
import { execFileSync } from "node:child_process";
import { dirname, join, basename } from "node:path";
import { fileURLToPath } from "node:url";
import { pipeline } from "node:stream/promises";

const BASE = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest";
const TARGETS = {
  "linux-x64": ["ffmpeg-master-latest-linux64-lgpl.tar.xz", ["ffmpeg", "ffprobe"]],
  "win32-x64": ["ffmpeg-master-latest-win64-lgpl.zip", ["ffmpeg.exe", "ffprobe.exe"]],
};

const target = TARGETS[`${process.platform}-${process.arch}`];
if (!target) {
  console.error(`No ffmpeg build is listed for ${process.platform}-${process.arch}.`);
  process.exit(1);
}
const [archive, binaries] = target;
const here = dirname(fileURLToPath(import.meta.url));
const bin = join(here, "..", "resources", "bin");
mkdirSync(bin, { recursive: true });
if (binaries.every((name) => existsSync(join(bin, name)))) {
  console.log(`ffmpeg already in ${bin}`);
  process.exit(0);
}

const file = join(bin, archive);
console.log(`Downloading ${BASE}/${archive}`);
const response = await fetch(`${BASE}/${archive}`);
if (!response.ok) throw new Error(`Download failed: ${response.status}`);
await pipeline(response.body, createWriteStream(file));

const unpacked = join(bin, "ffmpeg-unpacked");
mkdirSync(unpacked, { recursive: true });
execFileSync("tar", [archive.endsWith(".zip") ? "-xf" : "-xJf", file, "-C", unpacked]);
const all = readdirSync(unpacked, { recursive: true });
for (const name of binaries) {
  const found = all.find((entry) => basename(entry) === name);
  if (!found) throw new Error(`${name} not found in the download.`);
  copyFileSync(join(unpacked, found), join(bin, name));
  if (process.platform !== "win32") chmodSync(join(bin, name), 0o755);
}
const license = all.find((entry) => basename(entry).toUpperCase().startsWith("LICENSE"));
if (license) copyFileSync(join(unpacked, license), join(bin, "ffmpeg-LICENSE.txt"));
rmSync(unpacked, { recursive: true, force: true });
rmSync(file);
console.log(`ffmpeg ready in ${bin}`);
