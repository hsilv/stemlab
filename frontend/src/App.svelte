<script>
  import "./App.css";
  import { onMount } from "svelte";
  import Crate from "./components/Crate.svelte";
  import LoadPage from "./components/LoadPage.svelte";
  import ProcessPage from "./components/ProcessPage.svelte";
  import RangesPage from "./components/RangesPage.svelte";
  import StemsPage from "./components/StemsPage.svelte";
  import { loadConfig, startPolling } from "./lib/jobs.js";
  import { goLoad, goProcess, goRanges, goStemsTab } from "./lib/nav.js";
  import { session, steps } from "./lib/state.svelte.js";

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
<header>
  <a class="brand" href="/"><strong>StemLab</strong></a>
  <span class="local"><span class="lamp" aria-hidden="true"></span>On this machine</span>
</header>
<div class="booth">
  <Crate />
  <main>
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
          onclick={goStemsTab}>Stems</button
        >
        <button
          type="button"
          class="step"
          id="step-ranges"
          aria-current={session.step === "ranges" ? "step" : undefined}
          onclick={goRanges}>Ranges</button
        >
        <button
          type="button"
          class="step"
          id="step-process"
          aria-current={session.step === "process" ? "step" : undefined}
          onclick={goProcess}>Process</button
        >
      </nav>
      <LoadPage />
      <StemsPage />
      <RangesPage />
      <ProcessPage />
    </section>
    <p id="message" role="alert" hidden={!session.message}>{session.message}</p>
    <footer>
      <span>Demucs on this machine</span>
      <a href="/docs">API documentation</a>
    </footer>
  </main>
</div>
