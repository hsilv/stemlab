import { api } from "./api.js";
import { activeStatuses } from "./labels.js";
import { chosenSources, spanError } from "./plan.js";
import { clearTags } from "./deck.js";
import { resetSection } from "./section.js";
import { session, showPage } from "./state.svelte.js";

export async function loadConfig() {
  try {
    const value = await api("/api/config");
    session.config = value;
    session.model = value.defaults.model;
    session.vocals = value.defaults.vocals;
    session.instrumentsFrom = value.defaults.instruments_from;
    session.shifts = String(value.defaults.shifts);
    session.overlap = String(value.defaults.overlap);
    session.shiftOptions = Array.from(
      { length: value.max_shifts + 1 },
      (_, index) => index,
    );
    session.overlapOptions = [...new Set([0.25, 0.5, 0.75, value.defaults.overlap])].sort();
    session.limits = `WAV or MP3 · Up to ${value.max_upload_mb} MB · ${value.max_duration_seconds / 60} minutes`;
  } catch {
    session.message = "Cannot load server settings.";
  }
}

export async function refresh() {
  const rows = await api("/api/jobs");
  session.rows = rows;
  session.loaded = true;
  if (!rows.some((row) => row.id === session.selectedId))
    session.selectedId = rows[0]?.id || null;
  if (!session.openedActive) {
    session.openedActive = true;
    const current = rows.find((row) => row.id === session.selectedId);
    if (current && activeStatuses.has(current.status)) showPage("process");
  }
}

export function startPolling() {
  let timer = 0;
  const poll = async () => {
    try {
      await refresh();
      if (session.connectionError) {
        session.message = "";
        session.connectionError = false;
      }
    } catch {
      session.connectionError = true;
      session.message = "Cannot reach StemLab. Check that the server is running.";
    }
    timer = setTimeout(poll, 2500);
  };
  poll();
  return () => clearTimeout(timer);
}

export async function runJobAction(actionName, id) {
  if (
    actionName === "delete" &&
    !window.confirm("Delete this track and all its stems?")
  )
    return;
  session.actionPending = true;
  session.message = "";
  try {
    await api(
      `/api/jobs/${id}${actionName === "delete" ? "" : `/${actionName}`}`,
      { method: actionName === "delete" ? "DELETE" : "POST" },
    );
    await refresh();
  } catch (error) {
    session.message = error.message;
  } finally {
    session.actionPending = false;
  }
}

function draftSpans() {
  const spans = session.ranges.map((range) => [range.from, range.to]);
  if (session.from !== "" && session.to !== "")
    spans.push([session.from, session.to]);
  spans.sort((a, b) => +a[0] - +b[0]);
  return spans;
}

export function separate() {
  const file = session.file;
  if (!file || session.uploading) return;
  const keep = chosenSources(session.mode, session.keep);
  if (session.mode === "custom" && !keep.length) return;
  if (session.from !== "" && session.to === "") {
    session.message = "Finish the range or clear it before separating.";
    return;
  }
  if (session.from !== "" && session.to !== "") {
    const error = spanError(
      +session.from,
      +session.to,
      session.ranges.map((range) => [+range.from, +range.to]),
      session.wave,
    );
    if (error) {
      session.message = error;
      return;
    }
  }
  session.uploading = true;
  session.message = "";
  session.progress = 0;
  session.uploadLabel = "Uploading…";
  const xhr = new XMLHttpRequest();
  const params = new URLSearchParams({
    filename: file.name,
    mode: session.mode,
    model: session.model,
    vocals: session.vocals,
    instruments_from: session.instrumentsFrom,
    shifts: session.shifts,
    overlap: session.overlap,
  });
  if (session.mode === "custom") params.set("keep", keep.join(","));
  const spans = draftSpans();
  if (spans.length === 1) {
    params.set("start", spans[0][0]);
    params.set("end", spans[0][1]);
  } else if (spans.length > 1) {
    params.set("ranges", spans.map((pair) => `${pair[0]}-${pair[1]}`).join(","));
  }
  showPage("process");
  xhr.open("POST", `/api/jobs?${params}`);
  xhr.setRequestHeader(
    "Content-Type",
    file.name.toLowerCase().endsWith(".mp3") ? "audio/mpeg" : "audio/wav",
  );
  xhr.upload.onprogress = (event) => {
    if (event.lengthComputable)
      session.progress = (event.loaded / event.total) * 100;
    if (event.loaded === event.total) session.uploadLabel = "Validating audio…";
  };
  xhr.onload = async () => {
    try {
      const result = JSON.parse(xhr.responseText);
      if (xhr.status >= 400)
        throw new Error(
          typeof result.detail === "string" ? result.detail : "Upload failed.",
        );
      session.selectedId = result.id;
      session.file = null;
      clearTags();
      resetSection();
      const input = document.getElementById("file");
      if (input) input.value = "";
      session.chosenLabel = "No file selected";
      await refresh();
    } catch (error) {
      session.message = error.message;
    }
  };
  xhr.onerror = () => {
    session.message =
      "Upload interrupted. Check the server connection and try again.";
  };
  xhr.onloadend = () => {
    session.uploading = false;
  };
  xhr.send(file);
}
