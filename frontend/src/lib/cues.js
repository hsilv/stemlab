const byTime = (a, b) => a.time - b.time;

export async function wavCues(file) {
  const read = async (from, length) =>
    new DataView(await file.slice(from, from + length).arrayBuffer());
  const text = (view, from, length) =>
    String.fromCharCode(...new Uint8Array(view.buffer, from, length));
  let rate = 0;
  const points = new Map();
  const labels = new Map();
  const header = await read(0, 12);
  if (header.byteLength < 12 || text(header, 0, 4) !== "RIFF") return [];
  for (let offset = 12; offset + 8 <= file.size; ) {
    const head = await read(offset, 8);
    const id = text(head, 0, 4);
    const size = head.getUint32(4, true);
    const body = offset + 8;
    if (id === "fmt ") rate = (await read(body + 4, 4)).getUint32(0, true);
    if (id === "cue ") {
      const view = await read(body, size);
      for (let i = 0; i < view.getUint32(0, true); i++)
        points.set(
          view.getUint32(4 + i * 24, true),
          view.getUint32(4 + i * 24 + 20, true),
        );
    }
    if (id === "LIST" && text(await read(body, 4), 0, 4) === "adtl") {
      const list = await read(body + 4, size - 4);
      for (let at = 0; at + 8 <= list.byteLength; ) {
        const length = list.getUint32(at + 4, true);
        if (text(list, at, 4) === "labl")
          labels.set(
            list.getUint32(at + 8, true),
            text(list, at + 12, length - 4).replace(/\0.*$/s, ""),
          );
        at += 8 + length + (length & 1);
      }
    }
    offset = body + size + (size & 1);
  }
  if (!rate) return [];
  return [...points]
    .map(([id, sample], index) => ({
      label: labels.get(id) || `Cue ${index + 1}`,
      time: sample / rate,
    }))
    .sort(byTime);
}

export function rekordboxCues(xml, fileName) {
  const doc = new DOMParser().parseFromString(xml, "application/xml");
  const track = [...doc.querySelectorAll("TRACK")].find(
    (element) =>
      decodeURIComponent(element.getAttribute("Location") || "")
        .split("/")
        .pop() === fileName,
  );
  if (!track) return [];
  return [...track.querySelectorAll("POSITION_MARK")]
    .filter((mark) => Number(mark.getAttribute("Num")) >= 0)
    .map((mark) => ({
      label:
        mark.getAttribute("Name") ||
        `Hot cue ${Number(mark.getAttribute("Num")) + 1}`,
      time: Number(mark.getAttribute("Start")),
    }))
    .sort(byTime);
}

globalThis.wavCues = wavCues;
globalThis.rekordboxCues = rekordboxCues;
