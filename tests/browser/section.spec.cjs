const { test, expect } = require("@playwright/test");

// Chooses a file but never clicks "Separate". The clicks and tone are a clear grid,
// so the load step's tempo reading finishes without running a separator.
function u32(n) {
  const bytes = Buffer.alloc(4);
  bytes.writeUInt32LE(n >>> 0);
  return bytes;
}

function chunk(id, body) {
  const pad = body.length & 1 ? Buffer.alloc(1) : Buffer.alloc(0);
  return Buffer.concat([Buffer.from(id), u32(body.length), body, pad]);
}

function cuedWav() {
  const rate = 22050;
  const seconds = 16;
  const frames = rate * seconds;
  const pcm = Buffer.alloc(frames * 2);
  const notes = [57, 60, 64, 69, 72, 76];
  const beat = 60 / 120;
  const fade = Math.round(0.01 * rate);
  for (let i = 0; i < frames; i++) {
    const t = i / rate;
    let sample = 0;
    for (const midi of notes) {
      const freq = 440 * 2 ** ((midi - 69) / 12);
      sample += Math.sin(2 * Math.PI * freq * t);
    }
    sample *= 0.5 / notes.length;
    if (i < fade) sample *= i / fade;
    if (i >= frames - fade) sample *= (frames - 1 - i) / fade;
    const nearest = Math.round(t / beat) * beat;
    if (i === Math.round(nearest * rate)) sample += 0.8;
    const value = Math.max(-32767, Math.min(32767, Math.round(sample * 32767)));
    pcm.writeInt16LE(value, i * 2);
  }
  const fmt = Buffer.alloc(16);
  fmt.writeUInt16LE(1, 0);
  fmt.writeUInt16LE(1, 2);
  fmt.writeUInt32LE(rate, 4);
  fmt.writeUInt32LE(rate * 2, 8);
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
    chunk("cue ", Buffer.concat([u32(2), point(1, rate * 4), point(2, rate * 12)])),
    chunk("LIST", Buffer.concat([Buffer.from("adtl"), label(1, "Intro"), label(2, "Drop")])),
  ]);
  return Buffer.concat([Buffer.from("RIFF"), u32(body.length), body]);
}

test("pick a section from cues on the waveform", async ({ page }) => {
  await page.goto("/");
  await page.setInputFiles("#file", { name: "cued.wav", mimeType: "audio/wav", buffer: cuedWav() });
  await page.getByRole("button", { name: "Choose stems" }).click();
  await page.getByRole("button", { name: "Set ranges" }).click();
  const wave = page.locator("#page-ranges .deck-detail");
  await expect(wave).toBeVisible();
  await expect(page.locator("#page-ranges .deck-marker")).toHaveCount(2);
  await expect(page.locator(".chip")).toHaveCount(3);

  // First marker click sets the start, the second sets the end, the third starts over.
  await page.locator("#page-ranges .deck-marker").nth(0).click();
  await expect(page.locator("#from")).toHaveValue("4");
  await expect(page.locator("#to")).toHaveValue("");
  await page.locator("#page-ranges .deck-marker").nth(1).click();
  await expect(page.locator("#to")).toHaveValue("12");
  await expect(page.locator("#page-ranges .deck-detail .deck-selection")).toBeVisible();
  await expect(page.locator(".chip.active")).toContainText("Intro → Drop");
  const timeline = await wave.boundingBox();
  const end = await page.getByRole("button", { name: "Section end" }).boundingBox();
  await page.mouse.move(end.x + end.width / 2, end.y + end.height / 2);
  await page.mouse.down();
  await page.mouse.move(timeline.x + timeline.width * 0.5, end.y + end.height / 2);
  await page.mouse.up();
  expect(Number(await page.inputValue("#from"))).toBe(4);
  expect(Number(await page.inputValue("#to"))).toBeLessThan(12);
  expect(Number(await page.inputValue("#to"))).toBeGreaterThan(4);
  await page.screenshot({ path: "test-results/section-picker.png", fullPage: true });
  await page.locator("#page-ranges .deck-marker").nth(0).click();
  await expect(page.locator("#from")).toHaveValue("4");
  await expect(page.locator("#to")).toHaveValue("");

  // Chips pick a whole stretch; the ends of the track are left empty.
  await page.locator(".chip").first().click();
  await expect([await page.inputValue("#from"), await page.inputValue("#to")]).toEqual(["", "4"]);
  await page.locator(".chip").last().click();
  await expect([await page.inputValue("#from"), await page.inputValue("#to")]).toEqual(["12", ""]);

  // Clicking the bare waveform picks a time; Whole track clears.
  await page.locator("#clear").click();
  await wave.click({ position: { x: 50, y: 40 } });
  expect(Number(await page.inputValue("#from"))).toBeGreaterThan(0);
  await page.locator("#clear").click();
  await expect(page.locator("#from")).toHaveValue("");
  await expect(page.locator("#page-ranges .deck-detail .deck-selection")).toBeHidden();

  await page.locator("#from").fill("0");
  await page.locator("#to").fill("5");
  await page.getByRole("button", { name: "Add range" }).click();
  await page.locator("#from").fill("10");
  await page.locator("#to").fill("15");
  await page.getByRole("button", { name: "Add range" }).click();
  await expect(page.locator("#page-ranges .deck-detail .deck-band")).toHaveCount(2);
  await expect(page.locator(".range")).toHaveCount(2);
  await expect(page.locator("#section-effect")).toContainText("only inside the ranges");
});
