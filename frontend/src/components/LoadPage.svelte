<script>
  import "./LoadPage.css";
  import DeckWave from "./DeckWave.svelte";
  import { choose } from "../lib/deck.js";
  import { readingLine } from "../lib/format.js";
  import { beginAnalysis, resetAnalysis } from "../lib/jobs.js";
  import { setPreviewVolume } from "../lib/section.js";
  import { analysisSettled, goStems } from "../lib/nav.js";
  import { session } from "../lib/state.svelte.js";

  let dragging = $state(false);
  let picking = $state(false);
  let playing = $state(false);
  let player = $state(null);
  let previousFileKey = "";
  let pickToken = 0;
  const settled = $derived(analysisSettled());
  const keyText = $derived(readingLine(session.bpm, session.camelot, session.keyName));
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

  $effect(() => {
    const file = session.file;
    const key = file ? `${file.name}:${file.size}:${file.lastModified}` : "";
    if (key === previousFileKey) return;
    previousFileKey = key;
    pickToken += 1;
    stopFollow();
    if (!key) {
      picking = false;
      playing = false;
      resetAnalysis();
      return;
    }
    const token = pickToken;
    picking = false;
    playing = false;
    requestAnimationFrame(() => {
      if (token === pickToken) picking = true;
    });
    beginAnalysis(file);
  });

  let followFrame = 0;

  function stopFollow() {
    if (!followFrame) return;
    cancelAnimationFrame(followFrame);
    followFrame = 0;
  }

  function startFollow() {
    stopFollow();
    const step = () => {
      const audio = player;
      if (!audio || audio.paused || audio.ended) {
        followFrame = 0;
        return;
      }
      session.needle = audio.currentTime;
      followFrame = requestAnimationFrame(step);
    };
    followFrame = requestAnimationFrame(step);
  }

  function togglePlay() {
    if (!player) return;
    if (player.paused) {
      document.querySelectorAll("audio").forEach((other) => {
        if (other !== player) other.pause();
      });
      player.play();
    } else player.pause();
  }

  function follow(event) {
    session.needle = event.currentTarget.currentTime;
  }

  function seek(time) {
    session.needle = time;
    if (player && Number.isFinite(time)) player.currentTime = time;
  }

  function placeDownbeat(time) {
    const limit = session.wave?.duration ?? 0;
    session.downbeat = Math.min(limit || time, Math.max(0, time));
    session.downbeatArmed = false;
  }

  function rememberPlace(event) {
    if (session.needle) event.currentTarget.currentTime = session.needle;
  }

  $effect(() => {
    const level = session.volume;
    if (player) player.volume = level;
  });
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
    <label
      class="button file-label"
      class:next={!session.file}
      class:primary={!session.file}
      class:picking
      >Choose a file<input
        id="file"
        type="file"
        accept=".wav,.mp3,audio/wav,audio/x-wav,audio/mpeg"
        disabled={session.uploading}
        onchange={(event) => choose(event.currentTarget.files?.[0])}
      /></label
    >
    </div>
    {#if session.file && !settled}
      <p id="analysis-stage" class="note" role="status">{session.analysisStage}</p>
    {/if}
    {#if session.step === "load" && session.file && settled && session.wave}
      <section class="deck" aria-label="Beat grid">
        {#if keyText}
          <p id="reading" class="reading">{keyText}</p>
        {/if}
        {#if session.downbeat != null}
          <p id="downbeat" class="note">Downbeat {session.downbeat.toFixed(2)}</p>
        {/if}
        {#if session.analysisWarning}
          <p id="analysis-warning" class="note">{session.analysisWarning}</p>
        {/if}
        <div class="deck-actions">
          <button
            type="button"
            id="deck-play"
            disabled={!session.audioUrl}
            onclick={togglePlay}>{playing ? "Pause" : "Play"}</button
          >
          {#if session.bpm != null}
            <button
              type="button"
              id="set-downbeat"
              aria-pressed={session.downbeatArmed}
              onclick={() => (session.downbeatArmed = !session.downbeatArmed)}
              >Set downbeat</button
            >
          {/if}
        </div>
        <DeckWave
          peaks={session.wave.peaks}
          samples={session.wave.samples}
          sampleRate={session.wave.sampleRate}
          scale={session.wave.scale}
          duration={session.wave.duration}
          bpm={session.bpm}
          downbeat={session.downbeat}
          needle={session.needle}
          zoom={session.zoom}
          volume={session.volume}
          armed={session.downbeatArmed}
          onseek={seek}
          onzoom={(level) => (session.zoom = level)}
          onvolume={setPreviewVolume}
          ondownbeat={placeDownbeat}
        />
        {#if session.audioUrl}
          <audio
            id="deck-audio"
            bind:this={player}
            src={session.audioUrl}
            hidden
            onplay={() => {
              playing = true;
              startFollow();
            }}
            onpause={(event) => {
              playing = false;
              stopFollow();
              follow(event);
            }}
            onended={(event) => {
              playing = false;
              stopFollow();
              follow(event);
            }}
            ontimeupdate={follow}
            onseeked={follow}
            onloadedmetadata={rememberPlace}
          ></audio>
        {/if}
      </section>
    {/if}
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
      class:primary={!!session.file && !session.uploading && settled}
      disabled={!session.file || session.uploading || !settled}
      onclick={goStems}>Choose stems</button
    >
  </div>
</div>
