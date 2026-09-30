const BEATS_PER_BAR = 4;
const MAX_LINES = 20000;

export function beatInterval(bpm) {
  if (typeof bpm !== "number" || !Number.isFinite(bpm) || bpm <= 0) return null;
  return 60 / bpm;
}

function phase(bpm, downbeat) {
  const interval = beatInterval(bpm);
  if (interval == null || typeof downbeat !== "number" || !Number.isFinite(downbeat))
    return null;
  return { interval, downbeat };
}

function nearestStep(time, origin, step) {
  // A point halfway between two lines resolves toward the later one.
  return origin + Math.round((time - origin) / step) * step;
}

export function nearestBeat(time, bpm, downbeat) {
  const grid = phase(bpm, downbeat);
  if (!grid || typeof time !== "number" || !Number.isFinite(time)) return time;
  return nearestStep(time, grid.downbeat, grid.interval);
}

export function snapToBar(time, bpm, downbeat) {
  const grid = phase(bpm, downbeat);
  if (!grid || typeof time !== "number" || !Number.isFinite(time)) return time;
  return nearestStep(time, grid.downbeat, grid.interval * BEATS_PER_BAR);
}

function lineTimes(bpm, downbeat, start, end, beatsPerLine) {
  const grid = phase(bpm, downbeat);
  if (!grid || !Number.isFinite(start) || !Number.isFinite(end) || end < start) return [];
  const step = grid.interval * beatsPerLine;
  const first = Math.ceil((start - grid.downbeat) / step - 1e-9);
  const last = Math.floor((end - grid.downbeat) / step + 1e-9);
  if (last - first > MAX_LINES) return [];
  const times = [];
  for (let index = first; index <= last; index += 1)
    times.push(grid.downbeat + index * step);
  return times;
}

export function beatLines(bpm, downbeat, start, end) {
  return lineTimes(bpm, downbeat, start, end, 1);
}

export function barLines(bpm, downbeat, start, end) {
  return lineTimes(bpm, downbeat, start, end, BEATS_PER_BAR);
}
