<script>
  import "./Crate.css";
  import { duration, stamp } from "../lib/format.js";
  import { modeNames } from "../lib/labels.js";
  import { openJob } from "../lib/nav.js";
  import { extendHint, groupSongs, rangeHint } from "../lib/songs.js";
  import { session } from "../lib/state.svelte.js";

  // Songs the listener opened or closed by hand; the song with the selected edit is always open.
  let toggled = $state({});
  const songs = $derived(groupSongs(session.rows));

  function isOpen(song) {
    const holdsSelection = song.edits.some((edit) => edit.id === session.selectedId);
    return holdsSelection || (toggled[song.key] ?? false);
  }

  function toggle(song) {
    toggled[song.key] = !isOpen(song);
  }

  const tempo = (row) => (row.bpm != null && row.bpm !== "" ? Number(row.bpm).toFixed(1) : "");

  function describe(row) {
    return `${modeNames[row.mode] || "All stems"}${rangeHint(row)}${extendHint(row)}`;
  }
</script>

<aside class="crate" aria-label="Crate">
  <div class="section-heading">
    <h2>Crate</h2>
    <span id="count">{songs.length}</span>
  </div>
  <div class="crate-columns" aria-hidden="true">
    <span>Title</span><span>BPM</span><span>Key</span>
  </div>
  <div id="history">
    {#if session.loaded && !session.rows.length}
      <p class="note">The crate is empty.</p>
    {/if}
    {#each songs as song (song.key)}
      {#if song.edits.length === 1}
        {@const row = song.edits[0]}
        <button
          type="button"
          class="track"
          class:selected={row.id === session.selectedId}
          aria-pressed={row.id === session.selectedId}
          onclick={() => openJob(row.id)}
        >
          <strong>{row.filename}</strong>
          <small>
            <i class="dot {row.status}" aria-hidden="true"></i>
            {duration(row.duration)} · {row.status} · {describe(row)}
          </small>
          <span class="cell">{tempo(row)}</span>
          <span class="cell key">{row.camelot ?? ""}</span>
        </button>
      {:else}
        <div class="song">
          <button
            type="button"
            class="track song-head"
            aria-expanded={isOpen(song)}
            onclick={() => toggle(song)}
          >
            <strong>{song.filename}</strong>
            <small>{duration(song.edits[0].duration)} · {song.edits.length} edits</small>
            <span class="cell">{tempo(song.edits[0])}</span>
            <span class="cell key">{song.edits[0].camelot ?? ""}</span>
          </button>
          {#if isOpen(song)}
            {#each song.edits as row (row.id)}
              <button
                type="button"
                class="track edit"
                class:selected={row.id === session.selectedId}
                aria-pressed={row.id === session.selectedId}
                onclick={() => openJob(row.id)}
              >
                <strong>{describe(row)}</strong>
                <small>{stamp(row.created)} · {row.status}</small>
              </button>
            {/each}
          {/if}
        </div>
      {/if}
    {/each}
  </div>
</aside>
