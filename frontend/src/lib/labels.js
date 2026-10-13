// What new jobs write; the server reports each finished output's own format.
export const exportFormat = "FLAC";

// What a listener can download a finished track as. The server lists which it can write.
export const exportFormats = {
  flac: "FLAC · lossless",
  wav: "WAV · 24-bit",
  mp3: "MP3 · 320 kbps",
};

export const sources = ["vocals", "drums", "bass", "other"];

export const sourceNames = {
  vocals: "Vocals",
  drums: "Drums",
  bass: "Bass",
  other: "Other instruments",
};

export const modeNames = {
  all: "All stems",
  vocals: "Vocals only",
  instrumental: "No vocals",
  custom: "Custom mix",
  extend: "Extended edit",
  generate: "Backing track",
};

export const manualActions = {
  start: "Paste at the start",
  end: "Paste at the end",
  insert: "Insert in the middle",
  replace: "Replace part of the song",
};

export const extendBars = [4, 8, 16, 32];
export const introSources = {
  stable_drums: "First steady drums",
  first_bars: "First bars of the song",
  fragment: "A fragment I choose",
};
export const introTreatments = {
  layered: "Layers enter one by one",
  drums_bass: "Drums and bass",
  instrumental: "Instrumental, no voice",
  mix: "The mix as it is",
};
export const outroSources = {
  last_bars: "Last bars of the song",
  fragment: "A fragment I choose",
};

export const modelNames = {
  htdemucs: "Demucs (fast)",
  htdemucs_ft: "Demucs fine-tuned",
  hdemucs_mmi: "Demucs MMI",
  ft_mmi: "Demucs fine-tuned + MMI (averaged, slower)",
};

export const vocalNames = {
  demucs: "Demucs (same model)",
  melband: "MelBand Roformer",
  bs: "BS-Roformer 1297",
  beta4: "MelBand Roformer Big Beta 4",
  bs1296: "BS-Roformer 1296",
  resurrection: "BS-Roformer Resurrection",
  ensemble: "MelBand + BS-Roformer (averaged)",
  ensemble_all: "All four Roformers (averaged, slowest)",
};

export const instrumentSourceNames = {
  residual: "Track without vocals",
  mix: "Original track",
  inverse: "Mix minus vocals (no Demucs; No vocals only)",
  direct_resurrection: "Instrumental model: BS-Roformer Resurrection (No vocals only)",
  direct_inst_v2: "Instrumental model: MelBand Inst V2 (No vocals only)",
  direct_bleedless: "Instrumental model: MelBand Bleedless v3 (No vocals only)",
};

export const activeStatuses = new Set(["queued", "running", "cancelling"]);

export const modes = [
  {
    value: "vocals",
    title: "Vocals only",
    detail: "The voice, on its own",
    icons: ["vocals"],
  },
  {
    value: "instrumental",
    title: "No vocals",
    detail: "All instruments together",
    icons: ["drums", "bass", "other"],
  },
  {
    value: "all",
    title: "All stems",
    detail: "Four individual tracks",
    icons: ["vocals", "drums", "bass", "other"],
  },
  {
    value: "custom",
    title: "Custom mix",
    detail: "You choose what stays",
    icons: ["vocals", "drums", "bass", "other"],
  },
];
