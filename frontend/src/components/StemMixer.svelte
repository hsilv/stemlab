<script>
  import "./StemMixer.css";
  import { onDestroy } from "svelte";
  import { clock } from "../lib/format.js";
  import { audibleLanes, laneColumns, sharedScale } from "../lib/mixer.js";

  // `outputs` are single-stem outputs of one finished job; each is fetched and decoded once,
  // then played together so a lane can be muted or soloed without rendering anything.
  let { jobId, outputs } = $props();

  const COLUMNS = 900;
  let state = $state("idle"); // idle | loading | ready | failed
  let message = $state("");
  let lanes = $state([]); // { id, label, source, peaks }
  let muted = $state([]);
  let soloed = $state([]);
  let playing = $state(false);
  let time = $state(0);
  let length = $state(0);

  let context = null;
  let buffers = new Map();
  let gains = new Map();
  let sources = [];
  let startedAt = 0;
  let offset = 0;
  let frame = 0;

  const heard = $derived(
    audibleLanes(
      lanes.map((lane) => lane.id),
      muted,
      soloed,
    ),
  );

  // Read `heard` first: with no player running yet there is nothing to loop over, and an
  // effect only follows what it actually read.
  $effect(() => {
    const audible = heard;
    for (const [id, gain] of gains) gain.gain.value = audible.has(id) ? 1 : 0;
  });

  async function load() {
    state = "loading";
    message = "";
    try {
      context = new AudioContext();
      const decoded = await Promise.all(
        outputs.map(async (output) => {
          const response = await fetch(`/api/jobs/${jobId}/audio/${output.id}`);
          if (!response.ok) throw new Error(`Could not load ${output.label}.`);
          return context.decodeAudioData(await response.arrayBuffer());
        }),
      );
      const scaled = sharedScale(decoded.map((buffer) => laneColumns(buffer.getChannelData(0), COLUMNS)));
      outputs.forEach((output, index) => buffers.set(output.id, decoded[index]));
      lanes = outputs.map((output, index) => ({
        id: output.id,
        label: output.label,
        source: output.sources[0],
        peaks: scaled[index],
      }));
      length = Math.max(...decoded.map((buffer) => buffer.duration));
      state = "ready";
    } catch (error) {
      message = error.message || "Could not open the mixer.";
      state = "failed";
    }
  }

  function stopSources() {
    for (const node of sources) {
      node.onended = null;
      try {
        node.stop();
      } catch {
        // Already stopped.
      }
      node.disconnect();
    }
    sources = [];
    gains = new Map();
  }

  function tick() {
    time = Math.min(length, context.currentTime - startedAt);
    if (time >= length) {
      pause(0);
      return;
    }
    frame = requestAnimationFrame(tick);
  }

  function play() {
    if (state !== "ready" || playing) return;
    document.querySelectorAll("audio").forEach((other) => other.pause());
    context.resume();
    if (offset >= length) offset = 0;
    for (const lane of lanes) {
      const node = context.createBufferSource();
      node.buffer = buffers.get(lane.id);
      const gain = context.createGain();
      gain.gain.value = heard.has(lane.id) ? 1 : 0;
      node.connect(gain).connect(context.destination);
      node.start(0, offset);
      gains.set(lane.id, gain);
      sources.push(node);
    }
    startedAt = context.currentTime - offset;
    playing = true;
    frame = requestAnimationFrame(tick);
  }

  function pause(at = time) {
    cancelAnimationFrame(frame);
    stopSources();
    offset = at;
    time = at;
    playing = false;
  }

  function toggle() {
    if (playing) pause();
    else play();
  }

  function seek(seconds) {
    const wasPlaying = playing;
    pause(Math.max(0, Math.min(length, seconds)));
    if (wasPlaying) play();
  }

  function flip(list, id) {
    return list.includes(id) ? list.filter((item) => item !== id) : [...list, id];
  }

  function draw(canvas, lane) {
    const scale = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!width || !height) return;
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
    const paint = canvas.getContext("2d");
    paint.scale(scale, scale);
    paint.fillStyle =
      getComputedStyle(canvas).getPropertyValue(`--${lane.source}`).trim() || "#b6bbc2";
    const middle = height / 2;
    for (let x = 0; x < width; x++) {
      const peak = lane.peaks[Math.min(COLUMNS - 1, Math.floor((x / width) * COLUMNS))];
      const bar = Math.max(1, peak * height * 0.9);
      paint.fillRect(x, middle - bar / 2, 1, bar);
    }
  }

  function lanePaint(canvas, lane) {
    draw(canvas, lane);
    const observer = new ResizeObserver(() => draw(canvas, lane));
    observer.observe(canvas);
    return () => observer.disconnect();
  }

  function seekFrom(event) {
    const box = event.currentTarget.getBoundingClientRect();
    seek(((event.clientX - box.left) / box.width) * length);
  }

  // Another player starting takes over the speakers.
  function onOtherPlay(event) {
    if (playing && event.target instanceof HTMLAudioElement) pause();
  }

  $effect(() => {
    document.addEventListener("play", onOtherPlay, true);
    return () => document.removeEventListener("play", onOtherPlay, true);
  });

  onDestroy(() => {
    cancelAnimationFrame(frame);
    stopSources();
    context?.close();
  });
</script>

<section class="mixer" aria-label="Stem mixer">
  <div class="mixer-head">
    <strong>Stem mixer</strong>
    {#if state === "ready"}
      <button
        type="button"
        class="mixer-play"
        aria-label={playing ? "Pause stems" : "Play stems"}
        onclick={toggle}
      >
        <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">
          {#if playing}
            <path d="M3 2h4v12H3zM9 2h4v12H9z" fill="currentColor" />
          {:else}
            <path d="M4 2.5v11l9-5.5z" fill="currentColor" />
          {/if}
        </svg>
      </button>
      <span class="mixer-time">{clock(time)}</span>
      <span class="mixer-time dim">/ {clock(length)}</span>
    {/if}
  </div>
  {#if state === "idle"}
    <p class="note">Play the stems together and mute or solo any of them. Nothing is rendered.</p>
    <button type="button" onclick={load}>Open the mixer</button>
  {:else if state === "loading"}
    <p class="note" role="status">Loading the stems…</p>
  {:else if state === "failed"}
    <p class="error">{message}</p>
    <button type="button" onclick={load}>Try again</button>
  {:else}
    {#each lanes as lane (lane.id)}
      <div class="lane {lane.source}" class:silent={!heard.has(lane.id)}>
        <div class="lane-head">
          <span class="lane-name">{lane.label}</span>
          <button
            type="button"
            class="lane-button"
            aria-label="Mute {lane.label}"
            aria-pressed={muted.includes(lane.id)}
            onclick={() => (muted = flip(muted, lane.id))}>M</button
          >
          <button
            type="button"
            class="lane-button"
            aria-label="Solo {lane.label}"
            aria-pressed={soloed.includes(lane.id)}
            onclick={() => (soloed = flip(soloed, lane.id))}>S</button
          >
        </div>
        <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
        <div class="lane-wave" onclick={seekFrom}>
          <canvas {@attach (canvas) => lanePaint(canvas, lane)}></canvas>
          <span class="lane-needle" style:left="{length ? (time / length) * 100 : 0}%"></span>
        </div>
      </div>
    {/each}
  {/if}
</section>
