import { api } from "./api.js";
import { session } from "./state.svelte.js";

const SIDES = ["source", "target"];

function crateRef(side) {
  return side.job && side.stem ? `job:${side.job}:${side.stem}` : "";
}

export function refOf(side) {
  return side.kind === "job" ? crateRef(side) : side.ref;
}

// Read what the chosen file carries; clears the side when nothing is chosen.
export async function loadInfo(side) {
  const ref = refOf(side);
  side.info = null;
  side.error = "";
  if (!ref) return;
  try {
    const info = await api(`/api/tags?${new URLSearchParams({ ref })}`);
    if (refOf(side) === ref) {
      side.info = info;
      side.name = info.name;
    }
  } catch (error) {
    if (refOf(side) === ref) side.error = error.message;
  }
}

// An uploaded file is kept by the server for a while, named by a reference.
export async function stageFile(side, file) {
  side.info = null;
  side.error = "";
  side.ref = "";
  if (!file) return;
  try {
    const response = await fetch(`/api/tags/files?${new URLSearchParams({ filename: file.name })}`, {
      method: "POST",
      body: file,
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok)
      throw new Error(typeof body.detail === "string" ? body.detail : "Could not read that file.");
    side.ref = body.ref;
    await loadInfo(side);
  } catch (error) {
    side.error = error.message;
  }
}

export function problem() {
  const tool = session.tagTool;
  for (const name of SIDES) {
    const side = tool[name];
    if (!refOf(side)) return `Choose the ${name} file.`;
    if (side.error) return side.error;
    if (!side.info) return "Reading the file…";
  }
  if (refOf(tool.source) === refOf(tool.target)) return "The source and the target are the same file.";
  return "";
}

// The title the copy will have, as the server will make it.
export function resultingTitle() {
  const tool = session.tagTool;
  const title = tool.source.info?.tags.title || (tool.source.name || "").replace(/\.[^.]+$/, "");
  const version = tool.version === null ? (tool.target.info?.version ?? "") : tool.version.trim();
  if (!title) return "";
  if (!version || title.toLowerCase().endsWith(`(${version.toLowerCase()})`)) return title;
  return `${title} (${version})`;
}

export async function copyTags() {
  const tool = session.tagTool;
  if (problem() || tool.busy) return;
  tool.busy = true;
  tool.done = "";
  session.message = "";
  try {
    const response = await fetch("/api/tags/copy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source: refOf(tool.source),
        target: refOf(tool.target),
        version: tool.version,
        cover: tool.cover,
      }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(typeof body.detail === "string" ? body.detail : "Could not copy the tags.");
    }
    const name =
      /filename="?([^";]+)"?/.exec(response.headers.get("content-disposition") ?? "")?.[1] ??
      "tagged-copy";
    const link = document.createElement("a");
    link.href = URL.createObjectURL(await response.blob());
    link.download = name;
    link.click();
    URL.revokeObjectURL(link.href);
    tool.done = `Saved ${name}.`;
  } catch (error) {
    session.message = error.message;
  } finally {
    tool.busy = false;
  }
}
