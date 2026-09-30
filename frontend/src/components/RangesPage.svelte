<script>
  import "./RangesPage.css";
  import { onMount } from "svelte";
  import { clock } from "../lib/format.js";
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
    nudgeSelectionEdge,
    pickTime,
    removeRange,
    setSection,
    stopAtEnd,
    togglePreview,
  } from "../lib/section.js";
  import { session, showPage } from "../lib/state.svelte.js";
  import { drawWaveform } from "../lib/waveform.js";

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

  function percent(time) {
    return `${(time / session.wave.duration) * 100}%`;
  }

  function paint() {
    if (session.step !== "ranges" || !session.wave) return;
    const canvas = document.getElementById("wave");
    if (canvas?.clientWidth) drawWaveform(canvas, session.wave.peaks);
  }

  let suppressClick = false;

  function timeAt(clientX) {
    const box = document.getElementById("wave").getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (clientX - box.left) / box.width));
    return ratio * session.wave.duration;
  }

  function pickOnWave(event) {
    if (suppressClick) {
      suppressClick = false;
      return;
    }
    if (!session.wave) return;
    const box = document.getElementById("wave").getBoundingClientRect();
    pickTime(((event.clientX - box.left) / box.width) * session.wave.duration);
  }

  function stopEdgeClick(event) {
    event.stopPropagation();
    suppressClick = false;
  }

  function beginDrag(event, apply) {
    event.preventDefault();
    event.stopPropagation();
    const handle = event.currentTarget;
    handle.setPointerCapture(event.pointerId);
    const move = (pointer) => apply(timeAt(pointer.clientX));
    const finish = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", finish);
      handle.removeEventListener("pointercancel", finish);
      suppressClick = true;
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", finish);
    handle.addEventListener("pointercancel", finish);
  }

  function nudge(edge, event, index = -1) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    event.stopPropagation();
    const step = (event.shiftKey ? 1 : 0.1) * (event.key === "ArrowLeft" ? -1 : 1);
    if (index < 0) nudgeSelectionEdge(edge, step);
    else {
      const range = session.ranges[index];
      const current = edge === "from" ? +range.from : +range.to;
      moveRangeEdge(index, edge, current + step);
    }
  }

  $effect(() => {
    session.step;
    session.wave;
    const frame = requestAnimationFrame(paint);
    return () => cancelAnimationFrame(frame);
  });

  onMount(() => {
    window.addEventListener("resize", paint);
    return () => window.removeEventListener("resize", paint);
  });
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
    <div id="timeline" class="timeline" hidden={!session.wave} onclick={pickOnWave}>
      <canvas id="wave"></canvas>
      {#if session.wave}
        <div id="bands">
          {#each session.ranges as range, index (index)}
            <div
              class="band"
              class:arrive={session.flash === `${range.from}|${range.to}`}
              style:left={percent(+range.from)}
              style:right={`${100 - (+range.to / session.wave.duration) * 100}%`}
            >
              <button
                type="button"
                class="edge start"
                aria-label="Range start, {clock(+range.from)}"
                onpointerdown={(event) => beginDrag(event, (time) => moveRangeEdge(index, "from", time))}
                onclick={stopEdgeClick}
                onkeydown={(event) => nudge("from", event, index)}
              ></button>
              <button
                type="button"
                class="edge end"
                aria-label="Range end, {clock(+range.to)}"
                onpointerdown={(event) => beginDrag(event, (time) => moveRangeEdge(index, "to", time))}
                onclick={stopEdgeClick}
                onkeydown={(event) => nudge("to", event, index)}
              ></button>
            </div>
          {/each}
        </div>
        <div
          id="selection"
          class="selection"
          hidden={session.from === "" && session.to === ""}
          style:left={percent(session.from === "" ? 0 : +session.from)}
          style:right={`${100 - (session.to === "" ? 100 : (+session.to / session.wave.duration) * 100)}%`}
        >
          <button
            type="button"
            class="edge start"
            aria-label="Section start"
            onpointerdown={(event) => beginDrag(event, (time) => moveSelectionEdge("from", time))}
            onclick={stopEdgeClick}
            onkeydown={(event) => nudge("from", event)}
          ></button>
          <button
            type="button"
            class="edge end"
            aria-label="Section end"
            onpointerdown={(event) => beginDrag(event, (time) => moveSelectionEdge("to", time))}
            onclick={stopEdgeClick}
            onkeydown={(event) => nudge("to", event)}
          ></button>
        </div>
        <div id="markers">
          {#each cues as cue (`${cue.label}|${cue.time}`)}
            <button
              type="button"
              class="marker"
              style:left={percent(cue.time)}
              title="{cue.label} · {clock(cue.time)}"
              aria-label="{cue.label} · {clock(cue.time)}"
              onclick={(event) => {
                event.stopPropagation();
                pickTime(cue.time);
              }}
            ></button>
          {/each}
        </div>
      {/if}
    </div>
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
      seconds, then add the range. WAV
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
