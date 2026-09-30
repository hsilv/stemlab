import { isInvertible } from "./plan.js";
import { session } from "./state.svelte.js";

function correctInstruments() {
  if (
    !isInvertible(session.mode, session.keep) &&
    session.instrumentsFrom === "inverse"
  )
    session.instrumentsFrom = "residual";
}

export function setMode(mode) {
  session.mode = mode;
  correctInstruments();
}

export function setKeep(source, checked) {
  session.keep = checked
    ? [...session.keep.filter((item) => item !== source), source]
    : session.keep.filter((item) => item !== source);
  correctInstruments();
}
