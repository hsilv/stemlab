const { test, expect } = require("@playwright/test");

// UI only: submits to an API-only server (STEMLAB_QUEUE_MODE=local, no worker), so nothing runs.
function tinyWav() {
  const u32 = (n) => [n & 255, (n >> 8) & 255, (n >> 16) & 255, (n >> 24) & 255];
  const tag = (s) => [...s].map((c) => c.charCodeAt(0));
  const data = new Array(16000 * 2 * 2).fill(0);
  const body = [
    ...tag("WAVE"),
    ...tag("fmt "), ...u32(16), 1, 0, 1, 0, ...u32(16000), ...u32(32000), 2, 0, 16, 0,
    ...tag("data"), ...u32(data.length), ...data,
  ];
  return Buffer.from([...tag("RIFF"), ...u32(body.length), ...body]);
}

test("each stage of the pipeline can be chosen", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Stems", exact: true }).click();
  await expect(page.locator("#vocals option")).toHaveCount(7);
  await expect(page.locator("#model option")).toHaveCount(4);
  await expect(page.locator("#instruments-from option")).toHaveCount(3);
  await expect(page.locator("#vocals")).toHaveValue("ensemble");
  await expect(page.locator("#instruments-from")).toBeEnabled();

  // Without Roformer vocals there is no vocal-removed track to choose.
  await page.selectOption("#vocals", "demucs");
  await expect(page.locator("#instruments-from")).toBeDisabled();
  await page.selectOption("#vocals", "bs");
  await expect(page.locator("#instruments-from")).toBeEnabled();

  await page.selectOption("#model", "htdemucs");
  await page.selectOption("#instruments-from", "mix");
  await page.setInputFiles("#file", { name: "t.wav", mimeType: "audio/wav", buffer: tinyWav() });
  await page.getByRole("button", { name: "Set ranges" }).click();
  const [request] = await Promise.all([
    page.waitForRequest((r) => r.url().includes("/api/jobs?")),
    page.click("#separate"),
  ]);
  const params = new URL(request.url()).searchParams;
  expect([params.get("model"), params.get("vocals"), params.get("instruments_from")]).toEqual([
    "htdemucs",
    "bs",
    "mix",
  ]);
  await expect(page.locator("#detail")).toContainText(
    "Vocals: BS-Roformer 1297 · Instruments: Demucs (fast) on the original track",
  );
});

test("mix minus vocals is offered only when the output is the plain instrumental", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Stems", exact: true }).click();
  const inverse = page.locator('#instruments-from option[value="inverse"]');
  // Playwright does not report <option> as disabled, so check the DOM property.
  await expect(inverse).toHaveJSProperty("disabled", true); // "All stems" needs the instruments

  await page.locator('input[name="mode"][value="instrumental"]').check({ force: true });
  await expect(inverse).toHaveJSProperty("disabled", false);
  await page.selectOption("#instruments-from", "inverse");

  // Changing to an output that needs separate instruments resets the choice.
  await page.locator('input[name="mode"][value="vocals"]').check({ force: true });
  await expect(page.locator("#instruments-from")).toHaveValue("residual");

  await page.locator('input[name="mode"][value="instrumental"]').check({ force: true });
  await page.selectOption("#instruments-from", "inverse");
  await page.setInputFiles("#file", { name: "t.wav", mimeType: "audio/wav", buffer: tinyWav() });
  await page.getByRole("button", { name: "Set ranges" }).click();
  const [request] = await Promise.all([
    page.waitForRequest((r) => r.url().includes("/api/jobs?")),
    page.click("#separate"),
  ]);
  const params = new URL(request.url()).searchParams;
  expect([params.get("mode"), params.get("instruments_from")]).toEqual(["instrumental", "inverse"]);
  await expect(page.locator("#detail")).toContainText("Instruments: the mix minus the vocals");
});
