import { rekordboxCues, wavCues } from "./cues.js";
import { spanError } from "./plan.js";
import { session } from "./state.svelte.js";
import { waveformOf } from "./waveform.js";
import { api } from "./api.js";

function playbackVolume(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 1;
  return Math.min(1, Math.max(0, number));
}

export function setPreviewVolume(value) {
  session.volume = playbackVolume(value);
  for (const id of ["deck-audio", "section-audio"]) {
    const audio = document.getElementById(id);
    if (audio) audio.volume = session.volume;
  }
}

export function resetSection() {
  session.fileCues = [];
  session.xmlCues = [];
  session.ranges = [];
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

function placed(time) {
  return Math.round(time * 10000) / 10000;
}

function clampEdge(time, other, edge) {
  const limit = session.wave?.duration ?? 0;
  let value = Math.min(limit, Math.max(0, placed(time)));
  if (other === "") return value;
  const bound = +other;
  value =
    edge === "from"
      ? Math.min(value, placed(bound - 0.1))
      : Math.max(value, placed(bound + 0.1));
  return Math.min(limit, Math.max(0, placed(value)));
}

export function moveSelectionEdge(edge, time) {
  const value = String(clampEdge(time, edge === "from" ? session.to : session.from, edge));
  if (edge === "from") session.from = value;
  else session.to = value;
}

export function nudgeSelectionEdge(edge, delta) {
  const current =
    edge === "from"
      ? session.from === ""
        ? 0
        : +session.from
      : session.to === ""
        ? (session.wave?.duration ?? 0)
        : +session.to;
  moveSelectionEdge(edge, current + delta);
}

export function moveRangeEdge(index, edge, time) {
  const range = session.ranges[index];
  if (!range || !session.wave) return;
  let from = +range.from;
  let to = +range.to;
  if (edge === "from") from = Math.min(placed(time), placed(to - 0.1));
  else to = Math.max(placed(time), placed(from + 0.1));
  from = Math.max(0, placed(from));
  to = Math.min(session.wave.duration, placed(to));
  const others = session.ranges
    .filter((_, item) => item !== index)
    .map((item) => [+item.from, +item.to]);
  if (spanError(from, to, others, session.wave)) return;
  session.ranges = session.ranges.map((item, itemIndex) =>
    itemIndex === index ? { from: String(from), to: String(to) } : item,
  );
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
  session.from = "";
  session.to = "";
  session.message = "";
}

export function removeRange(index) {
  session.ranges = session.ranges.filter((_, item) => item !== index);
}

export function clearRanges() {
  session.ranges = [];
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
  if (audio) {
    audio.src = session.audioUrl;
    audio.volume = session.volume;
  }
}
