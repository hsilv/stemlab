<script>
  import "./TagsPage.css";
  import { modeNames } from "../lib/labels.js";
  import { copyTags, loadInfo, problem, refOf, resultingTitle, stageFile } from "../lib/tagtool.js";
  import { session } from "../lib/state.svelte.js";

  let { active = false } = $props();

  const tool = $derived(session.tagTool);
  const sides = $derived([
    ["source", "Take the tags from", tool.source],
    ["target", "Put them on", tool.target],
  ]);
  const shown = [
    ["title", "Title"],
    ["artist", "Artist"],
    ["album", "Album"],
    ["genre", "Genre"],
    ["date", "Year"],
    ["track", "Track"],
  ];

  function stemsOf(side) {
    const row = session.rows.find((item) => item.id === side.job);
    if (!row) return [];
    const ready = row.status === "completed" ? row.outputs : [];
    // A generated track has no uploaded song to take tags from.
    const original = row.mode === "generate" ? [] : [{ id: "original", label: "Original upload" }];
    return [...original, ...ready];
  }

  function choose(side) {
    if (!side.job && session.rows.length) side.job = session.rows[0].id;
    const stems = stemsOf(side);
    if (!stems.some((stem) => stem.id === side.stem)) side.stem = stems[0]?.id ?? "";
    loadInfo(side);
  }

  // Refresh what the pickers know whenever the booth opens.
  $effect(() => {
    if (!active) return;
    for (const side of [tool.source, tool.target]) if (side.kind === "job") choose(side);
  });

  const problemText = $derived(problem());
  const extra = (info) => Object.keys(info.tags).filter((name) => !shown.some(([key]) => key === name)).length;
</script>

<div id="page-tags" class="page is-on" hidden={!active} inert={tool.busy ? true : undefined}>
  <div class="page-head">
    <h2>Copy tags from one song to another.</h2>
    <p class="note">
      Title, artist, album, genre, year, track and cover go onto a copy of the target, so an
      instrumental or an edit keeps the song's identity. The title says what this version is.
      Neither file is changed; tempo and key keep the target's own. Needs ffmpeg.
    </p>
  </div>
  <div class="tag-sides">
    {#each sides as [name, label, side] (name)}
      <fieldset class="tag-side" id={`tags-${name}`}>
        <legend>{label}</legend>
        <div class="kind" role="group">
          <button
            type="button"
            aria-pressed={side.kind === "job"}
            onclick={() => {
              side.kind = "job";
              choose(side);
            }}>A song in the crate</button
          >
          <button
            type="button"
            aria-pressed={side.kind === "file"}
            onclick={() => {
              side.kind = "file";
              loadInfo(side);
            }}>A file I choose</button
          >
        </div>
        {#if side.kind === "job"}
          <label
            >Song
            <select
              id={`${name}-job`}
              value={side.job}
              onchange={(event) => {
                side.job = event.currentTarget.value;
                choose(side);
              }}
            >
              {#each session.rows as row (row.id)}
                <option value={row.id}>{row.filename} · {modeNames[row.mode] || "All stems"}</option>
              {/each}
            </select></label
          >
          <label
            >Which file
            <select
              id={`${name}-stem`}
              value={side.stem}
              onchange={(event) => {
                side.stem = event.currentTarget.value;
                loadInfo(side);
              }}
            >
              {#each stemsOf(side) as stem (stem.id)}
                <option value={stem.id}>{stem.label ?? stem.id}</option>
              {/each}
            </select></label
          >
        {:else}
          <label
            >MP3, FLAC or WAV (recognized by what is inside, not by its name)
            <input
              id={`${name}-file`}
              type="file"
              onchange={(event) => stageFile(side, event.currentTarget.files?.[0])}
            /></label
          >
        {/if}
        {#if side.error}
          <p class="note warn">{side.error}</p>
        {:else if side.info}
          <div class="tag-card">
            {#if side.info.cover}
              <img
                class="cover"
                alt="Cover"
                src={`/api/tags/cover?${new URLSearchParams({ ref: refOf(side) })}`}
              />
            {/if}
            <dl>
              {#each shown as [key, title] (key)}
                {#if side.info.tags[key]}
                  <dt>{title}</dt>
                  <dd>{side.info.tags[key]}</dd>
                {/if}
              {/each}
              {#if side.info.tempo.bpm || side.info.tempo.key}
                <dt>Tempo and key</dt>
                <dd>{[side.info.tempo.bpm && `${side.info.tempo.bpm} BPM`, side.info.tempo.key].filter(Boolean).join(" · ")}</dd>
              {/if}
            </dl>
            {#if !Object.keys(side.info.tags).length && !side.info.cover}
              <p class="note">No tags or cover.</p>
            {:else if extra(side.info)}
              <p class="note">{extra(side.info)} more fields</p>
            {/if}
          </div>
        {/if}
      </fieldset>
    {/each}
  </div>
  <div class="tag-options">
    <label
      >Version added to the title
      <input
        id="tag-version"
        type="text"
        placeholder={tool.target.info?.version ?? "none"}
        value={tool.version ?? ""}
        oninput={(event) => (tool.version = event.currentTarget.value)}
      /></label
    >
    <label class="inline"
      ><input
        id="tag-cover"
        type="checkbox"
        checked={tool.cover}
        onchange={(event) => (tool.cover = event.currentTarget.checked)}
      />Copy the cover</label
    >
    {#if resultingTitle()}
      <p class="note" id="tag-title">Title of the copy: <strong>{resultingTitle()}</strong></p>
    {/if}
  </div>
  <p class="note" aria-live="polite">{problemText || tool.done}</p>
  <div class="pager">
    <button
      type="button"
      id="copy-tags"
      class="next primary"
      disabled={!!problemText || tool.busy}
      onclick={copyTags}>{tool.busy ? "Working…" : "Copy the tags and download"}</button
    >
  </div>
</div>
