<script>
  import "./Transport.css";
  import { clock } from "../lib/format.js";

  // One strip for whichever preview played last: it drives that player, so seeking and
  // pausing work from one place while each output keeps its own player and download link.
  let audio = $state(null);
  let playing = $state(false);
  let time = $state(0);
  let length = $state(0);

  function follow(player) {
    time = player.currentTime || 0;
    length = Number.isFinite(player.duration) ? player.duration : 0;
    playing = !player.paused;
  }

  function onMedia(event) {
    const player = event.target;
    if (!(player instanceof HTMLAudioElement)) return;
    if (event.type === "play") audio = player;
    if (player === audio) follow(player);
  }

  $effect(() => {
    const events = ["play", "pause", "ended", "timeupdate", "loadedmetadata", "durationchange"];
    for (const name of events) document.addEventListener(name, onMedia, true);
    return () => {
      for (const name of events) document.removeEventListener(name, onMedia, true);
    };
  });

  const label = $derived(
    audio?.getAttribute("aria-label")?.replace(/ preview$/, "") || "Preview",
  );

  function toggle() {
    if (!audio?.isConnected) {
      audio = null;
      return;
    }
    if (audio.paused) audio.play();
    else audio.pause();
  }

  function seek(event) {
    if (audio?.isConnected) audio.currentTime = Number(event.currentTarget.value);
  }
</script>

{#if audio}
  <div class="transport-strip" role="region" aria-label="Transport">
    <button
      type="button"
      class="transport-play"
      aria-label={playing ? "Pause" : "Play"}
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
    <span class="transport-name">{label}</span>
    <span class="transport-time">{clock(time)}</span>
    <input
      class="transport-seek"
      type="range"
      min="0"
      max={length || 0}
      step="0.1"
      value={time}
      aria-label="Position"
      disabled={!length}
      oninput={seek}
    />
    <span class="transport-time dim">{clock(length)}</span>
  </div>
{/if}
