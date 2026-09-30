const { test, expect } = require("@playwright/test");
const path = require("path");

// Parser checks only: no server, model or audio processing involved.
test.beforeEach(async ({ page }) => {
  await page.goto("about:blank");
  await page.addScriptTag({
    path: path.join(__dirname, "../../frontend/src/lib/cues.js"),
    type: "module",
  });
  await page.waitForFunction(() => window.wavCues && window.rekordboxCues);
});

test("reads WAV cue points and labels", async ({ page }) => {
  const cues = await page.evaluate(async () => {
    const u32 = (n) => [n & 255, (n >> 8) & 255, (n >> 16) & 255, (n >> 24) & 255];
    const tag = (s) => [...s].map((c) => c.charCodeAt(0));
    const chunk = (id, body) => [...tag(id), ...u32(body.length), ...body, ...(body.length & 1 ? [0] : [])];
    const fmt = chunk("fmt ", [1, 0, 1, 0, ...u32(1000), ...u32(2000), 2, 0, 16, 0]);
    const data = chunk("data", new Array(4000).fill(0));
    const point = (id, at) => [...u32(id), ...u32(at), ...tag("data"), ...u32(0), ...u32(0), ...u32(at)];
    const cue = chunk("cue ", [...u32(2), ...point(2, 2500), ...point(1, 500)]);
    const label = (id, s) => chunk("labl", [...u32(id), ...tag(s), 0]);
    const list = chunk("LIST", [...tag("adtl"), ...label(1, "Drop")]);
    const body = [...tag("WAVE"), ...fmt, ...data, ...cue, ...list];
    const bytes = new Uint8Array([...tag("RIFF"), ...u32(body.length), ...body]);
    return wavCues(new File([bytes], "a.wav"));
  });
  expect(cues).toEqual([
    { label: "Drop", time: 0.5 },
    { label: "Cue 1", time: 2.5 },
  ]);
});

test("WAV without cues or non-WAV data gives no cues", async ({ page }) => {
  expect(await page.evaluate(() => wavCues(new File([new Uint8Array(20)], "a.wav")))).toEqual([]);
});

test("reads Rekordbox hot cues for the matching track only", async ({ page }) => {
  const xml = `<DJ_PLAYLISTS><COLLECTION>
    <TRACK Location="file://localhost/Music/Other%20Song.mp3"><POSITION_MARK Name="" Type="0" Start="1" Num="0"/></TRACK>
    <TRACK Location="file://localhost/Music/My%20Song.mp3">
      <POSITION_MARK Name="Memory" Type="0" Start="5" Num="-1"/>
      <POSITION_MARK Name="Chorus" Type="0" Start="90.5" Num="1"/>
      <POSITION_MARK Name="" Type="0" Start="12.25" Num="0"/>
    </TRACK></COLLECTION></DJ_PLAYLISTS>`;
  const cues = await page.evaluate((x) => rekordboxCues(x, "My Song.mp3"), xml);
  expect(cues).toEqual([
    { label: "Hot cue 1", time: 12.25 },
    { label: "Chorus", time: 90.5 },
  ]);
  expect(await page.evaluate((x) => rekordboxCues(x, "Missing.mp3"), xml)).toEqual([]);
});
