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
  ensemble: "MelBand + BS-Roformer (averaged)",
  ensemble_all: "All four Roformers (averaged, slowest)",
};

export const instrumentSourceNames = {
  residual: "Track without vocals",
  mix: "Original track",
  inverse: "Mix minus vocals (no Demucs; No vocals only)",
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
