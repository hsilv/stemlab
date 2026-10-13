const { test, expect } = require("@playwright/test");
const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

// Needs ffmpeg and ffprobe on the machine running the tests, like the feature itself.

function make(folder, name, args) {
  const file = path.join(folder, name);
  execFileSync("ffmpeg", ["-nostdin", "-v", "error", "-y", ...args, file]);
  return file;
}

test("the Tags booth copies a song's tags and cover onto another file", async ({ page }) => {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), "stemlab-tags-"));
  const cover = make(folder, "cover.png", ["-f", "lavfi", "-i", "color=c=red:s=16x16:d=1", "-frames:v", "1"]);
  const song = make(folder, "song.mp3", [
    "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-i", cover,
    "-map", "0:a", "-map", "1:v", "-c:a", "libmp3lame", "-c:v", "copy", "-id3v2_version", "3",
    "-metadata", "title=Gasolina", "-metadata", "artist=Daddy Yankee",
    "-metadata", "album=Barrio Fino", "-disposition:v", "attached_pic",
  ]);
  const plain = make(folder, "plain.flac", ["-f", "lavfi", "-i", "sine=frequency=220:duration=2", "-c:a", "flac"]);

  const name = `Gasolina-${Date.now()}.mp3`;
  const created = await page.request.post(`/api/jobs?filename=${name}&bpm=120&downbeat=0`, {
    data: fs.readFileSync(song),
    headers: { "Content-Type": "audio/mpeg" },
  });
  expect(created.ok()).toBeTruthy();
  await page.goto("/");
  await page.locator("#booth-tags").click();

  // The source is the crate's original upload, and shows what it carries.
  const source = page.locator("#tags-source");
  await expect(source).toContainText("Gasolina");
  await expect(source).toContainText("Daddy Yankee");
  await expect(source.locator("img.cover")).toBeVisible();

  // The target is a file with no extension in its name worth trusting.
  const target = page.locator("#tags-target");
  await target.getByRole("button", { name: "A file I choose" }).click();
  await page.setInputFiles("#target-file", plain);
  await expect(target).toContainText("No tags or cover");
  await expect(page.locator("#copy-tags")).toBeEnabled();

  await page.locator("#tag-version").fill("Instrumental");
  await expect(page.locator("#tag-title")).toContainText("Gasolina (Instrumental)");

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.locator("#copy-tags").click(),
  ]);
  const saved = path.join(folder, "result.flac");
  await download.saveAs(saved);
  const shown = JSON.parse(
    execFileSync("ffprobe", ["-v", "error", "-print_format", "json", "-show_entries", "format_tags:stream=codec_type", saved]),
  );
  expect(shown.format.tags.title ?? shown.format.tags.TITLE).toBe("Gasolina (Instrumental)");
  expect((shown.format.tags.artist ?? shown.format.tags.ARTIST)).toBe("Daddy Yankee");
  expect(shown.streams.some((stream) => stream.codec_type === "video")).toBe(true);
  await expect(page.locator("#page-tags")).toContainText("Saved");
  await page.screenshot({ path: "test-results/tags-booth.png", fullPage: true });

  // The same file on both sides is refused with a reason.
  await target.getByRole("button", { name: "A song in the crate" }).click();
  await expect(page.locator("#page-tags")).toContainText("same file");
  await expect(page.locator("#copy-tags")).toBeDisabled();
});
