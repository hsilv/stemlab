import { chosenSources } from "./plan.js";
import { session, showPage } from "./state.svelte.js";

export function goLoad() {
  showPage("load");
}

export function goProcess() {
  showPage("process");
}

export function goStemsTab() {
  session.message = "";
  showPage("stems");
}

export function goStems() {
  if (!session.file) {
    session.message = "Choose a WAV or MP3 first.";
    return;
  }
  session.message = "";
  showPage("stems");
}

export function goRanges() {
  if (!session.file) {
    session.message = "Choose a WAV or MP3 first.";
    return;
  }
  if (!chosenSources(session.mode, session.keep).length) {
    session.message = "Select at least one sound to create your mix.";
    return;
  }
  session.message = "";
  showPage("ranges");
}

export function openJob(id) {
  session.selectedId = id;
  showPage("process");
}
