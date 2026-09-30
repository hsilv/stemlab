<script>
  import "./StemsPage.css";
  import {
    instrumentSourceNames,
    modeNames,
    modelNames,
    modes,
    sourceNames,
    sources,
    vocalNames,
  } from "../lib/labels.js";
  import { goLoad, goRanges } from "../lib/nav.js";
  import { chosenSources, isInvertible, previewNote } from "../lib/plan.js";
  import { setKeep, setMode } from "../lib/selection.js";
  import { session } from "../lib/state.svelte.js";

  const chosen = $derived(chosenSources(session.mode, session.keep));
  const note = $derived(previewNote(session.mode, chosen));
  const invertible = $derived(isInvertible(session.mode, session.keep));
  const blocked = $derived(!session.file || session.uploading || !chosen.length);
</script>

<div
  id="page-stems"
  class="page"
  class:is-on={session.step === "stems"}
  class:back={session.motion === "back"}
  hidden={session.step !== "stems"}
>
  <div class="page-head">
    <h2>Choose the stems.</h2>
    <p class="note">
      Each sound has its own color. All stems writes a file per sound. The other
      choices keep what you select in one file.
    </p>
  </div>
  <fieldset id="output-selector" class="output-selector" disabled={session.uploading}>
    <legend class="sr-only">Output</legend>
    <div class="mode-grid">
      {#each modes as mode (mode.value)}
        <label class="mode-card"
          ><input
            type="radio"
            name="mode"
            value={mode.value}
            checked={session.mode === mode.value}
            onchange={() => setMode(mode.value)}
          /><span
            ><span class="marks" aria-hidden="true"
              >{#each mode.icons as icon (icon)}<svg class={`icon ${icon}`}
                  ><use href={`#icon-${icon}`} /></svg
                >{/each}</span
            ><strong>{mode.title}</strong><small>{mode.detail}</small></span
          ></label
        >
      {/each}
    </div>
    <fieldset id="custom-sources" class="custom-sources" hidden={session.mode !== "custom"}>
      <legend>Keep these sounds together</legend>
      <div class="source-toggles">
        {#each sources as source (source)}
          <label class="stem-key {source}"
            ><input
              type="checkbox"
              name="keep"
              value={source}
              checked={session.keep.includes(source)}
              onchange={(event) => setKeep(source, event.currentTarget.checked)}
            /><svg class="icon" aria-hidden="true"><use href={`#icon-${source}`} /></svg
            ><span>{sourceNames[source]}</span></label
          >
        {/each}
      </div>
    </fieldset>
    <div id="output-preview" class="output-preview" aria-live="polite" aria-atomic="true">
      <strong>Output</strong>
      <div class="output-files">
        {#if session.mode === "all"}
          {#each chosen as name (name)}
            <div class="output-file">{sourceNames[name]} · WAV</div>
          {/each}
        {:else if chosen.length}
          <div class="output-file">
            {session.mode === "instrumental"
              ? "Instrumental · WAV"
              : `${modeNames[session.mode]} · WAV`}
            <small>{chosen.map((name) => sourceNames[name]).join(" + ")}</small>
          </div>
        {/if}
      </div>
      <p class={note.className}>{note.text}</p>
    </div>
    <fieldset class="quality">
      <legend>Separation quality</legend>
      <label
        >Vocals<select id="vocals" bind:value={session.vocals}>
          {#each session.config?.vocal_models ?? [] as value (value)}
            <option {value}>{vocalNames[value] || value}</option>
          {/each}
        </select></label
      >
      <label
        >Drums, bass &amp; other<select id="model" bind:value={session.model}>
          {#each session.config?.models ?? [] as value (value)}
            <option {value}>{modelNames[value] || value}</option>
          {/each}
        </select></label
      >
      <label
        >Instruments from<select
          id="instruments-from"
          bind:value={session.instrumentsFrom}
          disabled={session.vocals === "demucs"}
        >
          {#each session.config?.instrument_sources ?? [] as value (value)}
            <option {value} disabled={value === "inverse" && !invertible}
              >{instrumentSourceNames[value] || value}</option
            >
          {/each}
        </select></label
      >
      <label
        >Shifts<select id="shifts" bind:value={session.shifts}>
          {#each session.shiftOptions as value (value)}
            <option value={String(value)}>{value}</option>
          {/each}
        </select></label
      >
      <label
        >Overlap<select id="overlap" bind:value={session.overlap}>
          {#each session.overlapOptions as value (value)}
            <option value={String(value)}>{Math.round(value * 100)}%</option>
          {/each}
        </select></label
      >
      <p class="note">
        Higher quality takes longer. Roformer models give cleaner vocals; Demucs
        always makes drums, bass and other, and shifts and overlap tune that stage.
        For No vocals, "Mix minus vocals" skips Demucs and keeps everything the vocal
        model left, unchanged. Demucs MMI scored slightly higher on bass in published
        tests than the fine-tuned model. If the bass sounds bubbly, try another model,
        "Original track", or plain Demucs for vocals.
      </p>
    </fieldset>
  </fieldset>
  <div class="pager">
    <button type="button" id="back-load" class="back" onclick={goLoad}>Back</button>
    <button type="button" id="to-ranges" class="next" class:primary={!blocked} disabled={blocked} onclick={goRanges}
      >Set ranges</button
    >
  </div>
</div>
