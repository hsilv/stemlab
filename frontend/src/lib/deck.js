import { loadFileMedia, resetSection } from "./section.js";
import { session, showPage } from "./state.svelte.js";
import { readTags } from "./tags.js";

export function clearTags() {
  if (session.tags?.coverUrl) URL.revokeObjectURL(session.tags.coverUrl);
  session.tags = null;
}

export function choose(value, sourceJob = null) {
  if (session.uploading) return;
  session.message = "";
  if (!value) return;
  clearTags();
  session.file = null;
  session.sourceJob = null;
  session.chosenLabel = "No file selected";
  if (!/\.(wav|mp3|flac)$/i.test(value.name)) {
    session.message = "Please choose a WAV, MP3 or FLAC file.";
    return;
  }
  if (
    session.config &&
    value.size > session.config.max_upload_mb * 1024 * 1024
  ) {
    session.message = `Choose a file under ${session.config.max_upload_mb} MB.`;
    return;
  }
  session.file = value;
  session.sourceJob = sourceJob;
  resetSection();
  loadFileMedia(value);
  readTags(value).then((tags) => {
    if (session.file !== value) {
      if (tags.coverUrl) URL.revokeObjectURL(tags.coverUrl);
      return;
    }
    session.tags = tags;
  });
  session.chosenLabel = `${value.name} · ${(value.size / 1024 / 1024).toFixed(1)} MB`;
}

// Bring an already uploaded song into the page. The server keeps its copy; only the browser
// needs the audio, for the waveform and preview. Resolves true when the song is loaded.
async function openSong(row) {
  if (session.uploading) return false;
  session.message = "";
  try {
    const response = await fetch(`/api/jobs/${row.id}/audio/original`);
    if (!response.ok) throw new Error("missing");
    const blob = await response.blob();
    choose(new File([blob], row.filename, { type: blob.type }), row);
  } catch {
    session.message = "Could not open the original song.";
    return false;
  }
  return !!session.file;
}

// Open an uploaded song for another edit on the Load step.
export async function editAgain(row) {
  if (await openSong(row)) showPage("load");
}

let extenderToken = 0;

// Open an uploaded song in the Extender booth, unless it is already the one open there.
export async function openForExtender(row) {
  if (session.file && session.sourceJob?.id === row.id) return;
  const token = ++extenderToken;
  await openSong(row);
  if (token !== extenderToken) return;
}
