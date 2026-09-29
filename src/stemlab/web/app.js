const $ = (id) => document.getElementById(id);
let file = null,
  selected = null,
  rows = [],
  uploading = false,
  config = null,
  detailVersion = "";
let historyVersion = "",
  connectionError = false;
const active = new Set(["queued", "running", "cancelling"]);
const sourceNames = {
  vocals: "Vocals",
  drums: "Drums",
  bass: "Bass",
  other: "Other instruments",
};
const modeNames = {
  all: "All stems",
  vocals: "Vocals only",
  instrumental: "No vocals",
  custom: "Custom mix",
};
function selection() {
  const mode = document.querySelector('input[name="mode"]:checked').value;
  const keep = [...document.querySelectorAll('input[name="keep"]:checked')].map(
    (input) => input.value,
  );
  return { mode, keep };
}
function updateSelection() {
  const { mode, keep } = selection();
  $("custom-sources").hidden = mode !== "custom";
  const chosen =
    mode === "vocals"
      ? ["vocals"]
      : mode === "instrumental"
        ? ["drums", "bass", "other"]
        : mode === "custom"
          ? keep
          : Object.keys(sourceNames);
  const preview = $("output-preview");
  preview.replaceChildren(element("strong", "YOUR OUTPUT"));
  const files = element("div", undefined, "output-files");
  if (mode === "all") {
    for (const name of chosen)
      files.append(element("div", `${sourceNames[name]} · WAV`, "output-file"));
  } else if (chosen.length) {
    const output = element(
      "div",
      mode === "instrumental"
        ? "Instrumental · WAV"
        : `${modeNames[mode]} · WAV`,
      "output-file",
    );
    output.append(
      element("small", chosen.map((name) => sourceNames[name]).join(" + ")),
    );
    files.append(output);
  }
  preview.append(files);
  const excluded = Object.keys(sourceNames).filter(
    (name) => !chosen.includes(name),
  );
  preview.append(
    element(
      "p",
      !chosen.length
        ? "Select at least one sound to create your mix."
        : mode === "all"
          ? "Each sound will be saved as its own track."
          : `${chosen.length > 1 ? "Kept together in one track." : "One isolated track."}${excluded.length ? " Left out: " + excluded.map((name) => sourceNames[name]).join(", ") + "." : " All sounds included."}`,
      !chosen.length ? "error" : "note",
    ),
  );
  $("output-summary").textContent =
    mode === "all"
      ? "4 individual WAV files"
      : chosen.length
        ? "1 WAV file · Your selected sounds"
        : "Choose at least one sound";
  $("separate").disabled = !file || uploading || !chosen.length;
}
$("output-selector").addEventListener("change", updateSelection);
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function message(text = "") {
  $("message").textContent = text;
  $("message").hidden = !text;
}
async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : `Request failed (${response.status}).`,
    );
  }
  return response.status === 204 ? null : response.json();
}
function choose(value) {
  if (uploading) return;
  message();
  if (!value) return;
  file = null;
  $("separate").disabled = true;
  $("chosen").textContent = "No file selected";
  if (!/\.(wav|mp3)$/i.test(value.name)) {
    message("Please choose a WAV or MP3 file.");
    return;
  }
  if (config && value.size > config.max_upload_mb * 1024 * 1024) {
    message(`Choose a file under ${config.max_upload_mb} MB.`);
    return;
  }
  file = value;
  $("chosen").textContent =
    `${file.name} · ${(file.size / 1024 / 1024).toFixed(1)} MB`;
  updateSelection();
}
$("file").addEventListener("change", (event) => choose(event.target.files[0]));
for (const event of ["dragenter", "dragover"])
  $("dropzone").addEventListener(event, (e) => {
    e.preventDefault();
    $("dropzone").classList.add("dragging");
  });
for (const event of ["dragleave", "drop"])
  $("dropzone").addEventListener(event, (e) => {
    e.preventDefault();
    $("dropzone").classList.remove("dragging");
  });
$("dropzone").addEventListener("drop", (event) =>
  choose(event.dataTransfer.files[0]),
);
$("separate").addEventListener("click", () => {
  if (!file || uploading) return;
  const { mode, keep } = selection();
  if (mode === "custom" && !keep.length) return;
  uploading = true;
  message();
  $("separate").disabled = true;
  $("file").disabled = true;
  $("output-selector").disabled = true;
  $("upload-status").hidden = false;
  $("upload-progress").value = 0;
  $("upload-label").textContent = "Uploading…";
  const xhr = new XMLHttpRequest();
  const params = new URLSearchParams({ filename: file.name, mode });
  if (mode === "custom") params.set("keep", keep.join(","));
  xhr.open("POST", `/api/jobs?${params}`);
  xhr.setRequestHeader(
    "Content-Type",
    file.name.toLowerCase().endsWith(".mp3") ? "audio/mpeg" : "audio/wav",
  );
  xhr.upload.onprogress = (event) => {
    if (event.lengthComputable)
      $("upload-progress").value = (event.loaded / event.total) * 100;
    if (event.loaded === event.total)
      $("upload-label").textContent = "Validating audio…";
  };
  xhr.onload = async () => {
    try {
      const result = JSON.parse(xhr.responseText);
      if (xhr.status >= 400)
        throw new Error(
          typeof result.detail === "string" ? result.detail : "Upload failed.",
        );
      selected = result.id;
      detailVersion = "";
      file = null;
      $("file").value = "";
      $("chosen").textContent = "No file selected";
      await refresh();
    } catch (error) {
      message(error.message);
    }
  };
  xhr.onerror = () =>
    message("Upload interrupted. Check the server connection and try again.");
  xhr.onloadend = () => {
    uploading = false;
    $("file").disabled = false;
    $("output-selector").disabled = false;
    updateSelection();
    $("upload-status").hidden = true;
  };
  xhr.send(file);
});
function duration(seconds) {
  return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
}
function renderHistory() {
  const version =
    selected +
    JSON.stringify(rows.map((row) => [row.id, row.status, row.filename]));
  if (version === historyVersion) return;
  historyVersion = version;
  $("count").textContent = rows.length;
  $("history").replaceChildren();
  if (!rows.length)
    $("history").append(
      element("p", "Your separated tracks will appear here.", "note"),
    );
  for (const row of rows) {
    const button = element(
      "button",
      undefined,
      `track ${row.id === selected ? "selected" : ""}`,
    );
    button.setAttribute("aria-pressed", String(row.id === selected));
    button.append(
      element("strong", row.filename),
      element(
        "small",
        `${duration(row.duration)} · ${row.status} · ${modeNames[row.mode] || "All stems"}`,
      ),
    );
    button.onclick = () => {
      selected = row.id;
      detailVersion = "";
      renderHistory();
      renderDetail();
    };
    $("history").append(button);
  }
}
function link(text, href, className = "button") {
  const a = element("a", text, className);
  a.href = href;
  return a;
}
function action(text, actionName, id, className = "") {
  const button = element("button", text, className);
  button.onclick = async () => {
    if (
      actionName === "delete" &&
      !window.confirm("Delete this track and all its stems?")
    )
      return;
    button.disabled = true;
    message();
    try {
      await api(
        `/api/jobs/${id}${actionName === "delete" ? "" : "/" + actionName}`,
        { method: actionName === "delete" ? "DELETE" : "POST" },
      );
      detailVersion = "";
      await refresh();
    } catch (error) {
      message(error.message);
      button.disabled = false;
    }
  };
  return button;
}
function audioRow(row, stem, label = stem, sources = []) {
  const section = element("div", undefined, "stem");
  const top = element("div", undefined, "stem-top");
  top.append(
    element("strong", label),
    link(
      stem === "original" && row.filename.toLowerCase().endsWith(".mp3")
        ? "Download MP3 ↓"
        : "Download WAV ↓",
      `/api/jobs/${row.id}/audio/${stem}?download=true`,
      "",
    ),
  );
  const player = element("audio");
  player.controls = true;
  player.preload = "none";
  player.src = `/api/jobs/${row.id}/audio/${stem}`;
  player.setAttribute("aria-label", `${stem} preview`);
  player.addEventListener("play", () =>
    document.querySelectorAll("audio").forEach((other) => {
      if (other !== player) other.pause();
    }),
  );
  section.append(top);
  if (sources.length > 1)
    section.append(
      element(
        "p",
        sources.map((name) => sourceNames[name]).join(" + "),
        "note",
      ),
    );
  section.append(player);
  return section;
}
function renderDetail() {
  const row = rows.find((row) => row.id === selected);
  if (!row) {
    if (!detailVersion) {
      const empty = element("div", undefined, "empty");
      empty.append(
        element("span", "≋"),
        element("h2", "A little space for every sound."),
        element("p", "Choose a WAV or MP3 to create your first mix."),
      );
      $("detail").replaceChildren(empty);
      detailVersion = "empty";
    }
    return;
  }
  // Heartbeats do not replace audio players or interrupt playback.
  const version = [row.id, row.status, row.stage, row.error].join("|");
  if (version === detailVersion) return;
  detailVersion = version;
  const heading = element("div", undefined, "detail-heading");
  const title = element("div");
  title.append(
    element("h2", row.filename),
    element(
      "div",
      `${duration(row.duration)} · ${(row.sample_rate / 1000).toFixed(1)} kHz · ${row.channels === 1 ? "Mono" : "Stereo"}`,
      "meta",
    ),
  );
  heading.append(title, element("span", row.status, `badge ${row.status}`));
  const stage = element(
    "div",
    row.stage,
    `stage ${active.has(row.status) ? "busy" : ""}`,
  );
  stage.setAttribute("role", "status");
  const actions = element("div", undefined, "actions");
  if (row.status === "completed")
    actions.append(
      link(
        row.mode === "all" ? "Download all stems ↓" : "Download result ZIP ↓",
        `/api/jobs/${row.id}/download`,
        "button primary",
      ),
    );
  if (["queued", "running"].includes(row.status))
    actions.append(action("Cancel job", "cancel", row.id));
  if (["failed", "cancelled"].includes(row.status))
    actions.append(action("Try again", "retry", row.id, "primary"));
  if (!active.has(row.status))
    actions.append(action("Delete", "delete", row.id, "danger"));
  $("detail").replaceChildren(heading, stage);
  $("detail").append(
    element("p", `Output: ${modeNames[row.mode] || "All stems"}`, "note"),
  );
  if (row.error) $("detail").append(element("p", row.error, "error"));
  if (active.has(row.status))
    $("detail").append(
      element(
        "p",
        "You can leave this page and return later. The first run downloads the model; processing time depends on track length and your hardware.",
        "note",
      ),
    );
  $("detail").append(actions, audioRow(row, "original"));
  if (row.status === "completed") {
    for (const output of row.outputs)
      $("detail").append(
        audioRow(row, output.id, output.label, output.sources),
      );
    $("detail").append(
      element(
        "p",
        "44.1 kHz stereo · 32-bit float WAV. Separation may contain artifacts or sound from other instruments.",
        "note",
      ),
    );
  }
}
async function refresh() {
  rows = await api("/api/jobs");
  if (!rows.some((row) => row.id === selected)) {
    selected = rows[0]?.id || null;
    detailVersion = "";
  }
  renderHistory();
  renderDetail();
}
async function poll() {
  try {
    await refresh();
    if (connectionError) {
      message();
      connectionError = false;
    }
  } catch (error) {
    connectionError = true;
    message("Cannot reach StemLab. Check that the server is running.");
  }
  setTimeout(poll, 2500);
}
api("/api/config")
  .then((value) => {
    config = value;
    $("limits").textContent =
      `WAV or MP3 · Up to ${value.max_upload_mb} MB · ${value.max_duration_seconds / 60} minutes`;
  })
  .catch(() => message("Cannot load server settings."));
updateSelection();
poll();
