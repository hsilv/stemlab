<script>
  import "./ResultPlayer.css";
  import { bandColor, bandPalette, waveformOf } from "../lib/waveform.js";

  // One result: its coloured waveform with a needle, above the player that plays it. A click
  // on the wave seeks the player. The audio is read for the picture only once it is on screen.
  let { src, label, onplay } = $props();

  let player = $state(null);
  let canvas = $state(null);
  let box = $state(null);
  let wave = $state(null);
  let failed = $state(false);
  let needle = $state(0);
  let frame = 0;
  let loading = false;

  async function read() {
    if (loading || wave) return;
    loading = true;
    try {
      const response = await fetch(src);
      if (!response.ok) throw new Error("not available");
      wave = await waveformOf(await response.blob());
    } catch {
      failed = true;
    }
  }

  function draw() {
    if (!canvas || !wave) return;
    const scale = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!width || !height) return;
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
    const paint = canvas.getContext("2d");
    paint.scale(scale, scale);
    const style = getComputedStyle(canvas);
    const palette = bandPalette(
      style.getPropertyValue("--band-low"),
      style.getPropertyValue("--band-mid"),
      style.getPropertyValue("--band-high"),
    );
    const plain = style.getPropertyValue("--secondary").trim() || "#b6bbc2";
    const middle = height / 2;
    for (let x = 0; x < width; x++) {
      const at = (x + 0.5) / width;
      const peak = wave.peaks[Math.min(wave.peaks.length - 1, Math.floor(at * wave.peaks.length))];
      if (!(peak > 0)) continue;
      paint.fillStyle = palette ? bandColor(wave.bands, at * wave.duration, wave.duration, palette) : plain;
      const bar = Math.max(1, peak * height * 0.92);
      paint.fillRect(x, middle - bar / 2, 1, bar);
    }
  }

  $effect(() => {
    if (!box) return;
    const watcher = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        read();
        watcher.disconnect();
      }
    });
    watcher.observe(box);
    return () => watcher.disconnect();
  });

  $effect(() => {
    if (!canvas || !wave) return;
    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(canvas);
    return () => observer.disconnect();
  });

  function follow() {
    if (player) {
      const length = player.duration || wave?.duration || 0;
      needle = length > 0 ? Math.min(1, player.currentTime / length) : 0;
    }
  }

  function run() {
    cancelAnimationFrame(frame);
    follow();
    if (player && !player.paused) frame = requestAnimationFrame(run);
  }

  function seek(event) {
    const bounds = event.currentTarget.getBoundingClientRect();
    const length = player.duration || wave?.duration || 0;
    if (!(length > 0)) return;
    player.currentTime = ((event.clientX - bounds.left) / bounds.width) * length;
    follow();
  }

  $effect(() => () => cancelAnimationFrame(frame));
</script>

<div class="result" bind:this={box}>
  {#if !failed}
    <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
    <div class="result-wave" class:ready={!!wave} onclick={seek}>
      <canvas bind:this={canvas}></canvas>
      {#if wave}
        <span class="result-needle" style:left="{needle * 100}%"></span>
      {/if}
    </div>
  {/if}
  <audio
    bind:this={player}
    controls
    preload="none"
    {src}
    aria-label="{label} preview"
    onplay={(event) => {
      onplay?.(event);
      run();
    }}
    onpause={run}
    onended={run}
    onseeked={follow}
    ontimeupdate={follow}
  ></audio>
</div>
