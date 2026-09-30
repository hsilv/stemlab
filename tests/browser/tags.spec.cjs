const { test, expect } = require("@playwright/test");
const path = require("path");

const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

function synchsafe(n) {
  return [(n >> 21) & 0x7f, (n >> 14) & 0x7f, (n >> 7) & 0x7f, n & 0x7f];
}

function textFrame(id, value) {
  const body = [3, ...Buffer.from(value)];
  return Buffer.concat([
    Buffer.from(id),
    Buffer.from([(body.length >> 24) & 255, (body.length >> 16) & 255, (body.length >> 8) & 255, body.length & 255]),
    Buffer.from([0, 0]),
    Buffer.from(body),
  ]);
}

function apicFrame() {
  const body = Buffer.concat([
    Buffer.from([0]),
    Buffer.from("image/png\0"),
    Buffer.from([3]),
    Buffer.from("\0"),
    png,
  ]);
  return Buffer.concat([
    Buffer.from("APIC"),
    Buffer.from([(body.length >> 24) & 255, (body.length >> 16) & 255, (body.length >> 8) & 255, body.length & 255]),
    Buffer.from([0, 0]),
    body,
  ]);
}

function id3(frames) {
  const body = Buffer.concat(frames);
  return Buffer.concat([Buffer.from("ID3"), Buffer.from([3, 0, 0]), Buffer.from(synchsafe(body.length)), body]);
}

test.beforeEach(async ({ page }) => {
  await page.goto("about:blank");
  await page.addScriptTag({
    path: path.join(__dirname, "../../frontend/src/lib/tags.js"),
    type: "module",
  });
  await page.waitForFunction(() => window.readTags);
});

test("reads ID3 title, artist, album, genre, year, and cover", async ({ page }) => {
  const bytes = id3([
    textFrame("TIT2", "Mirama"),
    textFrame("TPE1", "Daddy Yankee"),
    textFrame("TALB", "Barrio Fino"),
    textFrame("TCON", "(17)"),
    textFrame("TDRC", "2004-07-13"),
    apicFrame(),
  ]);
  const tags = await page.evaluate(async (list) => {
    const tags = await readTags(new File([new Uint8Array(list)], "a.mp3"));
    const cover = tags.coverUrl ? (await fetch(tags.coverUrl)).headers.get("content-type") : "";
    return { ...tags, cover };
  }, [...bytes]);
  expect(tags).toMatchObject({
    title: "Mirama",
    artist: "Daddy Yankee",
    album: "Barrio Fino",
    genre: "Rock",
    year: "2004",
    cover: "image/png",
  });
  expect(tags.coverUrl).toMatch(/^blob:/);
});

test("reads a WAV info list when there is no ID3 tag", async ({ page }) => {
  const u32 = (n) => [n & 255, (n >> 8) & 255, (n >> 16) & 255, (n >> 24) & 255];
  const tag = (s) => [...s].map((c) => c.charCodeAt(0));
  const info = (id, value) => {
    const body = [...tag(value), 0];
    return [...tag(id), ...u32(body.length), ...body, ...(body.length & 1 ? [0] : [])];
  };
  const list = [...tag("INFO"), ...info("INAM", "Night"), ...info("IART", "Ada"), ...info("IGNR", "Jazz")];
  const chunk = [...tag("LIST"), ...u32(list.length), ...list];
  const body = [...tag("WAVE"), ...chunk];
  const bytes = [...tag("RIFF"), ...u32(body.length), ...body];
  const tags = await page.evaluate(async (list) => readTags(new File([new Uint8Array(list)], "a.wav")), bytes);
  expect(tags).toMatchObject({ title: "Night", artist: "Ada", genre: "Jazz", coverUrl: "" });
});

test("a file without tags reports nothing", async ({ page }) => {
  const tags = await page.evaluate(() => readTags(new File([new Uint8Array(16)], "a.mp3")));
  expect(tags).toEqual({
    title: "",
    artist: "",
    album: "",
    genre: "",
    year: "",
    coverUrl: "",
  });
});

test("the load step shows tags from the chosen file", async ({ page }) => {
  const bytes = id3([
    textFrame("TIT2", "Mirama"),
    textFrame("TPE1", "Daddy Yankee"),
    textFrame("TALB", "Barrio Fino"),
    textFrame("TCON", "Reggaeton"),
    textFrame("TYER", "2004"),
    apicFrame(),
  ]);
  await page.goto("/");
  await page.setInputFiles("#file", { name: "mirama.mp3", mimeType: "audio/mpeg", buffer: bytes });
  await expect(page.getByRole("region", { name: "Track details" })).toBeVisible();
  await expect(page.getByRole("img", { name: "Album cover" })).toBeVisible();
  await expect(page.locator(".tags")).toContainText("Mirama");
  await expect(page.locator(".tags")).toContainText("Daddy Yankee");
  await expect(page.locator(".tags")).toContainText("Barrio Fino");
  await expect(page.locator(".tags")).toContainText("Reggaeton");
  await expect(page.locator(".tags")).toContainText("2004");
});
