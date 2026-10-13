<script>
  import "./ExtendPage.css";
  import DeckWave from "./DeckWave.svelte";
  import { clock } from "../lib/format.js";
  import { nearestBeat } from "../lib/grid.js";
  import {
    addOperation,
    barsOf,
    describe,
    draftProblem,
    firstBar,
    removeOperation,
    usesInverse,
  } from "../lib/manual.js";
  import { openForExtender } from "../lib/deck.js";
  import { createExtended, extendProblem, previewExtended } from "../lib/jobs.js";
  import {
    extendBars,
    introSources,
    introTreatments,
    manualActions,
    modelNames,
    outroSources,
    sourceNames,
    vocalNames,
  } from "../lib/labels.js";
  import {
    moveSelectionEdge,
    pickTime,
    setPreviewVolume,
    setSection,
    togglePreview,
  } from "../lib/section.js";
  import { session } from "../lib/state.svelte.js";

  let { active = false } = $props();

  const row = $derived(session.rows.find((item) => item.id === session.selectedId) ?? null);
  const opened = $derived(!!row && session.sourceJob?.id === row.id && !!session.file);

  // The song picked in the crate is the one planned here.
  $effect(() => {
    if (active && row) openForExtender(row);
  });

  const gridKnown = $derived(
    typeof session.bpm === "number" && session.bpm > 0 && typeof session.downbeat === "number",
  );
  const problem = $derived(extendProblem());
  const barSeconds = $derived(gridKnown ? 240 / session.bpm : 0);
  const selectedBars = $derived(
    barSeconds && session.from !== "" && session.to !== ""
      ? Math.round((+session.to - +session.from) / barSeconds)
      : 0,
  );
  const manual = $derived(session.extendMode === "manual");
  const draft = $derived(session.manual.draft);
  const stemNames = ["vocals", "drums", "bass", "other"];
  // Fragments already chosen show as bands on the waveform.
  const bands = $derived(
    (manual
      ? [...session.manual.operations.map((item) => item.fragment), draft.fragment]
      : [session.extend.intro, session.extend.outro]
          .filter((side) => side.bars && side.source === "fragment" && side.fragment)
          .map((side) => side.fragment)
    )
      .filter(Boolean)
      .map(([from, to]) => ({ from: String(from), to: String(to) })),
  );

  function aligned(time) {
    return gridKnown ? nearestBeat(time, session.bpm, session.downbeat) : time;
  }

  function onSeek(time, exact) {
    pickTime(exact ? time : aligned(time));
  }

  function onEdge(kind, time) {
    if (kind.index < 0) moveSelectionEdge(kind.edge, aligned(time));
  }

  function useSelection(side) {
    if (selectedBars < 1) return;
    session.extend[side].fragment = [+session.from, +session.to];
    session.extend[side].source = "fragment";
  }

  function useFragment() {
    if (selectedBars < 1) return;
    draft.fragment = [+session.from, +session.to];
    if (draft.action !== "replace") draft.bars = Math.min(64, selectedBars);
  }

  function useSelectionAsPosition() {
    draft.at = firstBar(session.from);
  }

  function useSelectionAsSpan() {
    draft.spanFrom = firstBar(session.from);
    draft.spanTo = firstBar(session.to);
  }

  function setBar(event, key) {
    const value = event.currentTarget.value;
    draft[key] = value === "" ? null : +value - 1;
  }

  function setSpan(event, side) {
    const value = event.currentTarget.value;
    if (side === 0) draft.spanFrom = value === "" ? null : +value - 1;
    else draft.spanTo = value === "" ? null : +value;
  }

  // Select a chosen fragment again and play it from its start.
  function hear(side) {
    const fragment = session.extend[side].fragment;
    if (!fragment) return;
    document.getElementById("section-audio")?.pause();
    setSection(String(fragment[0]), String(fragment[1]));
    togglePreview();
  }

  function fragmentText(side) {
    const fragment = session.extend[side].fragment;
    return fragment ? `${clock(fragment[0])}–${clock(fragment[1])}` : "none chosen yet";
  }
</script>

<div
  id="page-extend"
  class="page is-on"
  hidden={!active}
  inert={session.extendBusy ? true : undefined}
>
  {#if !row}
    <p class="note">Pick a song from the crate to extend it.</p>
  {:else if !opened}
    <p class="note">Opening {row.filename}…</p>
  {:else}
    <div class="page-head">
      <h2>{row.filename}</h2>
      <p class="note">
        {manual
          ? "Select a fragment of the song, process it with the models you choose and place it: at the start, at the end, in the middle, or in place of part of the song. Positions are bars of the original song."
          : "An intro goes before the song and an outro after it. The song starts exactly on a bar line and is not touched. Choose how long each is and what plays in it; you can listen to the joins before making it."}
      </p>
    </div>
  <p class="song-name">{session.bpm ? `${session.bpm} BPM` : "No tempo"}</p>
  {#if !gridKnown}
    <p class="note warn">No steady tempo was found for this song, so there is no beat grid to extend on.</p>
  {:else if session.analysisWarning}
    <p class="note warn">{session.analysisWarning} The joins may drift where the tempo is not steady.</p>
  {/if}
  <div class="mode" role="group" aria-label="How to extend">
    <button
      type="button"
      id="mode-auto"
      aria-pressed={!manual}
      onclick={() => (session.extendMode = "auto")}>Automatic</button
    >
    <button
      type="button"
      id="mode-manual"
      aria-pressed={manual}
      onclick={() => (session.extendMode = "manual")}>Manual</button
    >
  </div>
  {#if active && session.wave}
    <DeckWave
      peaks={session.wave.peaks}
      bands={session.wave.bands}
      samples={session.wave.samples}
      sampleRate={session.wave.sampleRate}
      scale={session.wave.scale}
      duration={session.wave.duration}
      bpm={session.bpm}
      downbeat={session.downbeat}
      needle={session.needle}
      zoom={session.zoom}
      volume={session.volume}
      ranges={bands}
      selection={{ from: session.from, to: session.to }}
      snap={gridKnown}
      onseek={onSeek}
      onzoom={(level) => (session.zoom = level)}
      onvolume={setPreviewVolume}
      {onEdge}
    />
  {/if}
  <div class="transport">
    <span class="note"
      >{manual
        ? "Select a stretch of the song on the waveform (it snaps to the beat grid), then use it in the operation below."
        : "To use a stretch of the song as a loop, select it on the waveform (it snaps to the beat grid), then:"}</span
    >
    <button
      type="button"
      id="preview-fragment"
      disabled={selectedBars < 1 || !session.audioUrl}
      onclick={togglePreview}>{session.previewing ? "Stop" : "Hear selection"}</button
    >
    {#if !manual}
      <button
        type="button"
        id="use-intro"
        disabled={selectedBars < 1 || !session.extend.intro.bars}
        onclick={() => useSelection("intro")}>Use for the intro</button
      >
      <button
        type="button"
        id="use-outro"
        disabled={selectedBars < 1 || !session.extend.outro.bars}
        onclick={() => useSelection("outro")}>Use for the outro</button
      >
    {/if}
    <span class="note" aria-live="polite"
      >{selectedBars >= 1 ? `Selection: ${selectedBars} bars` : "Nothing selected"}</span
    >
  </div>
  {#if !manual}
  <div class="extend-work">
    <fieldset class="side" id="extend-intro">
      <legend>Intro</legend>
      <label
        >Length
        <select
          id="intro-bars"
          value={session.extend.intro.bars}
          onchange={(event) => (session.extend.intro.bars = +event.currentTarget.value)}
        >
          <option value={0}>No intro</option>
          {#each extendBars as bars (bars)}
            <option value={bars}>{bars} bars</option>
          {/each}
        </select></label
      >
      {#if session.extend.intro.bars}
        <label
          >Loop taken from
          <select id="intro-source" bind:value={session.extend.intro.source}>
            {#each Object.entries(introSources) as [value, label] (value)}
              <option {value}>{label}</option>
            {/each}
          </select></label
        >
        <label
          >Plays as
          <select id="intro-treatment" bind:value={session.extend.intro.treatment}>
            {#each Object.entries(introTreatments) as [value, label] (value)}
              <option {value}>{label}</option>
            {/each}
          </select></label
        >
        {#if session.extend.intro.source === "fragment"}
          <p class="note">
            Fragment: {fragmentText("intro")}
            {#if session.extend.intro.fragment}
              <button type="button" class="hear" onclick={() => hear("intro")}>Hear it</button>
            {/if}
          </p>
        {/if}
      {/if}
    </fieldset>
    <fieldset class="side" id="extend-outro">
      <legend>Outro</legend>
      <label
        >Length
        <select
          id="outro-bars"
          value={session.extend.outro.bars}
          onchange={(event) => (session.extend.outro.bars = +event.currentTarget.value)}
        >
          <option value={0}>No outro</option>
          {#each extendBars as bars (bars)}
            <option value={bars}>{bars} bars</option>
          {/each}
        </select></label
      >
      {#if session.extend.outro.bars}
        <label
          >Loop taken from
          <select id="outro-source" bind:value={session.extend.outro.source}>
            {#each Object.entries(outroSources) as [value, label] (value)}
              <option {value}>{label}</option>
            {/each}
          </select></label
        >
        <p class="note">
          The voice leaves first, then the other instruments, then the bass; the drums fade
          out in the last bar.
          {#if session.extend.outro.source === "fragment"}
            Fragment: {fragmentText("outro")}
            {#if session.extend.outro.fragment}
              <button type="button" class="hear" onclick={() => hear("outro")}>Hear it</button>
            {/if}
          {/if}
        </p>
      {/if}
    </fieldset>
  </div>
  {:else}
    <div class="manual">
      {#if session.manual.operations.length}
        <ol class="operations" id="operations">
          {#each session.manual.operations as operation, index (index)}
            <li>
              <span>{describe(operation)}</span>
              <button
                type="button"
                class="hear-op"
                disabled={session.extendBusy}
                onclick={() => previewExtended(index)}>Hear it in the song</button
              >
              <button type="button" class="remove-op" onclick={() => removeOperation(index)}
                >Remove</button
              >
            </li>
          {/each}
        </ol>
      {:else}
        <p class="note">
          No operations yet. Select a fragment on the waveform, choose what to do with it and
          add it below.
        </p>
      {/if}
      <fieldset class="draft" id="draft">
        <legend>New operation</legend>
        <label
          >What to do
          <select id="draft-action" bind:value={draft.action}>
            {#each Object.entries(manualActions) as [value, label] (value)}
              <option {value}>{label}</option>
            {/each}
          </select></label
        >
        <p class="note">
          Fragment:
          {draft.fragment
            ? `${clock(draft.fragment[0])}–${clock(draft.fragment[1])} (${barsOf(draft.fragment[0], draft.fragment[1])} bars)`
            : "none yet"}
          <button
            type="button"
            id="draft-fragment"
            class="hear"
            disabled={selectedBars < 1}
            onclick={useFragment}>Use the selection</button
          >
        </p>
        {#if draft.action === "insert"}
          <label
            >Insert before bar
            <input
              id="draft-at"
              type="number"
              min="2"
              value={draft.at == null ? "" : draft.at + 1}
              oninput={(event) => setBar(event, "at")}
            /></label
          >
          <button
            type="button"
            id="draft-at-selection"
            class="hear"
            disabled={selectedBars < 1 && session.from === ""}
            onclick={useSelectionAsPosition}>Use the start of the selection</button
          >
        {:else if draft.action === "replace"}
          <div class="span">
            <label
              >Replace from bar
              <input
                id="draft-span-from"
                type="number"
                min="1"
                value={draft.spanFrom == null ? "" : draft.spanFrom + 1}
                oninput={(event) => setSpan(event, 0)}
              /></label
            >
            <label
              >to bar
              <input
                id="draft-span-to"
                type="number"
                min="1"
                value={draft.spanTo ?? ""}
                oninput={(event) => setSpan(event, 1)}
              /></label
            >
            <button
              type="button"
              id="draft-span-selection"
              class="hear"
              disabled={selectedBars < 1}
              onclick={useSelectionAsSpan}>Use the selection</button
            >
          </div>
          <p class="note">
            The fragment is repeated or trimmed to fill exactly those bars.
          </p>
        {/if}
        {#if draft.action !== "replace"}
          <label
            >Length in bars
            <input id="draft-bars" type="number" min="1" max="64" bind:value={draft.bars} />
            <small>A shorter fragment repeats, a longer one is trimmed.</small></label
          >
        {/if}
        <div class="stems">
          {#each stemNames as name (name)}
            <label class="stem-row">
              <input
                type="checkbox"
                id={`draft-stem-${name}`}
                checked={draft.stems[name] > 0}
                onchange={(event) => (draft.stems[name] = event.currentTarget.checked ? 1 : 0)}
              />
              <span>{sourceNames[name]}</span>
              <input
                type="range"
                min="5"
                max="100"
                step="5"
                aria-label={`${sourceNames[name]} volume`}
                value={Math.round(draft.stems[name] * 100)}
                disabled={!draft.stems[name]}
                oninput={(event) => (draft.stems[name] = +event.currentTarget.value / 100)}
              />
            </label>
          {/each}
        </div>
        {#if usesInverse(draft.stems)}
          <p class="note">
            Everything but the voice at one volume: the instruments are the song minus the
            voice, so nothing is lost to the separation.
          </p>
        {/if}
        <details>
          <summary>Separation models</summary>
          <label
            >Model
            <select bind:value={draft.model}>
              <option value="">Default ({modelNames[session.model] ?? session.model})</option>
              {#each session.config?.models ?? [] as value (value)}
                <option {value}>{modelNames[value] ?? value}</option>
              {/each}
            </select></label
          >
          <label
            >Voice from
            <select bind:value={draft.vocals}>
              <option value="">Default ({vocalNames[session.vocals] ?? session.vocals})</option>
              {#each session.config?.vocal_models ?? [] as value (value)}
                <option {value}>{vocalNames[value] ?? value}</option>
              {/each}
            </select></label
          >
          <label
            >Shifts
            <select bind:value={draft.shifts}>
              <option value="">Default ({session.shifts})</option>
              {#each session.shiftOptions as value (value)}
                <option value={String(value)}>{value}</option>
              {/each}
            </select></label
          >
          <label
            >Overlap
            <select bind:value={draft.overlap}>
              <option value="">Default ({Math.round(session.overlap * 100)}%)</option>
              {#each session.overlapOptions as value (value)}
                <option value={String(value)}>{Math.round(value * 100)}%</option>
              {/each}
            </select></label
          >
        </details>
        <p class="note" aria-live="polite">{draftProblem(draft)}</p>
        <button
          type="button"
          id="add-operation"
          disabled={!!draftProblem(draft)}
          onclick={addOperation}>Add operation</button
        >
      </fieldset>
    </div>
  {/if}
  {#if session.previewUrl}
    <div class="preview">
      <span class="note"
        >{manual
          ? "Preview: the operation with some of the song before and after it."
          : "Preview: the intro and the start of the song, then the end and the outro."}</span
      >
      <audio id="extend-preview" controls src={session.previewUrl}></audio>
    </div>
  {/if}
  <p class="note" aria-live="polite">{problem}</p>
  <div class="pager">
    {#if !manual}
      <button
        type="button"
        id="preview-extend"
        disabled={!!problem || session.extendBusy}
        onclick={() => previewExtended()}
        >{session.extendBusy ? "Working…" : "Preview the joins"}</button
      >
    {/if}
    <button
      type="button"
      id="create-extend"
      class="next primary"
      disabled={!!problem || session.extendBusy}
      onclick={createExtended}>Create extended version</button
    >
  </div>
  {/if}
</div>
