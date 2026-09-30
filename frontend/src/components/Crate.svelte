<script>
  import { duration } from "../lib/format.js";
  import { modeNames } from "../lib/labels.js";
  import { openJob } from "../lib/nav.js";
  import { session } from "../lib/state.svelte.js";
</script>

<aside class="crate" aria-label="Crate">
  <div class="section-heading">
    <h2>Crate</h2>
    <span id="count">{session.rows.length}</span>
  </div>
  <div id="history">
    {#if session.loaded && !session.rows.length}
      <p class="note">The crate is empty.</p>
    {/if}
    {#each session.rows as row (row.id)}
      <button
        type="button"
        class="track"
        class:selected={row.id === session.selectedId}
        aria-pressed={row.id === session.selectedId}
        onclick={() => openJob(row.id)}
      >
        <strong>{row.filename}</strong>
        <small
          >{duration(row.duration)} · {row.status} · {modeNames[row.mode] ||
            "All stems"}</small
        >
      </button>
    {/each}
  </div>
</aside>
