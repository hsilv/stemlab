export const steps = ["load", "stems", "ranges", "process"];

export const session = $state({
  step: "load",
  motion: "forward",
  file: null,
  chosenLabel: "No file selected",
  uploading: false,
  progress: 0,
  uploadLabel: "Uploading",
  config: null,
  limits: "Mono or stereo · WAV or MP3 audio",
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
});

export function showPage(next) {
  session.motion =
    steps.indexOf(next) < steps.indexOf(session.step) ? "back" : "forward";
  session.step = next;
}
