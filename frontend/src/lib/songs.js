// Jobs that edit the same uploaded song, newest song first. A job from before edits were
// grouped has no song_id and is its own song.
export function groupSongs(rows) {
  const songs = new Map();
  for (const row of rows) {
    const key = row.song_id ?? row.id;
    if (!songs.has(key)) songs.set(key, { key, filename: row.filename, edits: [] });
    songs.get(key).edits.push(row);
  }
  return [...songs.values()];
}

export function rangeHint(row) {
  const count = row.ranges?.length ?? 0;
  if (!count) return "";
  return count === 1 ? " · section" : ` · ${count} ranges`;
}

export function extendHint(row) {
  if (row.mode !== "extend" || !row.extend) return "";
  if (row.extend.operations) return ` · manual, ${row.extend.operations.length}`;
  const { intro, outro } = row.extend;
  return ` · ${intro ? intro.bars : 0}+${outro ? outro.bars : 0} bars`;
}
