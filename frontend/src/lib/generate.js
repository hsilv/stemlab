import { failureText, refresh } from "./jobs.js";
import { session, showPage } from "./state.svelte.js";

// Clickable starting points, for someone who does not know what to write.
export const examples = [
  "Warm lo-fi hip hop, mellow drums, soft electric piano, relaxed",
  "Upbeat funk groove, slap bass, tight drums, bright guitar, 110 BPM",
  "Dark cinematic synthwave, driving bass, pulsing synths, 120 BPM",
  "Gentle acoustic folk, fingerpicked guitar, light percussion, calm",
];

// What a good description names, one line each.
export const tips = [
  ["Style", "the genre or era: lo-fi, funk, house, 80s pop, jazz trio."],
  ["Feeling", "the mood: relaxed, tense, bright, dreamy, energetic."],
  ["Instruments", "what should play: drums, bass, piano, strings, synth pads."],
  ["Speed", "a tempo such as 90 BPM, or words like slow and driving."],
];

export function problem() {
  const { prompt, reference } = session.generate;
  if (!session.config?.generate?.ready)
    return "Generation is not set up on this machine yet. The README explains the one-time setup.";
  if (!prompt.trim()) return "Describe the music you want.";
  if (reference.kind === "job" && !reference.job) return "Choose the song to copy the style of.";
  if (reference.kind === "file" && !reference.file) return "Choose the audio file to copy the style of.";
  return "";
}

// Fill the booth with an earlier backing track's description, to make another take of it.
export function reuse(row) {
  session.generate.prompt = row.generate.prompt;
  session.generate.duration = row.generate.duration;
  session.generate.reference = { kind: "none", job: "", stem: "original", file: null };
  session.booth = "generate";
}

export async function createGenerated() {
  const form = session.generate;
  if (problem() || form.busy) {
    session.message = problem();
    return;
  }
  form.busy = true;
  session.message = "";
  const params = new URLSearchParams({
    prompt: form.prompt.trim(),
    duration: String(form.duration),
  });
  const { reference } = form;
  if (reference.kind === "job") {
    params.set("reference_job", reference.job);
    params.set("reference_stem", reference.stem);
  }
  if (reference.kind === "file") params.set("filename", reference.file.name);
  try {
    const response = await fetch(`/api/generate?${params}`, {
      method: "POST",
      body: reference.kind === "file" ? reference.file : null,
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(failureText(body, "Could not start the backing track."));
    session.selectedId = body.id;
    session.booth = "separate";
    showPage("process");
    await refresh();
  } catch (error) {
    session.message = error.message || "Could not start the backing track.";
  } finally {
    form.busy = false;
  }
}
