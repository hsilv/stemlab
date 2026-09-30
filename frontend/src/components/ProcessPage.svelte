<script>
  import "./ProcessPage.css";
  import TrackDetail from "./TrackDetail.svelte";
  import { session } from "../lib/state.svelte.js";
</script>

<div
  id="page-process"
  class="page"
  class:is-on={session.step === "process"}
  class:back={session.motion === "back"}
  hidden={session.step !== "process"}
>
  <div class="page-head">
    <h2>Processing.</h2>
  </div>
  <div id="upload-status" hidden={!session.uploading}>
    <label for="upload-progress" id="upload-label">{session.uploadLabel}</label>
    <progress id="upload-progress" max="100" value={session.progress}></progress>
  </div>
  <TrackDetail />
</div>
