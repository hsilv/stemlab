import { chosenSources } from "./plan.js";
import { session, showPage } from "./state.svelte.js";

export function analysisSettled() {
  return session.analysisStatus === "completed" || session.analysisStatus === "failed";
}

function holdForGrid() {
  return !!session.file && !analysisSettled();
}

function keepFailure() {
  if (session.analysisStatus !== "failed") session.message = "";
}

export function goLoad() {
  showPage("load");
}

export function goProcess() {
  showPage("process");
}

export function goStemsTab() {
  if (holdForGrid()) return;
  keepFailure();
  showPage("stems");
}

export function goStems() {
  if (!session.file) {
    session.message = "Choose a WAV or MP3 first.";
    return;
  }
  if (holdForGrid()) return;
  keepFailure();
  document.getElementById("deck-audio")?.pause();
  showPage("stems");
}

export function goRanges() {
  if (!session.file) {
    session.message = "Choose a WAV or MP3 first.";
    return;
  }
  if (holdForGrid()) return;
  if (!chosenSources(session.mode, session.keep).length) {
    session.message = "Select at least one sound to create your mix.";
    return;
  }
  keepFailure();
  showPage("ranges");
}

export function openJob(id) {
  session.selectedId = id;
  showPage("process");
}
