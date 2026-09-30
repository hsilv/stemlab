const { test, expect } = require("@playwright/test");

// UI only: chooses a file but never clicks "Separate", so no inference runs.
const u32 = (n) => [n & 255, (n >> 8) & 255, (n >> 16) & 255, (n >> 24) & 255];
const tag = (s) => [...s].map((c) => c.charCodeAt(0));
const chunk = (id, body) => [...tag(id), ...u32(body.length), ...body, ...(body.length & 1 ? [0] : [])];
function cuedWav() {
  const rate = 8000;
  const pcm = [];
  for (let i = 0; i < rate * 20; i++) {
    const v = Math.round(9000 * Math.sin(i / 15) * Math.abs(Math.sin(i / 8000)));
    pcm.push(v & 255, (v >> 8) & 255);
  }
  const point = (id, at) => [...u32(id), ...u32(at), ...tag("data"), ...u32(0), ...u32(0), ...u32(at)];
  const label = (id, s) => chunk("labl", [...u32(id), ...tag(s), 0]);
  const body = [
    ...tag("WAVE"),
    ...chunk("fmt ", [1, 0, 1, 0, ...u32(rate), ...u32(rate * 2), 2, 0, 16, 0]),
    ...chunk("data", pcm),
    ...chunk("cue ", [...u32(2), ...point(1, rate * 4), ...point(2, rate * 12)]),
    ...chunk("LIST", [...tag("adtl"), ...label(1, "Intro"), ...label(2, "Drop")]),
  ];
  return Buffer.from([...tag("RIFF"), ...u32(body.length), ...body]);
}

test("pick a section from cues on the waveform", async ({ page }) => {
  await page.goto("/");
  await page.setInputFiles("#file", { name: "cued.wav", mimeType: "audio/wav", buffer: cuedWav() });
  await page.getByRole("button", { name: "Choose stems" }).click();
  await page.getByRole("button", { name: "Set ranges" }).click();
  await expect(page.locator("#timeline")).toBeVisible();
  await expect(page.locator(".marker")).toHaveCount(2);
  await expect(page.locator(".chip")).toHaveCount(3);

  // First marker click sets the start, the second sets the end, the third starts over.
  await page.locator(".marker").nth(0).click();
  await expect(page.locator("#from")).toHaveValue("4");
  await expect(page.locator("#to")).toHaveValue("");
  await page.locator(".marker").nth(1).click();
  await expect(page.locator("#to")).toHaveValue("12");
  await expect(page.locator("#selection")).toBeVisible();
  await expect(page.locator(".chip.active")).toContainText("Intro → Drop");
  const timeline = await page.locator("#timeline").boundingBox();
  const end = await page.getByRole("button", { name: "Section end" }).boundingBox();
  await page.mouse.move(end.x + end.width / 2, end.y + end.height / 2);
  await page.mouse.down();
  await page.mouse.move(timeline.x + timeline.width * 0.5, end.y + end.height / 2);
  await page.mouse.up();
  expect(Number(await page.inputValue("#from"))).toBe(4);
  expect(Number(await page.inputValue("#to"))).toBeLessThan(12);
  expect(Number(await page.inputValue("#to"))).toBeGreaterThan(4);
  await page.screenshot({ path: "test-results/section-picker.png", fullPage: true });
  await page.locator(".marker").nth(0).click();
  await expect(page.locator("#from")).toHaveValue("4");
  await expect(page.locator("#to")).toHaveValue("");

  // Chips pick a whole stretch; the ends of the track are left empty.
  await page.locator(".chip").first().click();
  await expect([await page.inputValue("#from"), await page.inputValue("#to")]).toEqual(["", "4"]);
  await page.locator(".chip").last().click();
  await expect([await page.inputValue("#from"), await page.inputValue("#to")]).toEqual(["12", ""]);

  // Clicking the bare waveform picks a time; Whole track clears.
  await page.locator("#clear").click();
  await page.locator("#timeline").click({ position: { x: 50, y: 40 } });
  expect(Number(await page.inputValue("#from"))).toBeGreaterThan(0);
  await page.locator("#clear").click();
  await expect(page.locator("#from")).toHaveValue("");
  await expect(page.locator("#selection")).toBeHidden();

  await page.locator("#from").fill("0");
  await page.locator("#to").fill("5");
  await page.getByRole("button", { name: "Add range" }).click();
  await page.locator("#from").fill("10");
  await page.locator("#to").fill("15");
  await page.getByRole("button", { name: "Add range" }).click();
  await expect(page.locator(".band")).toHaveCount(2);
  await expect(page.locator(".range")).toHaveCount(2);
  await expect(page.locator("#section-effect")).toContainText("only inside the ranges");
});
