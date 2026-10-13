export const steps = ["load", "stems", "ranges", "process"];

export const session = $state({
  // Which booth the header shows: "separate", "playlist", "extend", "tags" or "generate".
  booth: "separate",
  step: "load",
  motion: "forward",
  file: null,
  // The job whose uploaded song is being edited again; null for a freshly chosen file.
  sourceJob: null,
  chosenLabel: "No file selected",
  uploading: false,
  progress: 0,
  uploadLabel: "Uploading",
  config: null,
  limits: "Mono or stereo · WAV, MP3 or FLAC audio",
  model: "",
  vocals: "",
  instrumentsFrom: "",
  shifts: "",
  overlap: "",
  shiftOptions: [],
  overlapOptions: [],
  mode: "all",
  keep: ["vocals", "drums", "bass", "other"],
  from: "",
  to: "",
  ranges: [],
  fileCues: [],
  xmlCues: [],
  wave: null,
  audioUrl: null,
  rows: [],
  loaded: false,
  selectedId: null,
  openedActive: false,
  connectionError: false,
  message: "",
  actionPending: false,
  tags: null,
  analysisStatus: "",
  analysisStage: "",
  bpm: null,
  camelot: null,
  keyName: null,
  downbeat: null,
  analysisWarning: "",
  needle: 0,
  zoom: 1,
  volume: 1,
  downbeatArmed: false,
  snap: true,
  exportFormat: "flac",
  // The intro and outro being planned for the song in sourceJob. A side with bars 0 is left out.
  extend: {
    intro: { bars: 16, source: "stable_drums", treatment: "layered", fragment: null },
    outro: { bars: 16, source: "last_bars", fragment: null },
  },
  // "auto" builds an intro and outro by itself; "manual" places fragments one by one.
  extendMode: "auto",
  // Manual edit: the operations so far (as the server takes them) and the one being drafted.
  manual: {
    operations: [],
    draft: {
      action: "insert",
      fragment: null,
      bars: 4,
      at: null,
      // The bars to replace: the first bar (0 is the first) and the last bar's number.
      spanFrom: null,
      spanTo: null,
      stems: { vocals: 1, drums: 1, bass: 1, other: 1 },
      model: "",
      vocals: "",
      shifts: "",
      overlap: "",
    },
  },
  // The Tags booth: where tags come from and where they go. Each side is a crate output
  // (job and stem) or an uploaded file, as a reference the server understands.
  tagTool: {
    source: { kind: "job", job: "", stem: "original", ref: "", info: null, name: "", error: "" },
    target: { kind: "job", job: "", stem: "original", ref: "", info: null, name: "", error: "" },
    // null adds the target's own version name to the title; "" adds nothing.
    version: null,
    cover: true,
    busy: false,
    done: "",
  },
  // The Generate booth: the description of the music, how long it lasts, and the optional
  // reference it should sound like (a crate song, a file, or none).
  generate: {
    prompt: "",
    duration: 30,
    reference: { kind: "none", job: "", stem: "original", file: null },
    busy: false,
  },
  extendBusy: false,
  // True while the section player is playing.
  previewing: false,
  previewUrl: "",
});

export function showPage(next) {
  session.motion =
    steps.indexOf(next) < steps.indexOf(session.step) ? "back" : "forward";
  session.step = next;
}
