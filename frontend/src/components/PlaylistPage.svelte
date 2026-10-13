<script>
  import "./PlaylistPage.css";
  import { moodLine, readingLine } from "../lib/format.js";
  import {
    audioSrc,
    cancelScan,
    chooseFolder,
    pinTrack,
    playlist,
    removeTrack,
    restoreTrack,
    scan,
  } from "../lib/playlist.js";

  let { active = false } = $props();
  let state = $state({
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
  });
  let player = $state(null);
  let selected = $state("");
  let playing = $state(false);
  let choosing = $state(false);

  const leftOut = $derived(
    state.held
      .map((path) => state.tracks.find((track) => track.path === path))
      .filter(Boolean),
  );
  const nowPlaying = $derived(
    state.order.find((row) => row.path === selected)?.filename ||
      state.tracks.find((track) => track.path === selected)?.filename ||
      "",
  );
  const folderEmpty = $derived(
    state.status === "completed" &&
      !state.order.length &&
      !state.unread.length &&
      !leftOut.length,
  );
  const busy = $derived(choosing || state.status === "running");

  function copy(value) {
    return {
      ...value,
      directories: [...value.directories],
      held: [...value.held],
      tracks: [...value.tracks],
      unread: [...value.unread],
      order: [...value.order],
    };
  }

  function line(row) {
    const parts = [];
    const reading = readingLine(row.bpm, row.camelot, row.key_name);
    if (reading) parts.push(reading);
    const mood = moodLine(row.valence, row.energy);
    if (mood) parts.push(mood);
    if (row.break) parts.push("Break");
    if (row.band === "half") parts.push("Half");
    if (row.band === "double") parts.push("Double");
    return parts.join(" · ");
  }

  function pauseOthers() {
    document.querySelectorAll("audio").forEach((other) => {
      if (other !== player) other.pause();
    });
  }

  function playRow(path) {
    if (!player) return;
    selected = path;
    const url = audioSrc(path);
    const absolute = new URL(url, window.location.href).href;
    const fromStart = () => {
      player.currentTime = 0;
    };
    if (player.src === absolute && player.readyState >= 1) {
      fromStart();
      player.play().catch(() => {});
      return;
    }
    // preload="none" does not fetch until play(), and play() has to stay in this click.
    player.src = url;
    player.addEventListener("loadedmetadata", fromStart, { once: true });
    player.play().catch(() => {});
  }

  function clearPlayer() {
    selected = "";
    playing = false;
    if (!player) return;
    player.pause();
    if (player.getAttribute("src")) {
      player.removeAttribute("src");
      player.load();
    }
  }

  async function onRemove(path) {
    if (selected === path) clearPlayer();
    await removeTrack(path);
  }

  $effect(() => {
    return playlist.subscribe((value) => {
      state = copy(value);
    });
  });

  $effect(() => {
    if (active) return;
    player?.pause();
  });

  $effect(() => {
    if (state.status !== "running") return;
    if (!selected && !player?.getAttribute("src")) return;
    clearPlayer();
  });

  function folderLabel(path) {
    if (!path || path === "/") return path || "";
    const trimmed = path.replace(/\/+$/, "");
    const slash = trimmed.lastIndexOf("/");
    return slash >= 0 ? trimmed.slice(slash + 1) : trimmed;
  }

  function choose() {
    if (busy) return;
    choosing = true;
    chooseFolder().finally(() => {
      choosing = false;
    });
  }
</script>

<div id="page-playlist" class="page" hidden={!active}>
  <div class="page-head">
    <h2>Playlist.</h2>
    <p class="note">Choose a folder. The scan reads the WAV and MP3 files in it.</p>
  </div>

  <section class="plate folder-card" aria-labelledby="folder-title">
    <div class="page-head">
      <h2 id="folder-title">Folder.</h2>
      {#if state.folder}
        <p class="folder-name">{folderLabel(state.folder)}</p>
        <p class="folder-path">{state.folder}</p>
      {:else}
        <p class="note">No folder chosen.</p>
      {/if}
    </div>
    <div class="folder-actions">
      <button type="button" id="playlist-choose" class="primary" disabled={busy} onclick={choose}
        >Choose a folder</button
      >
    </div>
    {#if choosing}
      <p class="note" role="status">The folder dialog is open.</p>
    {/if}
    <p id="playlist-message" class="error" role="alert" hidden={!state.message || state.status === "failed"}>
      {state.message}
    </p>
  </section>

  <div class="player">
    {#if nowPlaying}
      <p class="note">{nowPlaying}</p>
    {/if}
    <audio
      id="playlist-audio"
      bind:this={player}
      controls
      preload="none"
      aria-label={nowPlaying ? `${nowPlaying} preview` : "Playlist preview"}
      onplay={() => {
        playing = true;
        pauseOthers();
      }}
      onpause={() => (playing = false)}
      onended={() => (playing = false)}
    ></audio>
  </div>

  {#if state.status === "running"}
    <div class="scan-status" role="status">
      <p class="scan-count">Reading {state.done} / {state.total}</p>
      {#if state.total > 0}
        <progress
          id="scan-progress"
          max={state.total}
          value={state.done}
          aria-valuetext="{state.done} of {state.total} files"
        ></progress>
      {/if}
      {#if state.current}
        <p class="note">{state.current}</p>
      {/if}
      <button type="button" id="playlist-cancel" onclick={cancelScan}>Cancel</button>
    </div>
  {:else if state.status === "failed"}
    <div class="block" role="alert">
      <p class="error">{state.message || "The scan failed."}</p>
      <button type="button" class="primary" onclick={scan}>Scan again</button>
    </div>
  {:else if state.status === "cancelled"}
    <div class="block" role="status">
      <p>Scan cancelled.</p>
      <button type="button" class="primary" onclick={scan}>Scan again</button>
    </div>
  {:else if state.status === "completed"}
    {#if state.scanned && state.scanned !== state.folder}
      <p class="note">This order is from {state.scanned}.</p>
    {/if}
    {#if folderEmpty}
      <p class="note">No WAV or MP3 files in this folder.</p>
    {/if}
    <section class="block" aria-labelledby="order-title">
      <div class="list-head">
        <h3 id="order-title">Order</h3>
        <span>{state.order.length}</span>
      </div>
      {#if state.order.length}
        <ul class="rows">
          {#each state.order as row (row.path)}
            <li class="playlist-row" class:is-playing={playing && selected === row.path}>
              <button
                type="button"
                class="row-play"
                aria-current={selected === row.path ? "true" : undefined}
                aria-label={`Play ${row.filename} from the start`}
                onclick={() => playRow(row.path)}
              >
                <strong>{row.filename}</strong>
                <small>{line(row)}</small>
              </button>
              <div class="row-actions">
                <button
                  type="button"
                  aria-pressed={state.pinned === row.path}
                  disabled={state.ordering}
                  onclick={() => pinTrack(row.path)}>Pin</button
                >
                <button
                  type="button"
                  disabled={state.ordering}
                  onclick={() => onRemove(row.path)}>Remove</button
                >
              </div>
            </li>
          {/each}
        </ul>
      {:else if !folderEmpty}
        <p class="note">No tracks to play.</p>
      {/if}
    </section>
    {#if state.unread.length}
      <section class="block" aria-labelledby="unread-title">
        <div class="list-head">
          <h3 id="unread-title">No reading</h3>
          <span>{state.unread.length}</span>
        </div>
        <ul class="rows">
          {#each state.unread as row (row.path)}
            <li class="playlist-row">
              <div class="row-copy">
                <strong>{row.filename}</strong>
                <small>{row.reason}</small>
              </div>
            </li>
          {/each}
        </ul>
      </section>
    {/if}
    {#if leftOut.length}
      <section class="block" aria-labelledby="held-title">
        <div class="list-head">
          <h3 id="held-title">Left out</h3>
          <span>{leftOut.length}</span>
        </div>
        <ul class="rows">
          {#each leftOut as row (row.path)}
            <li class="playlist-row">
              <div class="row-copy">
                <strong>{row.filename}</strong>
                <small>{readingLine(row.bpm, row.camelot, row.key_name)}</small>
              </div>
              <div class="row-actions">
                <button
                  type="button"
                  disabled={state.ordering}
                  onclick={() => restoreTrack(row.path)}>Restore</button
                >
              </div>
            </li>
          {/each}
        </ul>
      </section>
    {/if}
  {:else}
    <p class="note">Choose a folder to order its WAV and MP3 files.</p>
  {/if}
</div>
