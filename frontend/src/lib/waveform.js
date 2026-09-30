// Full height is the single tallest bin. Every other bin is that value over the max.
export function peakReference(peaks) {
  let max = 0;
  for (const value of peaks) if (value > max) max = value;
  return max;
}

export function normalizePeaks(peaks) {
  const reference = peakReference(peaks);
  if (!(reference > 0)) return peaks;
  const scaled = new Float32Array(peaks.length);
  for (let bin = 0; bin < peaks.length; bin++) scaled[bin] = peaks[bin] / reference;
  return scaled;
}

function rms(samples, start, end) {
  const count = end - start;
  if (count <= 0) return 0;
  let sum = 0;
  for (let index = start; index < end; index++) {
    const sample = samples[index];
    sum += sample * sample;
  }
  return Math.sqrt(sum / count);
}

function mixMono(audio) {
  const mono = new Float32Array(audio.length);
  const channels = audio.numberOfChannels;
  for (let channel = 0; channel < channels; channel++) {
    const data = audio.getChannelData(channel);
    for (let index = 0; index < data.length; index++) mono[index] += data[index];
  }
  if (channels > 1) {
    for (let index = 0; index < mono.length; index++) mono[index] /= channels;
  }
  return mono;
}

function rmsColumns(samples, sampleRate, start, end, columns, scale) {
  const out = new Float32Array(columns);
  const span = end - start;
  const last = samples.length;
  const divisor = scale > 0 ? scale : 1;
  for (let column = 0; column < columns; column++) {
    const fromTime = start + (column / columns) * span;
    const toTime = start + ((column + 1) / columns) * span;
    const from = Math.max(0, Math.min(last, Math.floor(fromTime * sampleRate)));
    const to = Math.max(from, Math.min(last, Math.floor(toTime * sampleRate)));
    out[column] = rms(samples, from, to) / divisor;
  }
  return out;
}

const detailCache = new WeakMap();

function covers(cache, start, end, columns) {
  if (!cache || cache.start > start || cache.end < end) return false;
  return cache.density + 1e-6 >= columns / (end - start);
}

function readCached(cache, start, end, columns) {
  const out = new Float32Array(columns);
  const span = cache.end - cache.start;
  const count = cache.peaks.length;
  const width = end - start;
  for (let column = 0; column < columns; column++) {
    const fromTime = start + (column / columns) * width;
    const toTime = start + ((column + 1) / columns) * width;
    const first = Math.floor(((fromTime - cache.start) / span) * count);
    const last = Math.ceil(((toTime - cache.start) / span) * count);
    let peak = 0;
    for (let index = Math.max(0, first); index < Math.min(count, Math.max(first + 1, last)); index++) {
      if (cache.peaks[index] > peak) peak = cache.peaks[index];
    }
    out[column] = peak;
  }
  return out;
}

// Finer peaks for the visible span. The coarse overview is enough until a
// column would be wider than one pixel; the extra samples stay on that span.
export function refinePeaks(wave, start, end, columns) {
  const samples = wave?.samples;
  const sampleRate = wave?.sampleRate;
  if (!samples || !(sampleRate > 0) || !(columns > 0) || !(end > start)) return null;
  const span = end - start;
  const coarse = (wave.peaks?.length ?? 0) * (span / wave.duration);
  if (coarse >= columns) return null;
  const density = columns / span;
  const cached = detailCache.get(samples);
  if (covers(cached, start, end, columns)) return readCached(cached, start, end, columns);
  // One peak per pixel on screen. A wider cache is kept only while that
  // density still fits, so scrolling reuses it and zooming in builds again.
  const room = Math.floor(8192 / density);
  const extra = Math.max(0, (Math.min(room, span * 3) - span) / 2);
  const from = Math.max(0, start - extra);
  const to = Math.min(wave.duration, end + extra);
  const width = Math.max(columns, Math.round(density * (to - from)));
  const peaks = rmsColumns(samples, sampleRate, from, to, width, wave.scale);
  const next = { start: from, end: to, peaks, density };
  detailCache.set(samples, next);
  return readCached(next, start, end, columns);
}

export async function waveformOf(file, bins = 1500) {
  const context = new AudioContext();
  try {
    const audio = await context.decodeAudioData(await file.arrayBuffer());
    const samples = mixMono(audio);
    const raw = new Float32Array(bins);
    const size = samples.length / bins;
    for (let bin = 0; bin < bins; bin++) {
      const start = Math.floor(bin * size);
      const end = Math.floor((bin + 1) * size);
      raw[bin] = rms(samples, start, end);
    }
    const scale = peakReference(raw) || 1;
    return {
      peaks: normalizePeaks(raw),
      duration: audio.duration,
      samples,
      sampleRate: audio.sampleRate,
      scale,
    };
  } finally {
    context.close();
  }
}
