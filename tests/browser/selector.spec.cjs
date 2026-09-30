const { test, expect } = require("@playwright/test");
const { execFileSync } = require("node:child_process");
const { resolve } = require("node:path");
const python = resolve(".venv/bin/python");

function audio(format) {
  return execFileSync(python, [
    "-c",
    `import io, sys, numpy as np, soundfile as sf
t=np.arange(44100*2)/44100
b=io.BytesIO()
sf.write(b, 0.1*np.sin(2*np.pi*220*t), 44100, format='${format}')
sys.stdout.buffer.write(b.getvalue())`,
  ]);
}

for (const [mode, label, output, format] of [
  ["vocals", "Vocals only", "vocals", "WAV"],
  ["instrumental", "No vocals", "instrumental", "WAV"],
  ["custom", "Custom mix", "mix", "WAV"],
  ["instrumental", "No vocals", "instrumental", "MP3"],
]) {
  test(`${mode} ${format}: selection, GPU output, playback and persistence`, async ({
    page,
  }) => {
    const filename = `${mode}-${Date.now()}.${format.toLowerCase()}`;
    await page.goto("/");
    await page.getByRole("button", { name: "Stems", exact: true }).click();
    await page.getByRole("radio", { name: new RegExp(label) }).check();
    if (mode === "custom") {
      await page
        .getByRole("checkbox", { name: "Drums", exact: true })
        .uncheck();
      await page
        .getByRole("checkbox", { name: "Other instruments", exact: true })
        .uncheck();
      await expect(page.locator("#output-preview")).toContainText(
        "Vocals + Bass",
      );
    }
    if (mode === "instrumental")
      await expect(page.locator("#output-preview")).toContainText(
        "Drums + Bass + Other instruments",
      );
    await expect(page.locator("#output-preview .output-file")).toHaveCount(1);
    await page
      .locator("#file")
      .setInputFiles({
        name: filename,
        mimeType: format === "MP3" ? "audio/mpeg" : "audio/wav",
        buffer: audio(format),
      });
    await page.getByRole("button", { name: "Set ranges" }).click();
    const submitted = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.url().includes("/api/jobs?"),
    );
    await page.getByRole("button", { name: "Separate track" }).click();
    const row = await (await submitted).json();
    expect(row.mode).toBe(mode);
    expect(row.outputs.map((item) => item.id)).toEqual([output]);
    if (mode === "custom") expect(row.keep).toEqual(["vocals", "bass"]);
    await expect(page.locator("#detail h2")).toHaveText(filename);
    await expect(page.locator("#detail .badge")).toHaveText("completed", {
      timeout: 100000,
    });
    await expect(page.locator("#detail audio")).toHaveCount(2);
    const player = page.locator(`audio[aria-label="${output} preview"]`);
    await player.evaluate((audio) => audio.play());
    await expect
      .poll(() => player.evaluate((audio) => audio.currentTime))
      .toBeGreaterThan(0);
    if (format === "MP3") {
      const original = page.locator('audio[aria-label="original preview"]');
      await original.evaluate((audio) => audio.play());
      await expect
        .poll(() => original.evaluate((audio) => audio.currentTime))
        .toBeGreaterThan(0);
      await expect(
        page.getByRole("link", { name: "Download MP3" }),
      ).toBeVisible();
    }
    const downloadEvent = page.waitForEvent("download");
    await page.getByRole("link", { name: "Download result ZIP" }).click();
    const download = await downloadEvent;
    const names = JSON.parse(
      execFileSync(
        python,
        [
          "-c",
          "import json,sys,zipfile; print(json.dumps(zipfile.ZipFile(sys.argv[1]).namelist()))",
          await download.path(),
        ],
        { encoding: "utf8" },
      ),
    );
    expect(names).toEqual([`${output}.wav`]);
    await page.reload();
    await page.getByRole("button", { name: "Process", exact: true }).click();
    await expect(page.locator("#detail")).toContainText(`Output: ${label}`);
    await expect(page.locator("#detail audio")).toHaveCount(2);
    if (mode === "custom") {
      await page.getByRole("button", { name: "Stems", exact: true }).click();
      await page.getByRole("radio", { name: /Custom mix/ }).check();
      await page
        .getByRole("checkbox", { name: "Drums", exact: true })
        .uncheck();
      await page
        .getByRole("checkbox", { name: "Other instruments", exact: true })
        .uncheck();
      await page.screenshot({
        path: "test-results/selector-desktop.png",
        fullPage: true,
      });
      await page.setViewportSize({ width: 390, height: 844 });
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: "test-results/selector-mobile.png",
        fullPage: true,
      });
    }
    page.once("dialog", (dialog) => dialog.accept());
    await page.getByRole("button", { name: "Delete", exact: true }).click();
    await expect(
      page.getByRole("button", { name: new RegExp(filename) }),
    ).toHaveCount(0);
  });
}

test("empty custom selection blocks submission and keyboard presets work", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .locator("#file")
    .setInputFiles({
      name: "selection.wav",
      mimeType: "audio/wav",
      buffer: audio("WAV"),
    });
  await page.getByRole("button", { name: "Stems", exact: true }).click();
  await page.getByRole("radio", { name: /Custom mix/ }).check();
  for (const name of ["Vocals", "Drums", "Bass", "Other instruments"]) {
    await page.getByRole("checkbox", { name, exact: true }).uncheck();
  }
  await expect(page.getByRole("button", { name: "Set ranges" })).toBeDisabled();
  await expect(page.locator("#output-preview")).toContainText(
    "Select at least one sound",
  );
  const vocals = page.getByRole("radio", { name: /Vocals only/ });
  await vocals.focus();
  await page.keyboard.press("Space");
  await expect(vocals).toBeChecked();
  await expect(page.getByRole("button", { name: "Set ranges" })).toBeEnabled();
  await page.getByRole("button", { name: "Set ranges" }).click();
  await expect(
    page.getByRole("button", { name: "Separate track" }),
  ).toBeEnabled();
});
