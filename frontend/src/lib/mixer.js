// Which lanes are heard: only the soloed ones when any lane is soloed, otherwise every lane
// that is not muted.
export function audibleLanes(ids, muted, soloed) {
  if (soloed.length) return new Set(ids.filter((id) => soloed.includes(id)));
  return new Set(ids.filter((id) => !muted.includes(id)));
}

// The loudest sample in each of `columns` equal slices of a channel.
export function laneColumns(samples, columns) {
  const out = new Float32Array(columns);
  const size = samples.length / columns;
  for (let column = 0; column < columns; column++) {
    const end = Math.floor((column + 1) * size);
    let peak = 0;
    for (let index = Math.floor(column * size); index < end; index++) {
      const value = Math.abs(samples[index]);
      if (value > peak) peak = value;
    }
    out[column] = peak;
  }
  return out;
}

// Lanes share one scale, so a quiet stem looks quiet next to a loud one.
export function sharedScale(lanes) {
  let loudest = 0;
  for (const lane of lanes) for (const value of lane) if (value > loudest) loudest = value;
  return loudest > 0 ? lanes.map((lane) => lane.map((value) => value / loudest)) : lanes;
}
