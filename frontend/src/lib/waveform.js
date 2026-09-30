export async function waveformOf(file, bins = 1500) {
  const context = new AudioContext();
  try {
    const audio = await context.decodeAudioData(await file.arrayBuffer());
    const peaks = new Float32Array(bins);
    const size = audio.length / bins;
    for (let channel = 0; channel < audio.numberOfChannels; channel++) {
      const samples = audio.getChannelData(channel);
      for (let bin = 0; bin < bins; bin++) {
        const end = Math.floor((bin + 1) * size);
        for (let i = Math.floor(bin * size); i < end; i++)
          peaks[bin] = Math.max(peaks[bin], Math.abs(samples[i]));
      }
    }
    return { peaks, duration: audio.duration };
  } finally {
    context.close();
  }
}

export function drawWaveform(canvas, peaks) {
  const scale = window.devicePixelRatio || 1;
  canvas.width = canvas.clientWidth * scale;
  canvas.height = canvas.clientHeight * scale;
  const paint = canvas.getContext("2d");
  paint.fillStyle = "#d5d3ce";
  const middle = canvas.height / 2;
  const step = canvas.width / peaks.length;
  peaks.forEach((peak, bin) => {
    const height = Math.max(1, peak * canvas.height * 0.9);
    paint.fillRect(
      bin * step,
      middle - height / 2,
      Math.max(1, step - 0.5),
      height,
    );
  });
}
