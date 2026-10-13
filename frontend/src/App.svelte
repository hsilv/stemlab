<script>
  import "./App.css";
  import { onMount } from "svelte";
  import Crate from "./components/Crate.svelte";
  import ExtendPage from "./components/ExtendPage.svelte";
  import GeneratePage from "./components/GeneratePage.svelte";
  import LoadPage from "./components/LoadPage.svelte";
  import PlaylistPage from "./components/PlaylistPage.svelte";
  import ProcessPage from "./components/ProcessPage.svelte";
  import RangesPage from "./components/RangesPage.svelte";
  import SectionAudio from "./components/SectionAudio.svelte";
  import StemsPage from "./components/StemsPage.svelte";
  import TagsPage from "./components/TagsPage.svelte";
  import Transport from "./components/Transport.svelte";
  import { loadConfig, startPolling } from "./lib/jobs.js";
  import { analysisSettled, goLoad, goProcess, goRanges, goStemsTab } from "./lib/nav.js";
  import { session, steps } from "./lib/state.svelte.js";

  const waiting = $derived(!!session.file && !analysisSettled());
  let playlistOpened = $state(false);

  function showSeparate() {
    session.booth = "separate";
  }

  function showPlaylist() {
    playlistOpened = true;
    session.booth = "playlist";
  }

  function showExtender() {
    session.booth = "extend";
  }

  function showTags() {
    session.booth = "tags";
  }

  function showGenerate() {
    session.booth = "generate";
  }

  // Leaving a booth stops what it was playing.
  $effect(() => {
    session.booth;
    document.getElementById("section-audio")?.pause();
  });

  onMount(() => {
    const stop = startPolling();
    loadConfig();
    return stop;
  });
</script>

<svg class="sprite" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <symbol id="icon-vocals" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
    <rect x="9" y="2.5" width="6" height="11" rx="3" />
    <path d="M6.5 11a5.5 5.5 0 0 0 11 0" />
    <path d="M12 16.5V21M8.5 21h7" />
  </symbol>
  <symbol id="icon-drums" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
    <ellipse cx="12" cy="14.5" rx="8" ry="3.2" />
    <path d="M4 14.5V10.2c0-1.8 3.6-3.2 8-3.2s8 1.4 8 3.2v4.3" />
    <path d="M12 7V4" />
  </symbol>
  <symbol id="icon-bass" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
    <path d="M2.5 15c1.8 0 2.2-6 4.2-6s2.2 6 4.3 6 2.2-6 4.3-6 2.4 6 4.2 6" />
  </symbol>
  <symbol id="icon-other" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
    <circle cx="7" cy="15" r="3" />
    <circle cx="14" cy="9" r="3" />
    <circle cx="18.5" cy="16" r="2.25" />
  </symbol>
</svg>
<SectionAudio />
<Transport />
<header>
  <a class="brand" href="/"><strong>StemLab</strong></a>
  <nav class="booth-switch" aria-label="Booth">
    <button
      type="button"
      id="booth-separate"
      aria-current={session.booth === "separate" ? "page" : undefined}
      onclick={showSeparate}>Separate</button
    >
    <button
      type="button"
      id="booth-playlist"
      aria-current={session.booth === "playlist" ? "page" : undefined}
      onclick={showPlaylist}>Playlist</button
    >
    <button
      type="button"
      id="booth-extend"
      aria-current={session.booth === "extend" ? "page" : undefined}
      onclick={showExtender}>Extender</button
    >
    <button
      type="button"
      id="booth-tags"
      aria-current={session.booth === "tags" ? "page" : undefined}
      onclick={showTags}>Tags</button
    >
    <button
      type="button"
      id="booth-generate"
      aria-current={session.booth === "generate" ? "page" : undefined}
      onclick={showGenerate}>Generate</button
    >
  </nav>
  <span class="local"><span class="lamp" aria-hidden="true"></span>On this machine</span>
</header>
<div class="booth" class:is-playlist={session.booth === "playlist"}>
  <Crate />
  <main>
    <div hidden={session.booth !== "separate"}>
      <section class="intro">
        <h1>Load a track.</h1>
        <p>
          Choose the stems, mark where the effect plays, and separate. Audio
          stays on this machine.
        </p>
      </section>
      <section class="plate" aria-labelledby="upload-title">
        <nav class="steps" aria-label="Steps">
          <span
            id="step-mark"
            class="step-mark"
            aria-hidden="true"
            style:transform={`translateX(${steps.indexOf(session.step) * 100}%)`}
          ></span>
          <button
            type="button"
            class="step"
            id="step-load"
            aria-current={session.step === "load" ? "step" : undefined}
            onclick={goLoad}>Load</button
          >
          <button
            type="button"
            class="step"
            id="step-stems"
            aria-current={session.step === "stems" ? "step" : undefined}
            disabled={waiting}
            onclick={goStemsTab}>Stems</button
          >
          <button
            type="button"
            class="step"
            id="step-ranges"
            aria-current={session.step === "ranges" ? "step" : undefined}
            disabled={waiting}
            onclick={goRanges}>Ranges</button
          >
          <button
            type="button"
            class="step"
            id="step-process"
            aria-current={session.step === "process" ? "step" : undefined}
            onclick={goProcess}>Result</button
          >
        </nav>
        <LoadPage />
        <StemsPage />
        <RangesPage />
        <ProcessPage />
      </section>
      <p id="message" role="alert" hidden={!session.message}>{session.message}</p>
    </div>
    {#if playlistOpened}
      <PlaylistPage active={session.booth === "playlist"} />
    {/if}
    <div hidden={session.booth !== "extend"}>
      <section class="intro">
        <h1>Extend a song.</h1>
        <p>
          Pick a song from the crate, then add an intro before it and an outro after it, cut
          on its beat grid. Audio stays on this machine.
        </p>
      </section>
      <section class="plate" aria-label="Extender">
        <ExtendPage active={session.booth === "extend"} />
      </section>
    </div>
    <div hidden={session.booth !== "tags"}>
      <section class="intro">
        <h1>Tag a version.</h1>
        <p>
          Give an instrumental, a stem or an edit the artist, album and cover of its song.
          Audio stays on this machine.
        </p>
      </section>
      <section class="plate" aria-label="Tags">
        <TagsPage active={session.booth === "tags"} />
      </section>
    </div>
    <div hidden={session.booth !== "generate"}>
      <section class="intro">
        <h1>Make a backing track.</h1>
        <p>
          Describe the music, and add a song to copy the feel from if you like. Audio stays on
          this machine.
        </p>
      </section>
      <section class="plate" aria-label="Generate">
        <GeneratePage active={session.booth === "generate"} />
      </section>
    </div>
    <footer>
      <span>Demucs on this machine</span>
      <a href="/docs">API documentation</a>
    </footer>
  </main>
</div>
