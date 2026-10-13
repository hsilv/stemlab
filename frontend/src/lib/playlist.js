import { get, writable } from "svelte/store";
import { api } from "./api.js";

function empty() {
  return {
    folder: "",
    parent: null,
    directories: [],
    pinned: null,
    held: [],
    scanId: null,
    status: "",
    done: 0,
    total: 0,
    current: null,
    tracks: [],
    unread: [],
    order: [],
    message: "",
    ordering: false,
    scanned: "",
  };
}

const state = writable(empty());

export const playlist = { subscribe: state.subscribe };

let scanToken = 0;
let orderToken = 0;

function patch(partial) {
  state.update((current) => ({ ...current, ...partial }));
}

function errorText(error) {
  return error instanceof Error ? error.message : "Request failed.";
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function audioSrc(path) {
  return `/api/playlist/audio?${new URLSearchParams({ path })}`;
}

let choosingFolder = false;

export async function chooseFolder() {
  if (choosingFolder || get(state).status === "running") return null;
  choosingFolder = true;
  const previous = get(state).folder;
  patch({ message: "" });
  try {
    const body = await api("/api/playlist/pick", { method: "POST" });
    if (!body || body.cancelled || typeof body.path !== "string" || !body.path) return null;
    patch({ folder: body.path, message: "" });
    void scan();
    return body.path;
  } catch (error) {
    if (get(state).folder !== previous) patch({ folder: previous });
    patch({ message: errorText(error) });
    return null;
  } finally {
    choosingFolder = false;
  }
}

async function reorder() {
  const token = ++orderToken;
  const scan = scanToken;
  const current = get(state);
  patch({ ordering: true });
  try {
    const body = await api("/api/playlist/order", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tracks: current.tracks,
        pinned: current.pinned,
        held: current.held,
      }),
    });
    if (token !== orderToken || scan !== scanToken) return "stale";
    patch({ order: Array.isArray(body.order) ? body.order : [], ordering: false, message: "" });
    return "ok";
  } catch (error) {
    if (token !== orderToken || scan !== scanToken) return "stale";
    patch({ ordering: false, message: errorText(error) });
    return "error";
  }
}

async function finish(body, token) {
  if (token !== scanToken) return;
  const tracks = Array.isArray(body.tracks) ? body.tracks : [];
  const unread = Array.isArray(body.unread) ? body.unread : [];
  const paths = new Set(tracks.map((track) => track.path));
  const current = get(state);
  patch({
    status: "completed",
    done: body.done ?? 0,
    total: body.total ?? 0,
    current: null,
    tracks,
    unread,
    order: [],
    held: current.held.filter((item) => paths.has(item)),
    pinned: paths.has(current.pinned) ? current.pinned : null,
  });
  if (tracks.length) await reorder();
}

async function poll(id, token) {
  while (token === scanToken) {
    await wait(400);
    if (token !== scanToken) return;
    let body;
    try {
      body = await api(`/api/playlist/scans/${id}`);
    } catch (error) {
      if (token !== scanToken) return;
      patch({ status: "failed", message: errorText(error), current: null });
      return;
    }
    if (token !== scanToken) return;
    if (body.status === "running") {
      patch({
        status: "running",
        done: body.done ?? 0,
        total: body.total ?? 0,
        current: body.current ?? null,
      });
      continue;
    }
    if (body.status === "completed") {
      await finish(body, token);
      return;
    }
    if (body.status === "cancelled") {
      patch({
        status: "cancelled",
        done: body.done ?? 0,
        total: body.total ?? 0,
        current: null,
        message: "",
      });
      return;
    }
    patch({
      status: "failed",
      done: body.done ?? 0,
      total: body.total ?? 0,
      current: null,
    });
    return;
  }
}

export async function scan() {
  const current = get(state);
  const folder = current.folder;
  if (!folder || current.status === "running") return;
  const sameFolder = folder === current.scanned;
  scanToken += 1;
  const token = scanToken;
  patch({
    message: "",
    status: "running",
    done: 0,
    total: 0,
    current: null,
    tracks: [],
    unread: [],
    order: [],
    scanId: null,
    ordering: false,
    scanned: folder,
    pinned: sameFolder ? current.pinned : null,
    held: sameFolder ? current.held : [],
  });
  try {
    const body = await api("/api/playlist/scans", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: folder }),
    });
    if (token !== scanToken) return;
    patch({
      scanId: body.id ?? null,
      status: body.status ?? "running",
      done: body.done ?? 0,
      total: body.total ?? 0,
    });
    if (!body.id) {
      patch({ status: "failed", message: "The scan did not start." });
      return;
    }
    if ((body.status ?? "running") === "running") await poll(body.id, token);
    else if (body.status === "completed") await finish(body, token);
    else if (body.status === "cancelled") patch({ status: "cancelled", current: null });
    else patch({ status: "failed", current: null });
  } catch (error) {
    if (token !== scanToken) return;
    patch({ status: "failed", message: errorText(error), current: null });
  }
}

export async function cancelScan() {
  const current = get(state);
  if (current.status !== "running" || !current.scanId) return;
  const id = current.scanId;
  scanToken += 1;
  const token = scanToken;
  try {
    const body = await api(`/api/playlist/scans/${id}`, { method: "DELETE" });
    if (token !== scanToken) return;
    if (body?.status === "completed") {
      await finish(body, token);
      return;
    }
    patch({
      status: "cancelled",
      done: body?.done ?? current.done,
      total: body?.total ?? current.total,
      current: null,
      message: "",
    });
  } catch (error) {
    if (token !== scanToken) return;
    patch({ message: errorText(error) });
    poll(id, token);
  }
}

export async function pinTrack(path) {
  const previous = get(state).pinned;
  if (previous === path || get(state).ordering) return;
  patch({ pinned: path });
  const result = await reorder();
  if (result === "error" && get(state).pinned === path) patch({ pinned: previous });
}

export async function removeTrack(path) {
  const current = get(state);
  if (current.ordering || current.held.includes(path)) return;
  const previousHeld = current.held;
  const previousPinned = current.pinned;
  patch({
    held: [...current.held, path],
    pinned: current.pinned === path ? null : current.pinned,
  });
  const result = await reorder();
  if (result === "error" && get(state).held.at(-1) === path) {
    patch({ held: previousHeld, pinned: previousPinned });
  }
}

export async function restoreTrack(path) {
  const current = get(state);
  if (current.ordering || !current.held.includes(path)) return;
  const previousHeld = current.held;
  patch({ held: current.held.filter((item) => item !== path) });
  const result = await reorder();
  if (result === "error" && !get(state).held.includes(path)) patch({ held: previousHeld });
}
