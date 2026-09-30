const GENRES = [
  "Blues",
  "Classic Rock",
  "Country",
  "Dance",
  "Disco",
  "Funk",
  "Grunge",
  "Hip-Hop",
  "Jazz",
  "Metal",
  "New Age",
  "Oldies",
  "Other",
  "Pop",
  "R&B",
  "Rap",
  "Reggae",
  "Rock",
  "Techno",
  "Industrial",
  "Alternative",
  "Ska",
  "Death Metal",
  "Pranks",
  "Soundtrack",
  "Euro-Techno",
  "Ambient",
  "Trip-Hop",
  "Vocal",
  "Jazz+Funk",
  "Fusion",
  "Trance",
  "Classical",
  "Instrumental",
  "Acid",
  "House",
  "Game",
  "Sound Clip",
  "Gospel",
  "Noise",
  "AlternRock",
  "Bass",
  "Soul",
  "Punk",
  "Space",
  "Meditative",
  "Instrumental Pop",
  "Instrumental Rock",
  "Ethnic",
  "Gothic",
  "Darkwave",
  "Techno-Industrial",
  "Electronic",
  "Pop-Folk",
  "Eurodance",
  "Dream",
  "Southern Rock",
  "Comedy",
  "Cult",
  "Gangsta",
  "Top 40",
  "Christian Rap",
  "Pop/Funk",
  "Jungle",
  "Native American",
  "Cabaret",
  "New Wave",
  "Psychedelic",
  "Rave",
  "Showtunes",
  "Trailer",
  "Lo-Fi",
  "Tribal",
  "Acid Punk",
  "Acid Jazz",
  "Polka",
  "Retro",
  "Musical",
  "Rock & Roll",
  "Hard Rock",
];

const EMPTY = {
  title: "",
  artist: "",
  album: "",
  genre: "",
  year: "",
  coverUrl: "",
};

const ascii = (bytes, offset, length) =>
  String.fromCharCode(...bytes.subarray(offset, offset + length));

function synchsafe(bytes, offset) {
  return (
    ((bytes[offset] & 0x7f) << 21) |
    ((bytes[offset + 1] & 0x7f) << 14) |
    ((bytes[offset + 2] & 0x7f) << 7) |
    (bytes[offset + 3] & 0x7f)
  );
}

function uint32(bytes, offset) {
  return (
    ((bytes[offset] << 24) |
      (bytes[offset + 1] << 16) |
      (bytes[offset + 2] << 8) |
      bytes[offset + 3]) >>>
    0
  );
}

function deunsync(bytes) {
  const out = [];
  for (let i = 0; i < bytes.length; i++) {
    out.push(bytes[i]);
    if (bytes[i] === 0xff && bytes[i + 1] === 0x00) i++;
  }
  return Uint8Array.from(out);
}

function decodeText(bytes, encoding) {
  const label = encoding === 0 ? "iso-8859-1" : encoding === 2 ? "utf-16be" : encoding === 3 ? "utf-8" : "utf-16";
  return new TextDecoder(label).decode(bytes);
}

function clean(text) {
  return text.replace(/\0/g, " ").replace(/\s+/g, " ").trim();
}

function parseGenre(value) {
  const text = clean(value);
  const wrapped = /^\((\d+)\)\s*(.*)$/.exec(text);
  if (wrapped) return wrapped[2] || GENRES[Number(wrapped[1])] || text;
  if (/^\d+$/.test(text)) return GENRES[Number(text)] || text;
  return text;
}

function parseYear(value) {
  const text = clean(value);
  const match = /^(\d{4})/.exec(text);
  return match ? match[1] : text;
}

function textAfter(bytes, encoding, start) {
  if (encoding === 1 || encoding === 2) {
    for (let i = start; i + 1 < bytes.length; i += 2) {
      if (bytes[i] === 0 && bytes[i + 1] === 0) return i + 2;
    }
    return bytes.length;
  }
  const end = bytes.indexOf(0, start);
  return end < 0 ? bytes.length : end + 1;
}

function readText(data) {
  if (!data.length) return "";
  return clean(decodeText(data.subarray(1), data[0]));
}

function readPicture(data, version) {
  if (data.length < 4) return null;
  if (version === 2) {
    const encoding = data[0];
    const format = ascii(data, 1, 3).toUpperCase();
    const type = data[4];
    const image = data.subarray(textAfter(data, encoding, 5));
    const mime = format === "PNG" ? "image/png" : "image/jpeg";
    return image.length ? { mime, type, image } : null;
  }
  const encoding = data[0];
  const mimeEnd = data.indexOf(0, 1);
  if (mimeEnd < 0) return null;
  const mime = decodeText(data.subarray(1, mimeEnd), 0) || "image/jpeg";
  const type = data[mimeEnd + 1];
  const image = data.subarray(textAfter(data, encoding, mimeEnd + 2));
  return image.length ? { mime, type, image } : null;
}

function frameBody(data, version, flags) {
  if (version === 4) {
    if (flags[1] & 0x0c) return null;
    let offset = 0;
    if (flags[1] & 0x40) offset += 1;
    if (flags[1] & 0x01) offset += 4;
    return data.subarray(offset);
  }
  if (version === 3 && flags[1] & 0xc0) return null;
  return data;
}

function applyFrame(tags, id, body) {
  if (!body) return;
  if (id === "TIT2") tags.title = readText(body);
  if (id === "TPE1") tags.artist = readText(body);
  if (id === "TALB") tags.album = readText(body);
  if (id === "TCON") tags.genre = parseGenre(readText(body));
  if (id === "TYER" || id === "TDRC") tags.year = parseYear(readText(body));
  if (id === "APIC") {
    const picture = readPicture(body, 3);
    if (picture && (picture.type === 3 || !tags.cover)) tags.cover = picture;
  }
}

function parseId3(bytes) {
  const tags = {};
  if (bytes.length < 10 || ascii(bytes, 0, 3) !== "ID3") return tags;
  const version = bytes[3];
  if (version < 2 || version > 4) return tags;
  let body = bytes.subarray(10, 10 + synchsafe(bytes, 6));
  if (bytes[5] & 0x80) body = deunsync(body);
  if (bytes[5] & 0x40) {
    const size = version === 4 ? synchsafe(body, 0) : 4 + uint32(body, 0);
    body = body.subarray(Math.min(size, body.length));
  }
  const v22 = { TT2: "TIT2", TP1: "TPE1", TAL: "TALB", TCO: "TCON", TYE: "TYER", PIC: "APIC" };
  for (let offset = 0; offset + (version === 2 ? 6 : 10) <= body.length; ) {
    if (body[offset] === 0) break;
    if (version === 2) {
      const raw = ascii(body, offset, 3);
      const size = (body[offset + 3] << 16) | (body[offset + 4] << 8) | body[offset + 5];
      if (!size || offset + 6 + size > body.length) break;
      const id = v22[raw];
      const data = body.subarray(offset + 6, offset + 6 + size);
      if (id === "APIC") {
        const picture = readPicture(data, 2);
        if (picture && (picture.type === 3 || !tags.cover)) tags.cover = picture;
      } else if (id) applyFrame(tags, id, data);
      offset += 6 + size;
      continue;
    }
    const id = ascii(body, offset, 4);
    const size = version === 4 ? synchsafe(body, offset + 4) : uint32(body, offset + 4);
    if (!/^[A-Z0-9]{4}$/.test(id) || !size || offset + 10 + size > body.length) break;
    const data = frameBody(
      body.subarray(offset + 10, offset + 10 + size),
      version,
      [body[offset + 8], body[offset + 9]],
    );
    applyFrame(tags, id, data);
    offset += 10 + size;
  }
  return tags;
}

function readInfo(list, tags) {
  for (let offset = 0; offset + 8 <= list.length; ) {
    const id = ascii(list, offset, 4);
    const size =
      (list[offset + 4] |
        (list[offset + 5] << 8) |
        (list[offset + 6] << 16) |
        (list[offset + 7] << 24)) >>>
      0;
    const text = clean(decodeText(list.subarray(offset + 8, offset + 8 + size), 0));
    if (id === "INAM") tags.title = text;
    if (id === "IART") tags.artist = text;
    if (id === "IPRD") tags.album = text;
    if (id === "IGNR") tags.genre = text;
    if (id === "ICRD") tags.year = parseYear(text);
    offset += 8 + size + (size & 1);
  }
}

async function readWav(file) {
  const tags = {};
  const header = new Uint8Array(await file.slice(0, 12).arrayBuffer());
  if (header.length < 12 || ascii(header, 0, 4) !== "RIFF") return tags;
  for (let offset = 12; offset + 8 <= file.size; ) {
    const head = new DataView(await file.slice(offset, offset + 8).arrayBuffer());
    const id = ascii(new Uint8Array(head.buffer), 0, 4);
    const size = head.getUint32(4, true);
    const bodyAt = offset + 8;
    if (id === "id3 " || id === "ID3 ") {
      Object.assign(tags, parseId3(new Uint8Array(await file.slice(bodyAt, bodyAt + size).arrayBuffer())));
    }
    if (id === "LIST") {
      const list = new Uint8Array(await file.slice(bodyAt, bodyAt + size).arrayBuffer());
      if (ascii(list, 0, 4) === "INFO") readInfo(list.subarray(4), tags);
    }
    offset = bodyAt + size + (size & 1);
  }
  return tags;
}

async function readId3v1(file) {
  if (file.size < 128) return {};
  const bytes = new Uint8Array(await file.slice(file.size - 128).arrayBuffer());
  if (ascii(bytes, 0, 3) !== "TAG") return {};
  const latin1 = (start, length) =>
    clean(decodeText(bytes.subarray(start, start + length), 0)).replace(/\0.*$/, "");
  const genre = bytes[127];
  return {
    title: latin1(3, 30),
    artist: latin1(33, 30),
    album: latin1(63, 30),
    year: latin1(93, 4),
    genre: genre === 255 ? "" : GENRES[genre] || "",
  };
}

function keep(current, next) {
  for (const key of ["title", "artist", "album", "genre", "year", "cover"]) {
    if (!current[key] && next[key]) current[key] = next[key];
  }
}

export async function readTags(file) {
  const tags = {};
  try {
    const head = new Uint8Array(await file.slice(0, 10).arrayBuffer());
    if (ascii(head, 0, 3) === "ID3") {
      const size = synchsafe(head, 6);
      keep(tags, parseId3(new Uint8Array(await file.slice(0, 10 + size).arrayBuffer())));
    } else if (ascii(head, 0, 4) === "RIFF") {
      keep(tags, await readWav(file));
    }
    keep(tags, await readId3v1(file));
  } catch {
    return { ...EMPTY };
  }
  const cover = tags.cover;
  const coverUrl = cover
    ? URL.createObjectURL(new Blob([cover.image], { type: cover.mime || "image/jpeg" }))
    : "";
  return {
    title: tags.title || "",
    artist: tags.artist || "",
    album: tags.album || "",
    genre: tags.genre || "",
    year: tags.year || "",
    coverUrl,
  };
}

globalThis.readTags = readTags;
