import { api } from "./api.js";
import { activeStatuses } from "./labels.js";
import { chosenSources, spanError } from "./plan.js";
import { clearTags } from "./deck.js";
import { resetSection, setPreviewVolume } from "./section.js";
import { session, showPage } from "./state.svelte.js";

let analysisToken = 0;
let analysisAbort = null;

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

const AUDIO_TYPES = { ".mp3": "audio/mpeg", ".flac": "audio/flac" };

// What an upload's body is called on the wire: by its extension, WAV when it has no other.
function audioType(filename) {
  const extension = filename.toLowerCase().match(/\.[a-z0-9]+$/)?.[0];
  return AUDIO_TYPES[extension] ?? "audio/wav";
}

export function failureText(body, fallback) {
  return typeof body?.detail === "string" ? body.detail : fallback;
}

export function resetAnalysis() {
  analysisToken += 1;
  analysisAbort?.abort();
  analysisAbort = null;
  session.analysisStatus = "";
  session.analysisStage = "";
  session.bpm = null;
  session.camelot = null;
  session.keyName = null;
  session.downbeat = null;
  session.analysisWarning = "";
  session.needle = 0;
  session.zoom = 1;
  setPreviewVolume(1);
  session.downbeatArmed = false;
}

function failAnalysis(message) {
  session.analysisStatus = "failed";
  session.analysisStage = "";
  session.bpm = null;
  session.camelot = null;
  session.keyName = null;
  session.downbeat = null;
  session.analysisWarning = "";
  session.downbeatArmed = false;
  session.message = message;
}

function applyAnalysis(body) {
  if (body.stage) session.analysisStage = body.stage;
  if (body.status === "completed") {
    session.bpm = body.bpm ?? null;
    session.camelot = body.camelot ?? null;
    session.keyName = body.key_name ?? null;
    session.downbeat = body.downbeat ?? null;
    session.analysisWarning = body.warning || "";
    session.analysisStatus = "completed";
    return true;
  }
  if (body.status === "failed") {
    failAnalysis(body.error || "Could not read tempo and key.");
    return true;
  }
  return false;
}

async function pollAnalysis(id, token, signal) {
  while (token === analysisToken) {
    const response = await fetch(`/api/analyses/${id}`, { signal });
    const body = await response.json().catch(() => ({}));
    if (token !== analysisToken) return;
    if (!response.ok) {
      failAnalysis(failureText(body, "Could not read tempo and key."));
      return;
    }
    if (applyAnalysis(body)) return;
    await wait(400);
  }
}

// A song uploaded before already has its reading stored on the job. Only a job from before
// readings existed is analyzed again.
export function reuseReading(row, file) {
  if (row.bpm == null && !row.camelot) return beginAnalysis(file);
  resetAnalysis();
  session.bpm = row.bpm;
  session.camelot = row.camelot;
  session.keyName = row.key_name;
  session.downbeat = row.downbeat;
  session.analysisWarning = row.analysis_warning || "";
  session.analysisStatus = "completed";
}

export async function beginAnalysis(file) {
  resetAnalysis();
  const token = analysisToken;
  session.analysisStatus = "running";
  session.analysisStage = "Checking the file";
  analysisAbort = new AbortController();
  const signal = analysisAbort.signal;
  try {
    const response = await fetch(
      `/api/analyses?${new URLSearchParams({ filename: file.name })}`,
      {
        method: "POST",
        headers: {
          "Content-Type": audioType(file.name),
        },
        body: file,
        signal,
      },
    );
    const body = await response.json().catch(() => ({}));
    if (token !== analysisToken) return;
    if (!response.ok) {
      failAnalysis(failureText(body, "Could not read tempo and key."));
      return;
    }
    if (!applyAnalysis(body)) await pollAnalysis(body.id, token, signal);
  } catch (error) {
    if (token !== analysisToken || error?.name === "AbortError") return;
    failAnalysis("Could not read tempo and key.");
  }
}

function appendReading(params) {
  if (session.analysisStatus !== "completed") return;
  if (session.bpm != null) params.set("bpm", String(session.bpm));
  if (session.camelot) params.set("camelot", session.camelot);
  if (session.keyName) params.set("key_name", session.keyName);
  if (session.downbeat != null) params.set("downbeat", String(session.downbeat));
  params.set("analysis_warning", session.analysisWarning || "");
}

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
    session.limits = `WAV, MP3 or FLAC · Up to ${value.max_upload_mb} MB · ${value.max_duration_seconds / 60} minutes`;
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
  session.uploadLabel = session.sourceJob ? "Preparing…" : "Uploading…";
  const xhr = new XMLHttpRequest();
  const params = new URLSearchParams({
    mode: session.mode,
    model: session.model,
    vocals: session.vocals,
    instruments_from: session.instrumentsFrom,
    shifts: session.shifts,
    overlap: session.overlap,
  });
  if (session.sourceJob) params.set("from_job", session.sourceJob.id);
  else params.set("filename", file.name);
  if (session.mode === "custom") params.set("keep", keep.join(","));
  const spans = draftSpans();
  if (spans.length === 1) {
    params.set("start", spans[0][0]);
    params.set("end", spans[0][1]);
  } else if (spans.length > 1) {
    params.set("ranges", spans.map((pair) => `${pair[0]}-${pair[1]}`).join(","));
  }
  appendReading(params);
  showPage("process");
  xhr.open("POST", `/api/jobs?${params}`);
  if (!session.sourceJob)
    xhr.setRequestHeader("Content-Type", audioType(file.name));
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
      session.sourceJob = null;
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
  xhr.send(session.sourceJob ? null : file);
}

// The intro and outro to send: a side with no bars is left out, a fragment only travels with
// the fragment source.
export function extendPayload() {
  if (session.extendMode === "manual") return { operations: session.manual.operations };
  const side = (planned, withTreatment) => {
    if (!planned.bars) return null;
    const body = { bars: planned.bars, source: planned.source };
    if (withTreatment) body.treatment = planned.treatment;
    if (planned.source === "fragment") body.fragment = planned.fragment;
    return body;
  };
  return { intro: side(session.extend.intro, true), outro: side(session.extend.outro, false) };
}

export function extendProblem() {
  if (session.extendMode === "manual") {
    if (!session.bpm) return "No steady tempo was found, so there is no beat grid to extend on.";
    return session.manual.operations.length ? "" : "Add at least one operation.";
  }
  const { intro, outro } = session.extend;
  if (!intro.bars && !outro.bars) return "Choose an intro, an outro or both.";
  if (!session.bpm) return "No steady tempo was found, so there is no beat grid to extend on.";
  for (const [name, side] of [["intro", intro], ["outro", outro]])
    if (side.bars && side.source === "fragment" && !side.fragment)
      return `Select the ${name} fragment on the waveform first.`;
  return "";
}

async function failure(response, fallback) {
  const body = await response.json().catch(() => ({}));
  return failureText(body, fallback);
}

// A short rendering of the joins, for listening before the real edit is made.
export async function previewExtended(only = null) {
  const problem = extendProblem();
  if (problem || !session.sourceJob || session.extendBusy) {
    session.message = problem;
    return;
  }
  session.extendBusy = true;
  session.message = "";
  try {
    const response = await fetch(`/api/jobs/${session.sourceJob.id}/extend-preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        extend: extendPayload(),
        bpm: session.bpm,
        downbeat: session.downbeat,
        only,
      }),
    });
    if (!response.ok) throw new Error(await failure(response, "Could not build the preview."));
    if (session.previewUrl) URL.revokeObjectURL(session.previewUrl);
    session.previewUrl = URL.createObjectURL(await response.blob());
  } catch (error) {
    session.message = error.message || "Could not build the preview.";
  } finally {
    session.extendBusy = false;
  }
}

export async function createExtended() {
  const problem = extendProblem();
  if (problem || !session.sourceJob || session.extendBusy) {
    session.message = problem;
    return;
  }
  session.extendBusy = true;
  session.message = "";
  const params = new URLSearchParams({
    from_job: session.sourceJob.id,
    mode: "extend",
    extend: JSON.stringify(extendPayload()),
  });
  appendReading(params);
  try {
    const response = await fetch(`/api/jobs?${params}`, { method: "POST" });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(failureText(body, "Could not create the extended edit."));
    session.selectedId = body.id;
    session.file = null;
    session.sourceJob = null;
    clearTags();
    resetSection();
    if (session.previewUrl) URL.revokeObjectURL(session.previewUrl);
    session.previewUrl = "";
    session.manual.operations = [];
    session.chosenLabel = "No file selected";
    session.booth = "separate";
    showPage("process");
    await refresh();
  } catch (error) {
    session.message = error.message || "Could not create the extended edit.";
  } finally {
    session.extendBusy = false;
  }
}
