<script>
  import { choose } from "../lib/deck.js";
  import { goStems } from "../lib/nav.js";
  import { session } from "../lib/state.svelte.js";

  let dragging = $state(false);

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

<div id="page-load" class="page" class:is-on={session.step === "load"} class:back={session.motion === "back"} hidden={session.step !== "load"}>
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
  <div class="pager">
    <button type="button" id="to-stems" disabled={!session.file || session.uploading} onclick={goStems}
      >Choose stems</button
    >
  </div>
</div>
