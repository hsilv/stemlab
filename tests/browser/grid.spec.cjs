const { test, expect } = require("@playwright/test");

const RATE = 22050;
const SECONDS = 12;

function u32(n) {
  const bytes = Buffer.alloc(4);
  bytes.writeUInt32LE(n >>> 0);
  return bytes;
}

function chunk(id, body) {
  const pad = body.length & 1 ? Buffer.alloc(1) : Buffer.alloc(0);
  return Buffer.concat([Buffer.from(id), u32(body.length), body, pad]);
}

function gridWav() {
  const frames = RATE * SECONDS;
  const pcm = Buffer.alloc(frames * 2);
  const notes = [57, 60, 64, 69, 72, 76];
  const beat = 60 / 120;
  const fade = Math.round(0.01 * RATE);
  for (let i = 0; i < frames; i++) {
    const t = i / RATE;
    let sample = 0;
    for (const midi of notes) {
      const freq = 440 * 2 ** ((midi - 69) / 12);
      sample += Math.sin(2 * Math.PI * freq * t);
    }
    sample *= 0.5 / notes.length;
    if (i < fade) sample *= i / fade;
    if (i >= frames - fade) sample *= (frames - 1 - i) / fade;
    const nearest = Math.round(t / beat) * beat;
    if (i === Math.round(nearest * RATE)) sample += 0.8;
    const value = Math.max(-32767, Math.min(32767, Math.round(sample * 32767)));
    pcm.writeInt16LE(value, i * 2);
  }
  const fmt = Buffer.alloc(16);
  fmt.writeUInt16LE(1, 0);
  fmt.writeUInt16LE(1, 2);
  fmt.writeUInt32LE(RATE, 4);
  fmt.writeUInt32LE(RATE * 2, 8);
  fmt.writeUInt16LE(2, 12);
  fmt.writeUInt16LE(16, 14);
  const point = (id, at) => {
    const body = Buffer.alloc(24);
    body.writeUInt32LE(id, 0);
    body.writeUInt32LE(at, 4);
    body.write("data", 8);
    body.writeUInt32LE(at, 20);
    return body;
  };
  const label = (id, text) => chunk("labl", Buffer.concat([u32(id), Buffer.from(`${text}\0`)]));
  const body = Buffer.concat([
    Buffer.from("WAVE"),
    chunk("fmt ", fmt),
    chunk("data", pcm),
    chunk("cue ", Buffer.concat([u32(2), point(1, RATE * 4), point(2, RATE * 8)])),
    chunk("LIST", Buffer.concat([Buffer.from("adtl"), label(1, "Intro"), label(2, "Drop")])),
  ]);
  return Buffer.concat([Buffer.from("RIFF"), u32(body.length), body]);
}

function snap(time, bpm, downbeat) {
  const bar = (60 / bpm) * 4;
  return downbeat + Math.round((time - downbeat) / bar) * bar;
}

test("load waits for the grid, then ranges snap to the bar", async ({ page }) => {
  await page.goto("/");
  const started = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" && response.url().includes("/api/analyses?"),
  );
  await page.setInputFiles("#file", {
    name: "grid.wav",
    mimeType: "audio/wav",
    buffer: gridWav(),
  });
  const created = await started;
  expect(created.status()).toBe(202);
  const stems = page.getByRole("button", { name: "Choose stems" });
  if ((await page.locator("#reading").count()) === 0) {
    await expect(stems).toBeDisabled();
    await expect(page.locator("#analysis-stage")).toBeVisible();
  }
  await expect(page.locator("#reading")).toContainText("8A · A minor", { timeout: 60000 });
  await expect(stems).toBeEnabled();
  await expect(page.locator("#analysis-stage")).toHaveCount(0);
  await expect(page.locator("#analysis-warning")).toHaveCount(0);

  const bpm = Number((await page.locator("#reading").innerText()).match(/([\d.]+) BPM/)[1]);
  expect(Math.abs(bpm - 120)).toBeLessThanOrEqual(0.02);

  const audio = page.locator("#deck-audio");
  await page.locator("#deck-play").click();
  await expect.poll(() => audio.evaluate((node) => node.currentTime)).toBeGreaterThan(0.05);
  await page.locator("#deck-play").click();
  await expect.poll(() => audio.evaluate((node) => node.paused)).toBe(true);

  const detail = page.locator("#page-load .deck-detail");
  let box = await detail.boundingBox();
  await detail.click({ position: { x: box.width * 0.5, y: box.height * 0.5 } });
  await expect.poll(() => audio.evaluate((node) => node.currentTime)).toBeGreaterThan(4);

  const overview = page.locator("#page-load .deck-overview");
  const wide = await overview.boundingBox();
  await overview.click({ position: { x: wide.width * 0.08, y: wide.height * 0.5 } });
  await expect.poll(() => audio.evaluate((node) => node.currentTime)).toBeLessThan(2);

  const parked = await audio.evaluate((node) => node.currentTime);
  box = await detail.boundingBox();
  await page.locator("#set-downbeat").click();
  await expect(detail).toHaveAttribute("aria-label", "Set the downbeat");
  await detail.click({ position: { x: box.width * (0.75 / SECONDS), y: box.height * 0.5 } });
  await expect(detail).toHaveAttribute("aria-label", "Waveform detail");
  await expect
    .poll(() => audio.evaluate((node, at) => Math.abs(node.currentTime - at), parked))
    .toBeLessThan(0.05);
  const nudged = Number((await page.locator("#downbeat").innerText()).replace("Downbeat ", ""));
  expect(nudged).toBeGreaterThan(0.2);

  await stems.click();
  await page.getByRole("button", { name: "Set ranges" }).click();
  const wave = page.locator("#page-ranges .deck-detail");
  await expect(wave).toBeVisible();

  await page.locator("#from").fill("1.1");
  await page.locator("#to").fill("3.3");
  await expect(page.locator("#from")).toHaveValue("1.1");
  await expect(page.locator("#to")).toHaveValue("3.3");

  const waveBox = await wave.boundingBox();
  const end = await page.getByRole("button", { name: "Section end" }).boundingBox();
  await page.mouse.move(end.x + end.width / 2, end.y + end.height / 2);
  await page.mouse.down();
  await page.mouse.move(waveBox.x + waveBox.width * 0.5, end.y + end.height / 2);
  await page.mouse.up();
  const snappedTo = Number(await page.inputValue("#to"));
  expect(Math.abs(snappedTo - snap(SECONDS / 2, bpm, nudged))).toBeLessThan(0.08);
  expect(Number(await page.inputValue("#from"))).toBeCloseTo(1.1, 2);

  await page.getByRole("button", { name: "Section end" }).focus();
  await page.keyboard.press("ArrowRight");
  const bar = (60 / bpm) * 4;
  const nudgedEdge = Number(await page.inputValue("#to"));
  expect(Math.abs(nudgedEdge - snap(snappedTo + bar, bpm, nudged))).toBeLessThan(0.08);

  await page.locator("#clear").click();
  await page.locator(".chip").nth(1).click();
  await expect(page.locator("#from")).toHaveValue("4");
  await expect(page.locator("#to")).toHaveValue("8");

  await page.locator("#from").fill("1");
  await page.locator("#to").fill("2");
  await page.locator("#preview").click();
  const section = page.locator("#section-audio");
  await expect.poll(() => section.evaluate((node) => node.paused)).toBe(false);
  await expect(page.locator("#deck-audio")).toHaveCount(0);
  await page.locator("#preview").click();
  await expect.poll(() => section.evaluate((node) => node.paused)).toBe(true);

  await page.locator("#clear").click();
  const [request] = await Promise.all([
    page.waitForRequest((item) => item.method() === "POST" && item.url().includes("/api/jobs?")),
    page.locator("#separate").click(),
  ]);
  const params = new URL(request.url()).searchParams;
  expect(params.get("camelot")).toBe("8A");
  expect(params.get("key_name")).toBe("A minor");
  expect(Math.abs(Number(params.get("bpm")) - bpm)).toBeLessThan(0.011);
  expect(Math.abs(Number(params.get("downbeat")) - nudged)).toBeLessThan(0.011);
  expect(params.get("analysis_warning")).toBe("");
  await expect(page.locator("#job-reading")).toContainText("8A · A minor");
  await expect(page.locator("#job-reading")).toContainText("BPM");
  await expect(page.locator("#detail .deck-wave")).toHaveCount(0);
  await page.getByRole("button", { name: "Cancel job" }).click();
  await expect(page.locator("#detail .badge")).toHaveText("cancelled");
});

test("a file the server rejects can continue without a grid", async ({ page }) => {
  const listed = page.waitForResponse(
    (response) => response.url().includes("/api/jobs") && response.request().method() === "GET",
  );
  await page.goto("/");
  await listed;
  await page.getByRole("button", { name: "Load", exact: true }).click();
  await page.setInputFiles("#file", {
    name: "bad.wav",
    mimeType: "audio/wav",
    buffer: Buffer.from("not audio"),
  });
  await expect(page.locator("#message")).toContainText("not a readable WAV or MP3");
  await expect(page.getByRole("button", { name: "Choose stems" })).toBeEnabled();
  await expect(page.locator("#reading")).toHaveCount(0);
  await page.getByRole("button", { name: "Choose stems" }).click();
  await expect(page.locator("#page-stems")).toBeVisible();
});
