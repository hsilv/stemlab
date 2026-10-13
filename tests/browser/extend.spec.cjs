const { test, expect } = require("@playwright/test");

// Runs against an API-only server (STEMLAB_QUEUE_MODE=local, no worker): the job stays queued,
// and the preview, which needs the separator, is answered by a stand-in.
function song() {
  const rate = 22050;
  const frames = rate * 20;
  const pcm = Buffer.alloc(frames * 2);
  for (let i = 0; i < frames; i += 1) {
    const hit = i % (rate / 2) < 200 ? 0.8 : 0;
    const value = hit + 0.2 * Math.sin((2 * Math.PI * 220 * i) / rate);
    pcm.writeInt16LE(Math.round(Math.max(-1, Math.min(1, value)) * 32767), i * 2);
  }
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

test("the Extender booth plans an extended version of the song picked in the crate", async ({ page }) => {
  const name = `extend-${Date.now()}.wav`;
  const created = await page.request.post(
    `/api/jobs?filename=${name}&bpm=120&downbeat=0&camelot=8A&key_name=A%20minor`,
    { data: song(), headers: { "Content-Type": "audio/wav" } },
  );
  expect(created.ok()).toBeTruthy();
  await page.goto("/");
  await page.locator("#history .track", { hasText: name }).first().click();
  await page.locator("#booth-extend").click();

  const create = page.locator("#create-extend");
  await expect(page.locator("#page-extend")).toBeVisible();
  await expect(page.locator("#page-extend .deck-detail")).toBeVisible();
  await expect(create).toBeEnabled();

  // A fragment source needs a fragment: the page says so until one is selected and used.
  await page.locator("#intro-bars").selectOption("4");
  await page.locator("#outro-bars").selectOption("4");
  await page.locator("#intro-source").selectOption("fragment");
  await expect(create).toBeDisabled();
  await expect(page.locator("#page-extend")).toContainText("Select the intro fragment");
  await page.locator("#from").count();
  const wave = page.locator("#page-extend .deck-detail");
  const box = await wave.boundingBox();
  await wave.click({ position: { x: box.width * 0.2, y: 40 } });
  await wave.click({ position: { x: box.width * 0.8, y: 40 } });
  // The selection can be heard, and the needle follows it.
  const needle = page.locator("#page-extend .deck-overview .deck-needle");
  await page.locator("#preview-fragment").click();
  await expect(page.locator("#preview-fragment")).toHaveText("Stop");
  const left = async () => parseFloat(await needle.evaluate((node) => node.style.left));
  await expect.poll(left).toBeGreaterThan(5);
  const first = await left();
  await page.waitForTimeout(500);
  expect(await left()).toBeGreaterThan(first);
  await page.locator("#preview-fragment").click();
  await expect(page.locator("#preview-fragment")).toHaveText("Hear selection");
  await expect(page.locator("#use-intro")).toBeEnabled();
  await page.locator("#use-intro").click();
  // A chosen fragment can be heard again, and leaving the booth stops it.
  await page.getByRole("button", { name: "Hear it" }).click();
  await expect(page.locator("#preview-fragment")).toHaveText("Stop");
  await page.locator("#booth-separate").click();
  await expect(page.locator("#preview")).toHaveText("Preview section");
  await page.locator("#booth-extend").click();
  await expect(page.locator("#extend-intro")).toContainText("Fragment: 0:");
  await expect(create).toBeEnabled();
  await page.waitForTimeout(600);
  await page.screenshot({ path: "test-results/extend-page.png", fullPage: true });

  // The preview shows up as a player.
  await page.route("**/extend-preview", (route) =>
    route.fulfill({ status: 200, contentType: "audio/flac", body: Buffer.from("fLaC") }),
  );
  await page.locator("#preview-extend").click();
  await expect(page.locator("#extend-preview")).toBeVisible();

  // The crate stays on screen, so another song can be picked without leaving the booth.
  // Creating it adds a second edit of the same song, described by its bars.
  await create.click();
  await expect(page.locator("#page-process")).toBeVisible();
  await expect(page.locator("#detail")).toContainText("Extended edit · Intro 4 bars · Outro 4 bars");
  const crate = page.locator("#history .song", { hasText: name });
  await expect(crate).toContainText("2 edits");
  await page.screenshot({ path: "test-results/extend.png", fullPage: true });
});

test("a song without a tempo cannot be extended", async ({ page }) => {
  const name = `notempo-${Date.now()}.wav`;
  await page.request.post(`/api/jobs?filename=${name}`, {
    data: song(),
    headers: { "Content-Type": "audio/wav" },
  });
  await page.goto("/");
  await page.locator("#history .track", { hasText: name }).first().click();
  await page.locator("#booth-extend").click();
  await expect(page.locator("#page-extend")).toContainText("No steady tempo was found");
  await expect(page.locator("#create-extend")).toBeDisabled();
});

test("a manual edit places a processed fragment where it is told", async ({ page }) => {
  const name = `manual-${Date.now()}.wav`;
  await page.request.post(`/api/jobs?filename=${name}&bpm=120&downbeat=0&camelot=8A&key_name=A%20minor`, {
    data: song(),
    headers: { "Content-Type": "audio/wav" },
  });
  await page.goto("/");
  await page.locator("#history .track", { hasText: name }).first().click();
  await page.locator("#booth-extend").click();
  await page.locator("#mode-manual").click();
  const add = page.locator("#add-operation");
  await expect(add).toBeDisabled();
  await expect(page.locator("#draft")).toContainText("Select a fragment");

  const wave = page.locator("#page-extend .deck-detail");
  const box = await wave.boundingBox();
  await wave.click({ position: { x: box.width * 0.2, y: 40 } });
  await wave.click({ position: { x: box.width * 0.6, y: 40 } });
  await page.locator("#draft-fragment").click();
  await expect(page.locator("#draft")).toContainText("bars)");

  // Insert needs a position; everything but the voice at one volume says it uses the inverse.
  await page.locator("#draft-action").selectOption("insert");
  await expect(add).toBeDisabled();
  await page.locator("#draft-at").fill("4");
  await page.locator("#draft-stem-vocals").uncheck();
  await expect(page.locator("#draft")).toContainText("the song minus the voice");
  await page.locator("#draft-bars").fill("4");
  await expect(add).toBeEnabled();
  await add.click();
  await expect(page.locator("#operations li")).toHaveCount(1);
  await expect(page.locator("#operations")).toContainText("Insert in the middle before bar 4");
  await expect(page.locator("#operations")).toContainText("the song minus the voice");

  // A replace takes bars from the selection and fits the fragment to them.
  await page.locator("#draft-action").selectOption("replace");
  await page.locator("#draft-fragment").click();
  await page.locator("#draft-span-from").fill("6");
  await page.locator("#draft-span-to").fill("9");
  await add.click();
  await expect(page.locator("#operations li")).toHaveCount(2);
  await expect(page.locator("#operations")).toContainText("Replace part of the song bars 6 to 9");

  // One operation can be heard in its surroundings, and one removed.
  await page.route("**/extend-preview", async (route) => {
    const body = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: "audio/flac",
      body: Buffer.from(`fLaC${body.only}`),
    });
  });
  await page.locator(".hear-op").first().click();
  await expect(page.locator("#extend-preview")).toBeVisible();
  await page.locator(".remove-op").nth(1).click();
  await expect(page.locator("#operations li")).toHaveCount(1);

  await page.waitForTimeout(500);
  await page.screenshot({ path: "test-results/extend-manual.png", fullPage: true });
  await page.locator("#create-extend").click();
  await expect(page.locator("#detail")).toContainText("Extended edit · Manual, 1 operation");
});
