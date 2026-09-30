export function duration(seconds) {
  return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
}

export function clock(seconds) {
  return `${duration(seconds)}.${Math.floor((seconds % 1) * 10)}`;
}

export function readingLine(bpm, camelot, keyName) {
  const parts = [];
  if (bpm != null && bpm !== "") parts.push(`${Number(bpm).toFixed(2)} BPM`);
  if (camelot && keyName) parts.push(`${camelot} · ${keyName}`);
  else if (camelot || keyName) parts.push(camelot || keyName);
  return parts.join(" · ");
}
