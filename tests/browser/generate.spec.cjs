const { test, expect } = require("@playwright/test");

// Runs against an API-only server (STEMLAB_QUEUE_MODE=local): a job stays queued. When ACE-Step
// is not set up on that server the booth must say so instead; both outcomes are checked.
function clip() {
  const rate = 22050;
  const frames = rate * 3;
  const pcm = Buffer.alloc(frames * 2);
  for (let i = 0; i < frames; i += 1)
    pcm.writeInt16LE(Math.round(0.3 * Math.sin((2 * Math.PI * 220 * i) / rate) * 32767), i * 2);
  const head = Buffer.alloc(44);
  head.write("RIFF", 0);
  head.writeUInt32LE(36 + pcm.length, 4);
  head.write("WAVEfmt ", 8);
  head.writeUInt32LE(16, 16);
  head.writeUInt16LE(1, 20);
  head.writeUInt16LE(1, 22);
  head.writeUInt32LE(rate, 24);
  head.writeUInt32LE(rate * 2, 28);
  head.writeUInt16LE(2, 32);
  head.writeUInt16LE(16, 34);
  head.write("data", 36);
  head.writeUInt32LE(pcm.length, 40);
  return Buffer.concat([head, pcm]);
}

test("the Generate booth explains itself and starts a backing track", async ({ page }) => {
  const config = await (await page.request.get("/api/config")).json();
  await page.goto("/");
  await page.locator("#booth-generate").click();
  const go = page.locator("#generate-go");
  await expect(page.locator("#page-generate")).toBeVisible();
  await expect(page.locator("#page-generate .how li")).toHaveCount(3);
  await page.screenshot({ path: "test-results/generate-empty.png", fullPage: true });
  if (!config.generate.ready) {
    await expect(page.locator("#page-generate")).toContainText("not set up");
    await expect(go).toBeDisabled();
    return;
  }

  await expect(go).toBeDisabled();
  await page.locator(".chip").first().click();
  await expect(page.locator("#generate-prompt")).not.toHaveValue("");
  await expect(go).toBeEnabled();

  const prompt = `browser check ${Date.now()}`;
  await page.locator("#generate-prompt").fill(prompt);
  await page.locator("#generate-duration").fill("20");
  await page.locator("#reference-file").click();
  await expect(go).toBeDisabled();
  await page.locator("#reference-upload").setInputFiles({
    name: "ref.wav",
    mimeType: "audio/wav",
    buffer: clip(),
  });
  await expect(go).toBeEnabled();
  await page.screenshot({ path: "test-results/generate-filled.png", fullPage: true });

  await go.click();
  await expect(page.locator("#history .track", { hasText: prompt }).first()).toBeVisible();
  await expect(page.locator("#detail")).toContainText("Backing track");
  await expect(page.locator("#detail")).not.toContainText("original");
  await expect(page.getByRole("button", { name: "Make another take" })).toBeVisible();
  await page.screenshot({ path: "test-results/generate-started.png", fullPage: true });
});
