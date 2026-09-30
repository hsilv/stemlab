import { loadFileMedia, resetSection } from "./section.js";
import { session } from "./state.svelte.js";
import { readTags } from "./tags.js";

export function clearTags() {
  if (session.tags?.coverUrl) URL.revokeObjectURL(session.tags.coverUrl);
  session.tags = null;
}

export function choose(value) {
  if (session.uploading) return;
  session.message = "";
  if (!value) return;
  clearTags();
  session.file = null;
  session.chosenLabel = "No file selected";
  if (!/\.(wav|mp3)$/i.test(value.name)) {
    session.message = "Please choose a WAV or MP3 file.";
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
