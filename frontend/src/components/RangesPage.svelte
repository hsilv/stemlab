<script>
  import "./RangesPage.css";
  import DeckWave from "./DeckWave.svelte";
  import { clock } from "../lib/format.js";
  import { snapToBar } from "../lib/grid.js";
  import { separate } from "../lib/jobs.js";
  import {
    chosenSources,
    describeEffect,
    outputSummary,
  } from "../lib/plan.js";
  import {
    addRange,
    clearRanges,
    importRekordbox,
    moveRangeEdge,
    moveSelectionEdge,
    pickTime,
    removeRange,
    setSection,
    stopAtEnd,
    setPreviewVolume,
    togglePreview,
  } from "../lib/section.js";
  import { session, showPage } from "../lib/state.svelte.js";

  let previewLabel = $state("Preview section");
  const chosen = $derived(chosenSources(session.mode, session.keep));
  const blocked = $derived(!session.file || session.uploading || !chosen.length);
  const cues = $derived(
    [...session.fileCues, ...session.xmlCues].sort((a, b) => a.time - b.time),
  );
  const bounds = $derived([null, ...cues, null]);
  const effect = $derived(
    describeEffect(session.mode, session.ranges, session.from, session.to),
  );

  function onEdge(kind, time) {
    const snapped = snapToBar(time, session.bpm, session.downbeat);
    if (kind.index < 0) moveSelectionEdge(kind.edge, snapped);
    else moveRangeEdge(kind.index, kind.edge, snapped);
  }
</script>

<div
  id="page-ranges"
  class="page"
  class:is-on={session.step === "ranges"}
  class:back={session.motion === "back"}
  hidden={session.step !== "ranges"}
  inert={session.uploading ? true : undefined}
>
  <div class="page-head">
    <h2>Where it plays.</h2>
    <p class="note">
      A range is a stretch of the song that gets separated. Everywhere else stays the
      original recording. Add more than one: from 0 to 5 seconds, then from 10 to 15,
      and the effect hits each of them. Leave this empty to separate the whole track.
    </p>
  </div>
  <div class="range-work">
    {#if session.step === "ranges" && session.wave}
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
        ranges={session.ranges}
        selection={{ from: session.from, to: session.to }}
        cues={cues}
        onseek={pickTime}
        onzoom={(level) => (session.zoom = level)}
        onvolume={setPreviewVolume}
        onEdge={onEdge}
      />
    {/if}
    <div id="segments" class="segments">
      {#if cues.length}
        {#each bounds.slice(0, -1) as start, index (`${start?.time ?? "start"}|${bounds[index + 1]?.time ?? "end"}`)}
          {@const end = bounds[index + 1]}
          {@const values = [start ? String(start.time) : "", end ? String(end.time) : ""]}
          <button
            type="button"
            class="chip"
            class:active={values[0] === session.from && values[1] === session.to}
            onclick={() => setSection(...values)}
          >
            {start ? start.label : "Start"} → {end ? end.label : "End"} · {clock(
              start ? start.time : 0,
            )}–{end ? clock(end.time) : "end"}
          </button>
        {/each}
      {/if}
    </div>
    <ul id="range-list" class="range-list">
      {#each session.ranges as range, index (`${range.from}|${range.to}|${index}`)}
        <li class="range">
          <span>{clock(+range.from)}–{clock(+range.to)}</span>
          <button type="button" onclick={() => removeRange(index)}>Remove</button>
        </li>
      {/each}
    </ul>
    <div class="transport">
      <label class="time"
        >From<input
          id="from"
          type="number"
          min="0"
          step="0.1"
          placeholder="start"
          value={session.from}
          oninput={(event) => (session.from = event.currentTarget.value)}
        />s</label
      >
      <label class="time"
        >To<input
          id="to"
          type="number"
          min="0"
          step="0.1"
          placeholder="end"
          value={session.to}
          oninput={(event) => (session.to = event.currentTarget.value)}
        />s</label
      >
      <button type="button" id="add-range" onclick={addRange}>Add range</button>
      <button type="button" id="preview" onclick={togglePreview}>{previewLabel}</button>
      <button
        type="button"
        id="clear"
        disabled={session.from === "" && session.to === "" && !session.ranges.length}
        onclick={clearRanges}>Whole track</button
      >
      <span id="output-summary">{outputSummary(session.mode, chosen)}</span>
    </div>
  </div>
  <fieldset id="section" class="section-notes">
    <legend class="sr-only">Section</legend>
    <label class="button file-label"
      >Rekordbox XML<input
        id="rekordbox"
        type="file"
        accept=".xml,text/xml"
        onchange={(event) => importRekordbox(event.currentTarget.files?.[0])}
      /></label
    >
    <audio
      id="section-audio"
      hidden
      onplay={() => (previewLabel = "Stop")}
      onpause={() => (previewLabel = "Preview section")}
      ontimeupdate={stopAtEnd}
    ></audio>
    <p id="cue-note" class="note" aria-live="polite">
      Click a cue on the waveform (first click sets the start, second sets the end),
      drag either edge to adjust it, pick a stretch between cues, or type times in
      seconds, then add the range. Dragged edges and the arrow keys snap to the bar.
      Typed times stay as entered. WAV
      cue markers and Mixxx hot cues are read automatically; for Rekordbox, export your
      collection as XML and add it here.
    </p>
    <p id="section-effect" class="note" aria-live="polite">{effect}</p>
  </fieldset>
  <div class="pager">
    <button type="button" id="back-stems" class="back" onclick={() => showPage("stems")}>Back</button>
    <button type="button" id="separate" class="next primary" disabled={blocked} onclick={separate}
      >Separate track</button
    >
  </div>
</div>
