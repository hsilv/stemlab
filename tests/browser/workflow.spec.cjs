const { test, expect } = require("@playwright/test");

function wav() {
  const rate = 16000,
    frames = rate * 2,
    bytes = frames * 2;
  const result = Buffer.alloc(44 + bytes);
  result.write("RIFF");
  result.writeUInt32LE(36 + bytes, 4);
  result.write("WAVEfmt ", 8);
  result.writeUInt32LE(16, 16);
  result.writeUInt16LE(1, 20);
  result.writeUInt16LE(1, 22);
  result.writeUInt32LE(rate, 24);
  result.writeUInt32LE(rate * 2, 28);
  result.writeUInt16LE(2, 32);
  result.writeUInt16LE(16, 34);
  result.write("data", 36);
  result.writeUInt32LE(bytes, 40);
  for (let i = 0; i < frames; i++)
    result.writeInt16LE(
      Math.round(3000 * Math.sin((2 * Math.PI * 220 * i) / rate)),
      44 + i * 2,
    );
  return result;
}

test("upload, separate, preview, download, reload, delete on desktop and mobile", async ({
  page,
}) => {
  const filename = `browser-check-${Date.now()}.wav`;
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Hear every layer." }),
  ).toBeVisible();
  await page
    .locator("#file")
    .setInputFiles({ name: filename, mimeType: "audio/wav", buffer: wav() });
  await page.getByRole("button", { name: "Separate track" }).click();
  await expect(page.locator("#detail h2")).toHaveText(filename);
  await expect(page.locator("#detail .badge")).toHaveText("completed", {
    timeout: 100000,
  });
  await expect(page.locator("#detail audio")).toHaveCount(5);
  await page
    .locator('audio[aria-label="vocals preview"]')
    .evaluate(async (player) => {
      await player.play();
    });
  await expect
    .poll(() =>
      page
        .locator('audio[aria-label="vocals preview"]')
        .evaluate((player) => player.currentTime),
    )
    .toBeGreaterThan(0);
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download all stems" }).click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toBe(
    filename.replace(".wav", "-stems.zip"),
  );
  await page.reload();
  await expect(page.locator("#detail .badge")).toHaveText("completed");
  await page.screenshot({
    path: "test-results/stemlab-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("button", { name: "Separate track" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/stemlab-mobile.png",
    fullPage: true,
  });
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(
    page.getByRole("button", { name: new RegExp(filename) }),
  ).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("invalid file displays an actionable error", async ({ page }) => {
  await page.goto("/");
  await page
    .locator("#file")
    .setInputFiles({
      name: "bad.wav",
      mimeType: "audio/wav",
      buffer: Buffer.from("invalid"),
    });
  await page.getByRole("button", { name: "Separate track" }).click();
  await expect(page.getByRole("alert")).toContainText("readable WAV");
});
