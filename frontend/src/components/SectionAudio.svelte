<script>
  import { followPreview, stopAtEnd } from "../lib/section.js";
  import { session } from "../lib/state.svelte.js";
</script>

<!-- The one player for hearing a stretch of the loaded song: the Ranges and Extender pages share it. -->
<audio
  id="section-audio"
  hidden
  onplay={(event) => {
    session.previewing = true;
    followPreview(event.currentTarget);
  }}
  onpause={() => (session.previewing = false)}
  ontimeupdate={stopAtEnd}
></audio>
