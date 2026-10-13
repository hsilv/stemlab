import { nearestBar } from "./grid.js";
import { clock } from "./format.js";
import { manualActions, modelNames, sourceNames, vocalNames } from "./labels.js";
import { session } from "./state.svelte.js";

const STEMS = ["vocals", "drums", "bass", "other"];
const INSTRUMENTS = ["drums", "bass", "other"];

// Whole bars a stretch of seconds covers, by the beat grid; 0 without one.
export function barsOf(from, to) {
  const start = nearestBar(+from, session.bpm, session.downbeat);
  const end = nearestBar(+to, session.bpm, session.downbeat);
  return start == null || end == null ? 0 : Math.max(0, end - start);
}

export function firstBar(time) {
  return nearestBar(+time, session.bpm, session.downbeat);
}

// Everything but the voice at one volume is taken as the song minus the voice.
export function usesInverse(stems) {
  return (
    !stems.vocals &&
    INSTRUMENTS.every((name) => stems[name]) &&
    new Set(INSTRUMENTS.map((name) => stems[name])).size === 1
  );
}

export function draftProblem(draft) {
  if (!draft.fragment) return "Select a fragment on the waveform and use it.";
  if (!STEMS.some((name) => draft.stems[name])) return "Choose at least one sound.";
  if (draft.action === "insert" && draft.at == null) return "Choose the bar to insert before.";
  if (draft.action === "replace") {
    if (draft.spanFrom == null || draft.spanTo == null) return "Choose the bars to replace.";
    if (draft.spanTo <= draft.spanFrom) return "The bars to replace must cover at least one bar.";
  }
  if (draft.action !== "replace" && !(draft.bars >= 1 && draft.bars <= 64))
    return "The length must be 1 to 64 bars.";
  return "";
}

// The operation as the server takes it; bar numbers there start at 0.
export function operationOf(draft) {
  const operation = {
    action: draft.action,
    fragment: [...draft.fragment],
    stems: { ...draft.stems },
    model: draft.model || session.model,
    vocals: draft.vocals || session.vocals,
    shifts: +(draft.shifts === "" ? session.shifts : draft.shifts),
    overlap: +(draft.overlap === "" ? session.overlap : draft.overlap),
  };
  if (draft.action === "insert") operation.at = draft.at;
  if (draft.action === "replace") operation.span = [draft.spanFrom, draft.spanTo];
  if (draft.action !== "replace") operation.bars = +draft.bars;
  return operation;
}

export function describe(operation) {
  const [from, to] = operation.fragment;
  const where =
    operation.action === "insert"
      ? ` before bar ${operation.at + 1}`
      : operation.action === "replace"
        ? ` bars ${operation.span[0] + 1} to ${operation.span[1]}`
        : "";
  const length = operation.bars ? ` as ${operation.bars} bars` : "";
  const sounds = STEMS.filter((name) => operation.stems[name])
    .map((name) =>
      operation.stems[name] === 1
        ? sourceNames[name]
        : `${sourceNames[name]} ${Math.round(operation.stems[name] * 100)}%`,
    )
    .join(", ");
  const how = usesInverse(operation.stems)
    ? "the song minus the voice"
    : `${modelNames[operation.model] ?? operation.model} · voice: ${vocalNames[operation.vocals] ?? operation.vocals}`;
  return `${manualActions[operation.action]}${where} · fragment ${clock(from)}–${clock(to)}${length} · ${sounds} · ${how}`;
}

export function addOperation() {
  const draft = session.manual.draft;
  if (draftProblem(draft)) return;
  session.manual.operations = [...session.manual.operations, operationOf(draft)];
  draft.fragment = null;
  draft.at = null;
  draft.spanFrom = null;
  draft.spanTo = null;
}

export function removeOperation(index) {
  session.manual.operations = session.manual.operations.filter((_, item) => item !== index);
}
