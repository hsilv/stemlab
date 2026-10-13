export function duration(seconds) {
  return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
}

export function clock(seconds) {
  return `${duration(seconds)}.${Math.floor((seconds % 1) * 10)}`;
}

// Valence and energy run 0 to 1. Labels are for reading a list, not for measuring.
export function moodLine(valence, energy) {
  const parts = [];
  if (valence != null) parts.push(valence < 0.35 ? "Dark" : valence > 0.55 ? "Bright" : "Even");
  if (energy != null) parts.push(energy < 0.5 ? "Calm" : energy > 0.62 ? "Driving" : "Steady");
  return parts.join(" · ");
}

export function readingLine(bpm, camelot, keyName) {
  const parts = [];
  if (bpm != null && bpm !== "") parts.push(`${Number(bpm).toFixed(2)} BPM`);
  if (camelot && keyName) parts.push(`${camelot} · ${keyName}`);
  else if (camelot || keyName) parts.push(camelot || keyName);
  return parts.join(" · ");
}

export function stamp(seconds) {
  return new Date(seconds * 1000).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
