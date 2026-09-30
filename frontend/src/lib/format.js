export function duration(seconds) {
  return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
}

export function clock(seconds) {
  return `${duration(seconds)}.${Math.floor((seconds % 1) * 10)}`;
}
