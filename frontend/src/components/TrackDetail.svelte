<script>
  import "./TrackDetail.css";
  import { duration, readingLine } from "../lib/format.js";
  import { editAgain } from "../lib/deck.js";
  import { reuse } from "../lib/generate.js";
  import { runJobAction } from "../lib/jobs.js";
  import {
    activeStatuses,
    exportFormats,
    modeNames,
    sourceNames,
  } from "../lib/labels.js";
  import { extendNote, qualityText, rangeNote, stageValue } from "../lib/plan.js";
  import ResultPlayer from "./ResultPlayer.svelte";
  import StemMixer from "./StemMixer.svelte";
  import { session } from "../lib/state.svelte.js";

  const row = $derived(
    session.rows.find((item) => item.id === session.selectedId) ?? null,
  );

  const reading = $derived(
    row ? readingLine(row.bpm, row.camelot, row.key_name) : "",
  );

  const formats = $derived(
    Object.keys(exportFormats).filter((name) =>
      (session.config?.export_formats ?? ["flac", "wav"]).includes(name),
    ),
  );
  const chosenFormat = $derived(
    formats.includes(session.exportFormat) ? session.exportFormat : "flac",
  );

  const originalFormat = (filename) =>
    filename.toLowerCase().endsWith(".mp3")
      ? "MP3"
      : filename.toLowerCase().endsWith(".flac")
        ? "FLAC"
        : "WAV";

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
          : "Load a WAV, MP3 or FLAC, or pick a track from the crate."}
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
      class:done={row.status === "completed"}
      class:failed={row.status === "failed"}
      role="progressbar"
      aria-valuemin="0"
      aria-valuemax="100"
      aria-valuenow={value}
      aria-valuetext={row.stage}
    >
      <span class="meter-fill" style:width="{value}%"></span>
    </div>
    <p class="note">
      Output: {modeNames[row.mode] || "All stems"}{row.mode === "extend"
        ? extendNote(row)
        : row.mode === "generate"
          ? ` · “${row.generate.prompt}”`
          : ` · ${qualityText(row)}${rangeNote(row)}`}
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
        <a class="button primary" href="/api/jobs/{row.id}/download?format={chosenFormat}"
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
      {#if row.mode === "generate"}
        <button type="button" onclick={() => reuse(row)}>Make another take</button>
      {:else}
        <button type="button" disabled={session.uploading} onclick={() => editAgain(row)}
          >Edit this song again</button
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
    {#if row.mode !== "generate"}
      <div class="stem">
        <div class="stem-top">
          <strong>original</strong>
          <a href="/api/jobs/{row.id}/audio/original?download=true"
            >Download {originalFormat(row.filename)}</a
          >
        </div>
        <ResultPlayer
          src="/api/jobs/{row.id}/audio/original"
          label="original"
          onplay={pauseOthers}
        />
      </div>
    {/if}
    {#if row.status === "completed"}
      <label class="format">
        Download as
        <select
          value={chosenFormat}
          onchange={(event) => (session.exportFormat = event.currentTarget.value)}
        >
          {#each formats as name (name)}
            <option value={name}>{exportFormats[name]}</option>
          {/each}
        </select>
      </label>
      {#if row.mode === "all" && row.outputs.length > 1 && row.outputs.every((output) => output.sources.length === 1)}
        {#key row.id}
          <StemMixer jobId={row.id} outputs={row.outputs} />
        {/key}
      {/if}
      {#each row.outputs as output (output.id)}
        <div class="stem">
          <div class="stem-top">
            <strong>{output.label}</strong>
            <a href="/api/jobs/{row.id}/audio/{output.id}?download=true&format={chosenFormat}"
              >Download {chosenFormat.toUpperCase()}</a
            >
          </div>
          {#if output.sources.length > 1 && row.mode !== "extend"}
            <p class="note">{output.sources.map((name) => sourceNames[name]).join(" + ")}</p>
          {/if}
          <ResultPlayer
            src="/api/jobs/{row.id}/audio/{output.id}"
            label={output.id}
            onplay={pauseOthers}
          />
        </div>
      {/each}
      {#if row.mode === "generate"}
        <p class="note">
          48 kHz stereo, made by an AI model from your description: listen before you use it.
          Stored as lossless 24-bit FLAC; other formats are made when you download.
        </p>
      {:else}
        <p class="note">
          44.1 kHz stereo. Stored as lossless 24-bit FLAC (older jobs: 32-bit float WAV); other formats are made when you download. Separation may contain artifacts or sound
          from other instruments.
        </p>
      {/if}
    {/if}
  {/if}
</section>
