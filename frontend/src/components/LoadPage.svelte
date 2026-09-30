<script>
  import "./LoadPage.css";
  import { choose } from "../lib/deck.js";
  import { goStems } from "../lib/nav.js";
  import { session } from "../lib/state.svelte.js";

  let dragging = $state(false);
  const rows = $derived(
    session.tags
      ? [
          ["Album", session.tags.album],
          ["Genre", session.tags.genre],
          ["Year", session.tags.year],
        ].filter(([, value]) => value)
      : [],
  );
  const trackTitle = $derived(session.tags?.title || session.file?.name || "");

  function hold(event) {
    event.preventDefault();
    dragging = true;
  }

  function release(event) {
    event.preventDefault();
    dragging = false;
  }

  function drop(event) {
    release(event);
    choose(event.dataTransfer?.files[0]);
  }
</script>

<div
  id="page-load"
  class="page"
  class:has-file={!!session.file}
  class:is-on={session.step === "load"}
  class:back={session.motion === "back"}
  hidden={session.step !== "load"}
>
  <div
    id="dropzone"
    class="dropzone"
    class:dragging
    ondragenter={hold}
    ondragover={hold}
    ondragleave={release}
    ondrop={drop}
  >
    <div class="drop-copy">
      <h2 id="upload-title">Drop a WAV or MP3 on the deck</h2>
      <p id="limits">{session.limits}</p>
      <p id="chosen" class="chosen" aria-live="polite">{session.chosenLabel}</p>
    </div>
    <label class="button file-label"
      >Choose a file<input
        id="file"
        type="file"
        accept=".wav,.mp3,audio/wav,audio/x-wav,audio/mpeg"
        disabled={session.uploading}
        onchange={(event) => choose(event.currentTarget.files?.[0])}
      /></label
    >
    </div>
    {#if session.file && session.tags}
      {#key `${session.file.name}:${session.file.size}:${session.file.lastModified}`}
      <section class="tags" aria-label="Track details">
        <figure class="sleeve">
          {#if session.tags.coverUrl}
            <img class="tags-cover" src={session.tags.coverUrl} alt="Album cover" />
          {:else}
            <div class="tags-blank" aria-hidden="true"></div>
          {/if}
        </figure>
        <div class="tags-copy">
          <h2 class="tags-title">{trackTitle}</h2>
          {#if session.tags.artist}
            <p class="tags-artist">{session.tags.artist}</p>
          {/if}
          {#if rows.length}
            <dl>
              {#each rows as [label, value] (label)}
                <div>
                  <dt>{label}</dt>
                  <dd>{value}</dd>
                </div>
              {/each}
            </dl>
          {:else if !session.tags.coverUrl && !session.tags.title && !session.tags.artist}
            <p class="note">No tags in this file.</p>
          {/if}
        </div>
      </section>
      {/key}
    {/if}
    <div class="pager">
    <button
      type="button"
      id="to-stems"
      class="next"
      class:primary={!!session.file && !session.uploading}
      disabled={!session.file || session.uploading}
      onclick={goStems}>Choose stems</button
    >
  </div>
</div>
