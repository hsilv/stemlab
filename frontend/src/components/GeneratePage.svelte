<script>
  import "./GeneratePage.css";
  import { readingLine } from "../lib/format.js";
  import { createGenerated, examples, problem, tips } from "../lib/generate.js";
  import { modeNames } from "../lib/labels.js";
  import { session } from "../lib/state.svelte.js";

  let { active = false } = $props();

  const form = $derived(session.generate);
  const limits = $derived(session.config?.generate?.seconds ?? [10, 240]);
  const references = $derived(session.rows.filter((row) => row.mode !== "generate" || row.status === "completed"));
  const chosen = $derived(references.find((row) => row.id === form.reference.job) ?? null);
  const stems = $derived([
    ...(chosen && chosen.mode !== "generate" ? [{ id: "original", label: "The whole song" }] : []),
    ...(chosen?.status === "completed" ? chosen.outputs : []),
  ]);
  const reading = $derived(chosen ? readingLine(chosen.bpm, chosen.camelot, chosen.key_name) : "");
  const problemText = $derived(problem());

  function useCrate() {
    form.reference.kind = "job";
    if (!references.some((row) => row.id === form.reference.job))
      form.reference.job = references[0]?.id ?? "";
    pickStem();
  }

  function pickStem() {
    if (!stems.some((stem) => stem.id === form.reference.stem)) form.reference.stem = stems[0]?.id ?? "original";
  }
</script>

<div id="page-generate" class="page is-on" hidden={!active} inert={form.busy ? true : undefined}>
  <div class="page-head">
    <h2>How it works</h2>
    <ol class="how">
      <li><strong>Describe</strong> the music in your own words.</li>
      <li>Optionally <strong>add a reference</strong>, a song to take the feel from.</li>
      <li>Press <strong>Make the track</strong>. It appears in the crate when it is ready.</li>
    </ol>
  </div>

  <label class="field"
    ><span class="label">1 · What should it sound like?</span>
    <textarea
      id="generate-prompt"
      rows="3"
      maxlength="500"
      placeholder="For example: warm lo-fi hip hop, mellow drums, soft electric piano, relaxed"
      value={form.prompt}
      oninput={(event) => (form.prompt = event.currentTarget.value)}
    ></textarea></label
  >
  <div class="chips" role="group" aria-label="Example descriptions">
    {#each examples as example (example)}
      <button type="button" class="chip" onclick={() => (form.prompt = example)}>{example}</button>
    {/each}
  </div>
  <details class="help">
    <summary>Not sure what to write?</summary>
    <p>
      Write a short phrase, in English, naming a few of these. A track has no singing: it is
      music to play or sing over.
    </p>
    <ul>
      {#each tips as [name, text] (name)}
        <li><strong>{name}</strong>: {text}</li>
      {/each}
    </ul>
    <p>Each press of the button makes a different take, so try the same description again.</p>
  </details>

  <fieldset class="field reference">
    <legend>2 · A song to copy the feel from (optional)</legend>
    <p class="note">
      A reference only guides the style, sound and tempo. The new track is not a copy of it and
      does not use its notes.
    </p>
    <div class="kind" role="group" aria-label="Reference">
      <button
        type="button"
        id="reference-none"
        aria-pressed={form.reference.kind === "none"}
        onclick={() => (form.reference.kind = "none")}>No reference</button
      >
      <button
        type="button"
        id="reference-job"
        aria-pressed={form.reference.kind === "job"}
        disabled={!references.length}
        onclick={useCrate}>A song in the crate</button
      >
      <button
        type="button"
        id="reference-file"
        aria-pressed={form.reference.kind === "file"}
        onclick={() => (form.reference.kind = "file")}>A file I choose</button
      >
    </div>
    {#if form.reference.kind === "job"}
      <label
        >Song
        <select
          id="reference-song"
          value={form.reference.job}
          onchange={(event) => {
            form.reference.job = event.currentTarget.value;
            pickStem();
          }}
        >
          {#each references as row (row.id)}
            <option value={row.id}>{row.filename} · {modeNames[row.mode] || "All stems"}</option>
          {/each}
        </select></label
      >
      <label
        >Which part
        <select
          id="reference-stem"
          value={form.reference.stem}
          onchange={(event) => (form.reference.stem = event.currentTarget.value)}
        >
          {#each stems as stem (stem.id)}
            <option value={stem.id}>{stem.label ?? stem.id}</option>
          {/each}
        </select></label
      >
      <p class="note">
        Tip: pick the instrumental or the drums and bass when you only want the groove.
      </p>
      {#if reading}
        <p class="note" id="reference-reading">Detected: {reading}</p>
      {/if}
    {:else if form.reference.kind === "file"}
      <label
        >A WAV, MP3 or FLAC file. Only its middle 30 seconds are used.
        <input
          id="reference-upload"
          type="file"
          accept=".wav,.mp3,.flac,audio/wav,audio/mpeg,audio/flac"
          onchange={(event) => (form.reference.file = event.currentTarget.files?.[0] ?? null)}
        /></label
      >
    {/if}
  </fieldset>

  <label class="field"
    ><span class="label">3 · How long? <strong>{form.duration} seconds</strong></span>
    <input
      id="generate-duration"
      type="range"
      min={limits[0]}
      max={limits[1]}
      step="5"
      value={form.duration}
      oninput={(event) => (form.duration = Number(event.currentTarget.value))}
    />
    <span class="note">Short tracks are quickest to try. You can always make a longer one.</span></label
  >

  <p class="note" aria-live="polite">{problemText}</p>
  <p class="note warn" role="alert" hidden={!session.message}>{session.message}</p>
  <div class="pager">
    <button
      type="button"
      id="generate-go"
      class="next primary"
      disabled={!!problemText || form.busy}
      onclick={createGenerated}>{form.busy ? "Starting…" : "Make the track"}</button
    >
  </div>
  <p class="note">
    Each track starts with about half a minute of loading, then takes roughly half as long as the
    music itself. Everything runs on this machine. The result is made by an AI model, so listen before you use it; this
    version does not learn from your library or label your songs.
  </p>
</div>
