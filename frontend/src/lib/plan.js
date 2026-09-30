import { clock } from "./format.js";
import {
  instrumentSourceNames,
  modelNames,
  sourceNames,
  sources,
  vocalNames,
} from "./labels.js";

export function chosenSources(mode, keep) {
  if (mode === "vocals") return ["vocals"];
  if (mode === "instrumental") return ["drums", "bass", "other"];
  if (mode === "custom") return sources.filter((name) => keep.includes(name));
  return [...sources];
}

// Subtracting the vocals only yields every instrument together.
export function isInvertible(mode, keep) {
  const chosen = chosenSources(mode, keep);
  return chosen.length === 3 && !chosen.includes("vocals");
}

export function previewNote(mode, chosen) {
  const excluded = sources.filter((name) => !chosen.includes(name));
  if (!chosen.length)
    return {
      className: "error",
      text: "Select at least one sound to create your mix.",
    };
  if (mode === "all")
    return {
      className: "note",
      text: "Each sound will be saved as its own track.",
    };
  const head =
    chosen.length > 1 ? "Kept together in one track." : "One isolated track.";
  const tail = excluded.length
    ? ` Left out: ${excluded.map((name) => sourceNames[name]).join(", ")}.`
    : " All sounds included.";
  return { className: "note", text: head + tail };
}

export function outputSummary(mode, chosen) {
  if (mode === "all") return "4 individual WAV files";
  if (chosen.length) return "1 WAV file · Your selected sounds";
  return "Choose at least one sound";
}

export function spanError(from, to, others, wave) {
  if (!(to > from)) return "The range must end after it starts.";
  if (to - from < 1) return "Each range must be at least 1 second.";
  if (wave && to > wave.duration + 0.05)
    return "That range ends after the track.";
  if (others.some(([start, end]) => from < end && to > start))
    return "Ranges overlap. Leave a gap between them, or make them one range.";
  return "";
}

export function describeEffect(mode, ranges, from, to) {
  const spans = ranges.map((range) => [+range.from, +range.to]);
  if (from !== "" && to !== "") spans.push([+from, +to]);
  if (!spans.length && from === "" && to === "")
    return "The effect covers the whole track.";
  if (from !== "" && to === "") return "Set the end, then add the range.";
  if (mode === "all" && spans.length > 1)
    return "All stems: four tracks the length of the song. Audio is only inside the ranges; the rest is silent so the files still line up.";
  if (mode === "all")
    return "All stems: you get four tracks that cover just this section.";
  return spans.length > 1
    ? "You get the whole song. The effect applies only to these ranges; the rest stays as the original."
    : "You get the whole song. The effect applies only to this section; the rest stays as the original.";
}

export function qualityText(row) {
  const vocals = `Vocals: ${vocalNames[row.vocals]}`;
  const tail = `${row.shifts} shifts · ${Math.round(row.overlap * 100)}% overlap`;
  if (row.vocals !== "demucs" && row.instruments_from === "inverse")
    return `${vocals} · Instruments: the mix minus the vocals`;
  const source =
    row.vocals === "demucs"
      ? ""
      : ` on the ${instrumentSourceNames[row.instruments_from].toLowerCase()}`;
  return `${vocals} · Instruments: ${modelNames[row.model]}${source} · ${tail}`;
}

export function rangeNote(row) {
  const spans = row.ranges;
  if (!spans || !spans.length) return "";
  const listed = spans
    .map(([start, end]) => `${clock(start)}–${clock(end)}`)
    .join(", ");
  if (row.mode === "all" && spans.length > 1)
    return ` · Ranges ${listed} (audio only there; the rest of each stem is silent)`;
  if (row.mode === "all")
    return ` · Section ${listed} (stems cover just this section)`;
  return ` · ${spans.length > 1 ? "Ranges" : "Section"} ${listed} (the rest of the song is unchanged)`;
}

export function stageValue(stage, status) {
  if (status === "completed" || stage === "Ready") return 100;
  if (status === "failed" || status === "cancelled") return 0;
  const range = /Range (\d+) of (\d+)/.exec(stage || "");
  if (range)
    return Math.round(
      20 + (55 * (Number(range[1]) - 1)) / Number(range[2]),
    );
  if (/Separating drums/.test(stage)) return 62;
  if (/Separating/.test(stage)) return 42;
  if (/Restoring/.test(stage)) return 80;
  if (/Writing/.test(stage)) return 88;
  if (/Preparing/.test(stage)) return 94;
  if (/Loading model/.test(stage)) return 22;
  if (/Waiting/.test(stage)) return 8;
  return 12;
}
