<script>
  import "./TrackDetail.css";
  import { duration, readingLine } from "../lib/format.js";
  import { runJobAction } from "../lib/jobs.js";
  import {
    activeStatuses,
    modeNames,
    sourceNames,
  } from "../lib/labels.js";
  import { qualityText, rangeNote, stageValue } from "../lib/plan.js";
  import { session } from "../lib/state.svelte.js";

  const row = $derived(
    session.rows.find((item) => item.id === session.selectedId) ?? null,
  );

  const reading = $derived(
    row ? readingLine(row.bpm, row.camelot, row.key_name) : "",
  );

  function pauseOthers(event) {
    document.querySelectorAll("audio").forEach((other) => {
      if (other !== event.currentTarget) other.pause();
    });
  }
</script>

<section id="detail" class="detail" aria-label="Selected track">
  {#if !row}
    <div class="empty">
      <h2>{session.file ? "Ready to separate." : "Nothing on the deck."}</h2>
      <p>
        {session.file
          ? "Choose an output and separate, or pick a track from the crate."
          : "Load a WAV or MP3, or pick a track from the crate."}
      </p>
    </div>
  {:else}
    {@const value = stageValue(row.stage, row.status)}
    <div class="detail-heading">
      <div>
        <h2>{row.filename}</h2>
        <div class="meta">
          {duration(row.duration)} · {(row.sample_rate / 1000).toFixed(1)} kHz ·
          {row.channels === 1 ? "Mono" : "Stereo"}
        </div>
      </div>
      <span class="badge {row.status}">{row.status}</span>
    </div>
    <div class="stage" class:busy={activeStatuses.has(row.status)} role="status">{row.stage}</div>
    <div
      class="meter"
      class:busy={activeStatuses.has(row.status)}
      role="progressbar"
      aria-valuemin="0"
      aria-valuemax="100"
      aria-valuenow={value}
      aria-valuetext={row.stage}
    >
      <span class="meter-fill" style:width="{value}%"></span>
    </div>
    <p class="note">
      Output: {modeNames[row.mode] || "All stems"} · {qualityText(row)}{rangeNote(row)}
    </p>
    {#if reading}
      <p id="job-reading" class="note">{reading}</p>
    {/if}
    {#if row.analysis_warning}
      <p class="note">{row.analysis_warning}</p>
    {/if}
    {#if row.error}
      <p class="error">{row.error}</p>
    {/if}
    {#if activeStatuses.has(row.status)}
      <p class="note">
        You can leave this page and return later. The first run downloads the model;
        processing time depends on track length and your hardware.
      </p>
    {/if}
    <div class="actions">
      {#if row.status === "completed"}
        <a class="button primary" href="/api/jobs/{row.id}/download"
          >{row.mode === "all" ? "Download all stems" : "Download result ZIP"}</a
        >
      {/if}
      {#if row.status === "queued" || row.status === "running"}
        <button
          type="button"
          disabled={session.actionPending}
          onclick={() => runJobAction("cancel", row.id)}>Cancel job</button
        >
      {/if}
      {#if row.status === "failed" || row.status === "cancelled"}
        <button
          type="button"
          class="primary"
          disabled={session.actionPending}
          onclick={() => runJobAction("retry", row.id)}>Try again</button
        >
      {/if}
      {#if !activeStatuses.has(row.status)}
        <button
          type="button"
          class="danger"
          disabled={session.actionPending}
          onclick={() => runJobAction("delete", row.id)}>Delete</button
        >
      {/if}
    </div>
    <div class="stem">
      <div class="stem-top">
        <strong>original</strong>
        <a href="/api/jobs/{row.id}/audio/original?download=true"
          >{row.filename.toLowerCase().endsWith(".mp3") ? "Download MP3" : "Download WAV"}</a
        >
      </div>
      <audio
        controls
        preload="none"
        src="/api/jobs/{row.id}/audio/original"
        aria-label="original preview"
        onplay={pauseOthers}
      ></audio>
    </div>
    {#if row.status === "completed"}
      {#each row.outputs as output (output.id)}
        <div class="stem">
          <div class="stem-top">
            <strong>{output.label}</strong>
            <a href="/api/jobs/{row.id}/audio/{output.id}?download=true">Download WAV</a>
          </div>
          {#if output.sources.length > 1}
            <p class="note">{output.sources.map((name) => sourceNames[name]).join(" + ")}</p>
          {/if}
          <audio
            controls
            preload="none"
            src="/api/jobs/{row.id}/audio/{output.id}"
            aria-label="{output.id} preview"
            onplay={pauseOthers}
          ></audio>
        </div>
      {/each}
      <p class="note">
        44.1 kHz stereo · 32-bit float WAV. Separation may contain artifacts or sound
        from other instruments.
      </p>
    {/if}
  {/if}
</section>
