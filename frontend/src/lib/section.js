import { rekordboxCues, wavCues } from "./cues.js";
import { spanError } from "./plan.js";
import { session } from "./state.svelte.js";
import { waveformOf } from "./waveform.js";
import { api } from "./api.js";

export function resetSection() {
  session.fileCues = [];
  session.xmlCues = [];
  session.ranges = [];
  session.flash = "";
  session.wave = null;
  const audio = document.getElementById("section-audio");
  if (audio) audio.pause();
  if (session.audioUrl) URL.revokeObjectURL(session.audioUrl);
  session.audioUrl = null;
  session.from = "";
  session.to = "";
  const rekordbox = document.getElementById("rekordbox");
  if (rekordbox) rekordbox.value = "";
}

export function setSection(from, to) {
  session.from = from;
  session.to = to;
}

export function pickTime(time) {
  const from = session.from;
  const to = session.to;
  const rounded = String(Math.round(time * 10) / 10);
  if (from === "" || to !== "") setSection(rounded, "");
  else if (+rounded > +from) setSection(from, rounded);
  else setSection(rounded, from);
}

export function addRange() {
  if (session.from === "" || session.to === "") {
    session.message = "Set a start and an end, then add the range.";
    return;
  }
  const savedFrom = session.from;
  const savedTo = session.to;
  const error = spanError(
    +savedFrom,
    +savedTo,
    session.ranges.map((range) => [+range.from, +range.to]),
    session.wave,
  );
  if (error) {
    session.message = error;
    return;
  }
  const next = [...session.ranges, { from: savedFrom, to: savedTo }];
  next.sort((a, b) => +a.from - +b.from);
  session.ranges = next;
  session.flash = `${savedFrom}|${savedTo}`;
  session.from = "";
  session.to = "";
  session.message = "";
}

export function removeRange(index) {
  session.ranges = session.ranges.filter((_, item) => item !== index);
}

export function clearRanges() {
  session.ranges = [];
  session.flash = "";
  setSection("", "");
}

export function togglePreview() {
  const audio = document.getElementById("section-audio");
  if (!session.audioUrl || !audio) return;
  if (!audio.paused) {
    audio.pause();
    return;
  }
  audio.currentTime = +session.from || 0;
  audio.play();
}

export function stopAtEnd(event) {
  if (session.to !== "" && event.currentTarget.currentTime >= +session.to)
    event.currentTarget.pause();
}

export async function importRekordbox(file) {
  if (!file || !session.file) return;
  session.xmlCues = rekordboxCues(await file.text(), session.file.name);
  if (!session.xmlCues.length)
    session.message = `No hot cues for "${session.file.name}" found in that Rekordbox export.`;
}

export async function loadFileMedia(chosen) {
  const [wav, mixxx, wave] = await Promise.all([
    /\.wav$/i.test(chosen.name) ? wavCues(chosen).catch(() => []) : [],
    api(
      `/api/mixxx/cues?${new URLSearchParams({ filename: chosen.name })}`,
    ).catch(() => []),
    waveformOf(chosen).catch(() => null),
  ]);
  if (session.file !== chosen) return;
  session.fileCues = [...wav, ...mixxx];
  if (!wave) return;
  session.wave = wave;
  session.audioUrl = URL.createObjectURL(chosen);
  const audio = document.getElementById("section-audio");
  if (audio) audio.src = session.audioUrl;
}
