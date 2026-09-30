<script>
  import "./DeckWave.css";
  import { onMount } from "svelte";
  import { clock } from "../lib/format.js";
  import { barLines, beatInterval, beatLines, nearestBeat } from "../lib/grid.js";
  import { refinePeaks } from "../lib/waveform.js";

  let {
    peaks = [],
    samples = null,
    sampleRate = 0,
    scale = 1,
    duration = 0,
    bpm = null,
    downbeat = null,
    needle = 0,
    zoom = 1,
    volume = 1,
    ranges = [],
    selection = null,
    cues = [],
    armed = false,
    onseek,
    onzoom,
    onvolume,
    ondownbeat,
    onEdge,
  } = $props();

  const MIN_ZOOM = 1;
  const MAX_ZOOM = 64;
  const MIN_WINDOW = 0.25;
  const SCROLL_PIXEL = 1;

  let root;
  let overviewCanvas;
  let detailCanvas;
  let suppressClick = false;
  let painted = null;

  const magnification = $derived(clampZoom(zoom, duration));
  const view = $derived(viewWindow(duration, needle, magnification));
  const selectionSpan = $derived(selectionWindow(selection, duration));
  const playhead = $derived(Number.isFinite(needle) ? needle : 0);
  const needleAt = $derived(needlePercent(view, playhead, magnification));
  const viewport = $derived(viewportBox(duration, view));

  function clampZoom(value, trackDuration) {
    const limit =
      trackDuration > 0
        ? Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, trackDuration / MIN_WINDOW))
        : MIN_ZOOM;
    const number = Number(value);
    if (!Number.isFinite(number) || number <= 0) return MIN_ZOOM;
    return Math.min(limit, Math.max(MIN_ZOOM, number));
  }

  function viewWindow(trackDuration, playheadTime, level) {
    if (!(trackDuration > 0)) return { start: 0, end: 0, span: 0 };
    if (!(level > 1)) return { start: 0, end: trackDuration, span: trackDuration };
    const span = trackDuration / level;
    const center = Number.isFinite(playheadTime) ? playheadTime : 0;
    const start = center - span / 2;
    return { start, end: start + span, span };
  }

  function needlePercent(wave, playheadTime, level) {
    if (level > 1) return 50;
    if (!(wave.span > 0)) return 0;
    const ratio = (playheadTime - wave.start) / wave.span;
    return Math.min(100, Math.max(0, ratio * 100));
  }

  function viewportBox(trackDuration, wave) {
    if (!(trackDuration > 0) || !(wave.span > 0)) return null;
    const left = Math.max(0, wave.start);
    const right = Math.min(trackDuration, wave.end);
    if (right <= left) return null;
    return {
      left: (left / trackDuration) * 100,
      width: ((right - left) / trackDuration) * 100,
    };
  }

  function selectionWindow(value, trackDuration) {
    if (!value || !(trackDuration > 0)) return null;
    const fromBlank = value.from === "" || value.from == null;
    const toBlank = value.to === "" || value.to == null;
    if (fromBlank && toBlank) return null;
    const from = fromBlank ? 0 : Number(value.from);
    const to = toBlank ? trackDuration : Number(value.to);
    if (!Number.isFinite(from) || !Number.isFinite(to)) return null;
    return { from, to };
  }

  function overlaps(from, to, origin, span) {
    return span > 0 && to > origin && from < origin + span;
  }

  function percents(origin, span, from, to) {
    return {
      left: ((from - origin) / span) * 100,
      right: ((origin + span - to) / span) * 100,
    };
  }

  function trackPercent(time) {
    if (!(duration > 0)) return 0;
    return (time / duration) * 100;
  }

  function finiteRange(range) {
    const from = Number(range?.from);
    const to = Number(range?.to);
    if (!Number.isFinite(from) || !Number.isFinite(to)) return null;
    return { from, to };
  }

  function cssColor(node, name, fallback) {
    const value = getComputedStyle(node).getPropertyValue(name).trim();
    return value || fallback;
  }

  function fitCanvas(canvas) {
    const scale = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!width || !height) return null;
    const bitmapWidth = Math.round(width * scale);
    const bitmapHeight = Math.round(height * scale);
    if (canvas.width !== bitmapWidth || canvas.height !== bitmapHeight) {
      canvas.width = bitmapWidth;
      canvas.height = bitmapHeight;
    }
    const context = canvas.getContext("2d");
    context.setTransform(scale, 0, 0, scale, 0, 0);
    context.clearRect(0, 0, width, height);
    return { context, width, height };
  }

  function columnPeak(values, trackDuration, origin, span, width, x) {
    const count = values?.length ?? 0;
    if (!count || !(trackDuration > 0) || !(span > 0)) return 0;
    const startTime = origin + (x / width) * span;
    const endTime = origin + ((x + 1) / width) * span;
    const first = Math.max(0, Math.floor((startTime / trackDuration) * count));
    const last = Math.min(count, Math.ceil((endTime / trackDuration) * count));
    let peak = 0;
    for (let index = first; index < last; index += 1) {
      const value = values[index];
      if (value > peak) peak = value;
    }
    return peak;
  }

  function drawPeaks(context, values, trackDuration, origin, span, width, height, color) {
    context.fillStyle = color;
    const middle = height / 2;
    for (let x = 0; x < width; x += 1) {
      const peak = columnPeak(values, trackDuration, origin, span, width, x);
      if (!(peak > 0)) continue;
      const bar = Math.max(1, peak * height * 0.92);
      context.fillRect(x, middle - bar / 2, 1, bar);
    }
  }

  function drawLines(context, times, origin, span, width, height, color, alpha, thickness) {
    context.save();
    context.globalAlpha = alpha;
    context.fillStyle = color;
    for (const time of times) {
      const x = Math.round(((time - origin) / span) * width);
      context.fillRect(x - (thickness > 1 ? 1 : 0), 0, thickness, height);
    }
    context.restore();
  }

  function lineSpacing(times, span, width) {
    if (times.length < 2 || !(span > 0)) return Infinity;
    return ((times[1] - times[0]) / span) * width;
  }

  function paintCanvas(canvas, origin, span, showGrid) {
    if (!canvas) return;
    const fitted = fitCanvas(canvas);
    if (!fitted || !(span > 0) || !(duration > 0)) return;
    const { context, width, height } = fitted;
    const refined = showGrid
      ? refinePeaks(
          { peaks, samples, sampleRate, scale, duration },
          origin,
          origin + span,
          width,
        )
      : null;
    if (refined) {
      drawPeaks(context, refined, span, 0, span, width, height, cssColor(canvas, "--secondary", "#d5d3ce"));
    } else {
      drawPeaks(
        context,
        peaks,
        duration,
        origin,
        span,
        width,
        height,
        cssColor(canvas, "--secondary", "#d5d3ce"),
      );
    }
    if (!showGrid) return;
    const amber = cssColor(canvas, "--amber", "#e0a15a");
    const end = origin + span;
    const beats = beatLines(bpm, downbeat, origin, end);
    const bars = barLines(bpm, downbeat, origin, end);
    if (lineSpacing(beats, span, width) >= 4)
      drawLines(context, beats, origin, span, width, height, amber, 0.35, 1);
    if (lineSpacing(bars, span, width) >= 3)
      drawLines(context, bars, origin, span, width, height, amber, 0.9, 2);
  }

  function paintShift(start, span) {
    const width = detailCanvas?.clientWidth || 0;
    if (!(width > 0) || !(span > 0)) return Infinity;
    return (Math.abs(start - painted.start) / span) * width;
  }

  function peaksStale(start, span) {
    if (!painted) return true;
    if (painted.duration !== duration || painted.peaks !== peaks) return true;
    if (painted.bpm !== bpm || painted.downbeat !== downbeat) return true;
    if (painted.span !== span) return true;
    return paintShift(start, span) >= SCROLL_PIXEL;
  }

  function paint() {
    paintCanvas(overviewCanvas, 0, duration, false);
    paintCanvas(detailCanvas, view.start, view.span, true);
    painted = {
      start: view.start,
      span: view.span,
      duration,
      peaks,
      bpm,
      downbeat,
    };
  }

  function changeZoom(factor) {
    const next = clampZoom(Math.round(magnification * factor * 1000) / 1000, duration);
    if (next === magnification) return;
    onzoom?.(next);
  }

  function clampTime(time) {
    if (!(duration > 0)) return 0;
    return Math.min(duration, Math.max(0, time));
  }

  function timeAt(clientX, node) {
    const box = node.getBoundingClientRect();
    if (!box.width || !(view.span > 0)) return 0;
    const ratio = Math.min(1, Math.max(0, (clientX - box.left) / box.width));
    return view.start + ratio * view.span;
  }

  function activate(time) {
    if (!(duration > 0)) return;
    if (armed) {
      if (beatInterval(bpm) == null || typeof downbeat !== "number" || !Number.isFinite(downbeat))
        ondownbeat?.(clampTime(time));
      else ondownbeat?.(nearestBeat(time, bpm, downbeat));
      return;
    }
    onseek?.(clampTime(time));
  }

  function overviewClick(event) {
    if (!(duration > 0)) return;
    const box = overviewCanvas?.getBoundingClientRect();
    if (!box?.width) return;
    const ratio = Math.min(1, Math.max(0, (event.clientX - box.left) / box.width));
    onseek?.(ratio * duration);
  }

  function detailClick(event) {
    if (suppressClick) {
      suppressClick = false;
      return;
    }
    if (event.target.closest("button")) return;
    if (!detailCanvas) return;
    activate(timeAt(event.clientX, detailCanvas));
  }

  function cueClick(event, time) {
    event.stopPropagation();
    activate(time);
  }

  function edgeTime(kind) {
    if (kind.index < 0) {
      if (!selectionSpan) return kind.edge === "from" ? 0 : duration;
      return kind.edge === "from" ? selectionSpan.from : selectionSpan.to;
    }
    const range = finiteRange(ranges[kind.index]);
    if (!range) return 0;
    return kind.edge === "from" ? range.from : range.to;
  }

  function beginDrag(event, kind) {
    event.preventDefault();
    event.stopPropagation();
    const handle = event.currentTarget;
    const surface = detailCanvas;
    handle.setPointerCapture(event.pointerId);
    const move = (pointer) => {
      if (!surface) return;
      onEdge?.(kind, timeAt(pointer.clientX, surface));
    };
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

  function stopEdgeClick(event) {
    event.stopPropagation();
    suppressClick = false;
  }

  function nudgeEdge(kind, event) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    event.stopPropagation();
    const direction = event.key === "ArrowLeft" ? -1 : 1;
    const current = edgeTime(kind);
    const interval = beatInterval(bpm);
    if (interval != null && typeof downbeat === "number" && Number.isFinite(downbeat)) {
      const bars = event.shiftKey ? 4 : 1;
      onEdge?.(kind, current + direction * interval * 4 * bars);
      return;
    }
    const step = (event.shiftKey ? 1 : 0.1) * direction;
    onEdge?.(kind, current + step);
  }

  $effect(() => {
    const start = view.start;
    const span = view.span;
    duration;
    peaks;
    bpm;
    downbeat;
    if (!peaksStale(start, span)) return;
    const frame = requestAnimationFrame(paint);
    return () => cancelAnimationFrame(frame);
  });

  onMount(() => {
    const wheel = (event) => {
      event.preventDefault();
      if (!event.deltaY) return;
      changeZoom(Math.exp(-event.deltaY / 400));
    };
    root.addEventListener("wheel", wheel, { passive: false });
    const observer = new ResizeObserver(() => paint());
    observer.observe(root);
    window.addEventListener("resize", paint);
    paint();
    return () => {
      root.removeEventListener("wheel", wheel);
      observer.disconnect();
      window.removeEventListener("resize", paint);
    };
  });
</script>

<div class="deck-wave" bind:this={root} aria-label="Waveform">
  <div
    class="deck-detail"
    class:armed
    aria-label={armed ? "Set the downbeat" : "Waveform detail"}
    onclick={detailClick}
  >
    <canvas bind:this={detailCanvas} aria-hidden="true"></canvas>
    {#if view.span > 0}
      <div class="deck-bands">
        {#each ranges as range, index (index)}
          {@const span = finiteRange(range)}
          {#if span && overlaps(span.from, span.to, view.start, view.span)}
            {@const box = percents(view.start, view.span, span.from, span.to)}
            <div class="deck-band" style:left="{box.left}%" style:right="{box.right}%">
              <button
                type="button"
                class="deck-edge start"
                aria-label="Range start, {clock(span.from)}"
                onpointerdown={(event) => beginDrag(event, { edge: "from", index })}
                onclick={stopEdgeClick}
                onkeydown={(event) => nudgeEdge({ edge: "from", index }, event)}
              ></button>
              <button
                type="button"
                class="deck-edge end"
                aria-label="Range end, {clock(span.to)}"
                onpointerdown={(event) => beginDrag(event, { edge: "to", index })}
                onclick={stopEdgeClick}
                onkeydown={(event) => nudgeEdge({ edge: "to", index }, event)}
              ></button>
            </div>
          {/if}
        {/each}
      </div>
      {#if selectionSpan && overlaps(selectionSpan.from, selectionSpan.to, view.start, view.span)}
        {@const box = percents(view.start, view.span, selectionSpan.from, selectionSpan.to)}
        <div class="deck-selection" style:left="{box.left}%" style:right="{box.right}%">
          <button
            type="button"
            class="deck-edge start"
            aria-label="Section start"
            onpointerdown={(event) => beginDrag(event, { edge: "from", index: -1 })}
            onclick={stopEdgeClick}
            onkeydown={(event) => nudgeEdge({ edge: "from", index: -1 }, event)}
          ></button>
          <button
            type="button"
            class="deck-edge end"
            aria-label="Section end"
            onpointerdown={(event) => beginDrag(event, { edge: "to", index: -1 })}
            onclick={stopEdgeClick}
            onkeydown={(event) => nudgeEdge({ edge: "to", index: -1 }, event)}
          ></button>
        </div>
      {/if}
      <div class="deck-markers">
        {#each cues as cue, index (`${cue.label}|${cue.time}|${index}`)}
          {#if Number.isFinite(cue.time) && cue.time >= view.start && cue.time <= view.end}
            <button
              type="button"
              class="deck-marker"
              style:left="{percents(view.start, view.span, cue.time, cue.time).left}%"
              title="{cue.label} · {clock(cue.time)}"
              aria-label="{cue.label} · {clock(cue.time)}"
              onclick={(event) => cueClick(event, cue.time)}
            ></button>
          {/if}
        {/each}
      </div>
    {/if}
    {#if duration > 0}
      <div class="deck-needle" style:left="{needleAt}%"></div>
    {/if}
  </div>
  <div class="deck-overview" aria-label="Track overview" onclick={overviewClick}>
    <canvas bind:this={overviewCanvas} aria-hidden="true"></canvas>
    {#if viewport}
      <div class="deck-viewport" style:left="{viewport.left}%" style:width="{viewport.width}%"></div>
    {/if}
    {#if duration > 0}
      <div class="deck-bands">
        {#each ranges as range, index (index)}
          {@const span = finiteRange(range)}
          {#if span && overlaps(span.from, span.to, 0, duration)}
            {@const box = percents(0, duration, span.from, span.to)}
            <div class="deck-band" style:left="{box.left}%" style:right="{box.right}%"></div>
          {/if}
        {/each}
      </div>
      {#if selectionSpan}
        {@const box = percents(0, duration, selectionSpan.from, selectionSpan.to)}
        <div class="deck-selection" style:left="{box.left}%" style:right="{box.right}%"></div>
      {/if}
      <div class="deck-markers">
        {#each cues as cue, index (`${cue.label}|${cue.time}|${index}`)}
          {#if Number.isFinite(cue.time)}
            <span class="deck-cue-tick" style:left="{trackPercent(cue.time)}%"></span>
          {/if}
        {/each}
      </div>
      <div
        class="deck-needle"
        style:left="{Math.min(100, Math.max(0, trackPercent(playhead)))}%"
      ></div>
    {/if}
  </div>
  <div class="deck-tools">
    <div class="deck-zoom" role="group" aria-label="Waveform zoom">
      <button
        type="button"
        disabled={!(duration > 0) || magnification <= MIN_ZOOM}
        onclick={() => changeZoom(1 / 1.25)}>Zoom out</button
      >
      <button
        type="button"
        disabled={!(duration > 0) || magnification >= clampZoom(MAX_ZOOM, duration)}
        onclick={() => changeZoom(1.25)}>Zoom in</button
      >
    </div>
    <label class="deck-volume">
      Volume
      <input
        type="range"
        min="0"
        max="1"
        step="0.01"
        value={volume}
        aria-label="Volume"
        aria-valuemin="0"
        aria-valuemax="1"
        aria-valuenow={volume}
        aria-valuetext={`${Math.round(volume * 100)}%`}
        disabled={!(duration > 0)}
        oninput={(event) => onvolume?.(Number(event.currentTarget.value))}
      />
    </label>
  </div>
</div>
