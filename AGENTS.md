# StemLab agent instructions

These instructions apply to this repository. Read the relevant source before changing behavior; this file records project intent and conventions, not a substitute for the code. See [README.md](README.md) for the user-facing setup and API reference.

## Product and scope

StemLab is a working, local audio separation application, not just an infrastructure template. Users upload WAV or MP3 audio, choose what to isolate or keep together, then preview and download the results. Keep the workflow simple and interactive.

- Prefer free, open-source tools and local processing. Audio must stay on the user's machine unless the user explicitly requests a different architecture.
- Preserve GPU acceleration and CPU support. The user's NVIDIA RTX 5060 Ti with 16 GB VRAM has successfully run inference with this project. Verify current hardware/runtime availability rather than assuming it.
- The app is currently for one machine, bound to localhost, without user accounts. Public hosting and multi-user operation are separate work.
- Respect question-only requests: explain possibilities without editing files or implementing the ideas discussed.
- Keep implementation details out of the normal user workflow unless they help users choose an option. The current interface is English; respond to the user in their current language.

## Implemented behavior

Inputs are mono/stereo WAV, MP3 or FLAC (`jobs.INPUT_SUFFIXES` owns the list; the stored original keeps its own extension). The Playlist booth still scans WAV and MP3 only. Default limits are 200 MB and 900 seconds, with sample rates from 8 to 192 kHz. Validate actual decoded content, not just extensions or MIME headers. Original audio remains available in its input format.

| Mode | Exported outputs |
| --- | --- |
| `all` | Four FLAC files: vocals, drums, bass, other |
| `vocals` | `vocals.flac` only |
| `instrumental` | `instrumental.flac`: drums + bass + other |
| `custom` | `mix.flac`: the selected sources summed together |
| `extend` | `extended.flac`: an intro and outro around the whole song (below) |
| `generate` | `backing.flac`: a backing track made by ACE-Step from a prompt and an optional reference (below) |

The selector previews output grouping before submission. A custom selection must contain at least one unique supported source. `keep` is valid only for custom mode. Mode and selection persist with the job and survive retries. Older jobs migrate to `all`.

All generated audio is 44.1 kHz stereo, 24-bit FLAC (`STEM_SUFFIX` in `outputs.py`; jobs finished earlier hold float WAV under the same names, so always locate stems with `outputs.stem_file`). Preserve relative levels when summing sources; do not independently normalize or clip them: `inference.encode_all` applies one shared gain across a job's outputs only when a peak would exceed full scale. Downloads can be re-encoded on request (`exports.py`: FLAC/24-bit WAV through SoundFile, 320 kbps MP3 through `ffmpeg`; `/api/config` `export_formats` omits `mp3` without it); converted files live in a per-request `exports/` scratch folder that the response deletes, nothing extra is stored. Lossless export does not restore information lost in an MP3 input. ZIPs contain only the requested outputs.

Demucs currently analyzes all four sources regardless of the export mode. The app writes only the chosen outputs; individual internal stems are not retained for every mode. Do not present output selection as a separation-quality improvement or inference speedup.

## Architecture

| Path | Responsibility |
| --- | --- |
| `src/stemlab/main.py` | FastAPI entry point, static files, health routes, cross-origin write protection |
| `src/stemlab/routes.py` | Streaming upload, validation, job API, range playback and downloads |
| `src/stemlab/outputs.py` | Shared output-plan validation, source names and group definitions |
| `src/stemlab/jobs.py` | SQLite metadata, schema migration, task claims, source paths and stale recovery |
| `src/stemlab/worker.py` | Shared job execution, subprocess lifecycle, cancellation, timeout and ZIP creation |
| `src/stemlab/inference.py` | Demucs inference and output mixing/encoding |
| `src/stemlab/separation.py` | Common output type and separation protocol |
| `src/stemlab/local.py` | Starts the local HTTP server and polling worker |
| `src/stemlab/local_worker.py` | SQLite queue polling for direct local operation |
| `src/stemlab/config.py` | Validated `STEMLAB_` settings and `.env` loading |
| `frontend/` | Svelte 5 interface. `npm run build` writes static files under `src/stemlab/web/ui/` |
| `compose.yaml`, `compose.gpu.yaml` | Celery/Valkey deployment and NVIDIA worker override |

Two execution paths must remain supported: the direct launcher uses SQLite polling without Docker or Valkey; Compose uses Celery and Valkey. Both use the same job execution code and persistent metadata. Avoid duplicating processing behavior between these paths.

PyTorch imports and heavy inference belong in the child process, not HTTP request handlers. Long work must remain cancellable. Use one inference worker by default to limit GPU memory usage.

## Data and lifecycle invariants

- Store data under `STEMLAB_DATA_DIR` (default `data/`). Model weights default to `data/models/`, overridable with `TORCH_HOME`. Preserve user uploads, job history and cached weights.
- Use generated job IDs and validated output IDs for paths. Preserve `jobs.source_path()` handling of original WAV/MP3 files, and download allowlists from `output_plan()`.
- Uploads are raw request bodies, not multipart: `POST /api/jobs?filename=track.mp3&mode=instrumental`. Custom mode adds e.g. `keep=vocals,bass`.
- Preserve bounded streaming uploads, decoded validation, correct original MIME types, and HTTP Range playback.
- Job claims must match the current task ID and queued status. Retries get new task IDs, keeping the original source and selection.
- Preserve `queued → running → completed/failed` and `running → cancelling → cancelled`. Do not allow deletion of active jobs.
- Inference subprocesses must stop before cancellation is finalized and partial outputs are removed. Preserve timeouts and the file lock inherited by the child process.
- Stale recovery must not release jobs whose process still holds the lock. Use additive, idempotent migrations that preserve existing records.
- Keep polling from recreating audio players on every heartbeat; that interrupts playback. Render only when relevant state changes.
- Show real processing stages, not invented completion percentages.

## Environment and commands

Run commands from the repository root. Supported Python versions are 3.11 and 3.12 on Linux; locking uses `fcntl`. Dependencies are managed by `uv.lock`. The pinned inference stack is Demucs 4.0.1, PyTorch/torchaudio 2.7.1, with CUDA 12.8 wheels for the `cuda` extra. Upgrade this stack deliberately and verify actual inference afterward.

```sh
# NVIDIA setup and launch
uv sync --frozen --extra cuda
uv run --frozen --extra cuda python -m stemlab.local

# CPU alternative: use this extra instead of cuda
uv sync --frozen --extra inference
uv run --frozen --extra inference python -m stemlab.local

# Launch an already configured environment without syncing it
.venv/bin/python -m stemlab.local
```

The `cuda` and `inference` extras are mutually exclusive. **Plain `uv sync` or `uv run` can remove installed inference dependencies.** On an existing GPU environment, use `.venv/bin/…` for checks or keep `--extra cuda` on uv commands. Lightweight CI can deliberately use `uv sync --frozen` without inference extras.

The default app URL is `http://localhost:8000`, with API docs at `/docs`. `STEMLAB_DEVICE=auto` chooses an available GPU or CPU; `cuda` explicitly requires CUDA. Check for active jobs before restarting an existing instance. Use a separate port and data directory for integration tests.

```sh
# Compose: CPU, or NVIDIA worker
docker compose up --build --wait
docker compose -f compose.yaml -f compose.gpu.yaml up --build --wait
```

GPU containers require NVIDIA Container Toolkit and an appropriate Docker runtime. Check daemon availability; a valid Compose configuration does not prove containers start. Do not remove persistent volumes as a routine troubleshooting step.

## Verification

Use checks appropriate to the changed behavior. Documentation-only edits do not require model inference or a full test run.

```sh
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest
npm run build --prefix frontend
docker compose -f compose.yaml -f compose.gpu.yaml config --quiet

# Explicit real-model smoke test; may download weights
.venv/bin/python scripts/verify_inference.py
```

Python tests cover API validation, lifecycle behavior, old-schema migration and exact output sums. Keep these tests independent of GPU/model downloads. Use real inference when changing the model adapter, audio decoding or device compatibility. Synthetic inference verifies execution and output structure; it does not establish perceptual separation quality.

Browser tests require a running app, perform real inference, and use `.venv/bin/python` to generate WAV/MP3 fixtures:

```sh
# Terminal 1: isolated test instance, reusing the project model cache
TORCH_HOME="$PWD/data/models" STEMLAB_DATA_DIR=/tmp/stemlab-browser-data \
  STEMLAB_PORT=8765 .venv/bin/python -m stemlab.local

# Terminal 2
npm ci
npm run build --prefix frontend
npx playwright install chromium
npm run test:browser
```

`STEMLAB_TEST_URL` overrides the browser target. Tests exercise mode selection, actual playback, ZIP contents, persistence, invalid inputs and mobile layout; screenshots go to `test-results/`. Inspect relevant screenshots for UI changes. Stop only the test processes you started. The Python process serves the built interface; `npm run dev --prefix frontend` is only for interface work against an already running API (`STEMLAB_DEV_API`, default `http://127.0.0.1:8000`).

Keep `.env`, uploaded audio, model files, `data/`, `.venv/`, `node_modules/` and test artifacts out of version control. Update README when changing commands, configuration, modes or API behavior.

## Sections

A job can cover one section of the track (`range_start`/`range_end`) or several (`ranges`, a JSON list of `[start, end]` pairs; NULL with both range columns NULL means the whole track). One pair is stored in `range_start`/`range_end` either way, so older jobs and the single-section path stay the same. The API validates ranges after decoding, `inference.read_section` reads each one with `CONTEXT_SECONDS` of extra audio and reports the exact trim. For every mode except `all`, `write_outputs` splices each processed section into the original song (`splice`, 10 ms crossfade at inner edges) so the result is the whole song. `all` with one section returns section-only stems; `all` with several ranges returns full-length stems with audio only inside the ranges. Mixxx cues are read server-side from its SQLite library (`mixxx.py`, read-only, `GET /api/mixxx/cues`). `POST /api/jobs?from_job=<id>` (no body) makes another edit of an uploaded song. Jobs of one song share `song_id` (the first job's id; NULL on older jobs means the job is its own song); the crate groups by it in `frontend/src/lib/songs.js`: `routes.reuse_source` hard-links the original into the new job's folder (copy if that fails) and the job is otherwise normal. The UI path is `editAgain` in `frontend/src/lib/deck.js` (fetches the original only for the waveform and preview, sets `session.sourceJob`, reuses the stored reading via `reuseReading`). Analysis (`analysis.py`, child process) reads tempo and key as follows. Tempo and bar: the Beat This! network (`inference.track_beats`, optional `beat-this` package, MIT, weights downloaded once into the model cache, no GPU lock) says which pulse is the beat and which beats start a bar; the signal then fixes the exact period and hit positions. It exists because autocorrelation alone mistakes a 3-3-2 dembow for a 4:3 faster tempo (about 6% of the author's reggaeton library). Without the package or the weights the signal-only path runs (autocorrelation with a tempo prior, plus a drums-and-bass isolation to break octave ties). Key: chroma of the isolated bass+other stems (`isolate_window("harmonic")`, 90 s, GPU lock waited at most 30 s, else the full mix); a close call between keys that mix together (same Camelot number, or adjacent in the same mode) still returns the winner. Choosing a file posts it to `POST /api/analyses` (raw body, same WAV/MP3 checks as a job) and polls `GET /api/analyses/{id}` until `completed` or `failed`. Load stays on that step until then. Failure sets `session.message` and allows continuing without a grid. The poll field `warning` is stored on the job as `analysis_warning`. Job create takes optional `bpm`, `camelot`, `key_name`, `downbeat`, and `analysis_warning`; the UI sends the downbeat after any nudge. The section picker is `frontend/src/components/RangesPage.svelte`: peaks come from `frontend/src/lib/waveform.js`, and `DeckWave` (`frontend/src/components/DeckWave.svelte`, grid math in `frontend/src/lib/grid.js`) draws the wave, cues, and beat grid. The From/To inputs are the single source of truth. Cue markers and chips set the start then the end. A **Snap to the beat grid** switch (`session.snap`, on by default, disabled without a grid) controls snapping to the nearest beat (`nearestBeat`; arrows move one beat, Shift one bar) for clicks on the wave, dragged edges and arrow-key nudges; with it off they land exactly (arrows 0.01 s, Shift 0.1 s). Cue clicks and typed From/To are never snapped. DeckWave zooms up to 400x at the pointer (wheel), pans by dragging the zoomed wave or a horizontal wheel (`panTo`; a new needle position returns the window to the needle), and clicks store millisecond precision. `followPreview` (section.js) moves `session.needle` with the section preview. **Preview section** stays a separate player from the Load waveform. A finished job shows BPM and key in the track detail when those columns are present, and does not draw the grid. `tests/browser/grid.spec.cjs` covers that flow. `tests/browser/section.spec.cjs` covers the picker (`STEMLAB_TEST_URL` pointing at an API-only server with `STEMLAB_QUEUE_MODE=local`); its fixture is a clear grid so the load gate finishes without the isolation fallback. Inference computes only what the output plan needs: stages are skipped, and `restrict()` runs only the `htdemucs_ft` bag members for the wanted stems (unwanted stems come back as zeros and must not be exported). Other cue parsing lives only in `frontend/src/lib/cues.js` (WAV cue chunks and Rekordbox XML); `tests/browser/cues.spec.cjs` tests it without a server: `npx playwright test tests/browser/cues.spec.cjs`.

## Tags

`tags.py` reads tags with ffprobe and copies them with ffmpeg (`-c copy`, so audio is never re-encoded): `copy(source, target, version=, tempo=, cover=, fallback_title=)` writes the source's tags and cover onto the target in place, adds `version` to the title in parentheses, leaves out tool tags and the source's tempo and key, and keeps the target's own tempo and key unless `tempo` overrides them (FLAC `BPM`/`INITIALKEY`, MP3 and WAV `TBPM`/`TKEY`; a WAV carries no cover and drops tempo and key). The worker calls it for every output of a finished job (`worker.tag_outputs`, non-fatal, before the ZIP is written), and converted downloads call it again from the original upload (`routes.convert_or_fail`), so MP3 and WAV carry the same tags. `tagtool.py` is the Tags booth API: references (`job:<id>:<original|output>`, `file:<id>`) are the only way to name a file, uploads are classified by content and swept after an hour, and the target is always copied. Everything is skipped when `tags.available()` is false. Tests: `tests/test_tags.py` (needs ffmpeg) and `tests/browser/tagtool.spec.cjs`.

## Instrumental models

`instruments_from` also takes `direct_resurrection`, `direct_inst_v2` and `direct_bleedless` (`config.instrumental_only` marks them and `inverse` as No-vocals-only; `roformer.INSTRUMENTALS` maps them to BS-Roformer Resurrection (Unwa), MelBand Inst V2 (Unwa) and MelBand Bleedless v3 (Gabox)). They write the whole instrumental from one model and skip the vocal model and Demucs. Checkpoints may name that stem `Instrumental` or `other`, so `separate_instrumental` accepts either. They are not the default because of this benchmark (four 10 s voice-free intros from the author's library, each mixed with a Demucs voice from the same song, mean SDR of the recovered instrumental against the known one): mix minus the two-model Roformer vocals 15.98 dB, Resurrection 15.61, Inst V2 15.52, Bleedless 15.42, becruily 15.36; averaging with the mix-minus-vocals result gave 15.99 at best; on a voice-free input the direct models change the audio more (23 to 38 dB against 43 for mix minus vocals). SDR does not capture how full or clean a result sounds, so the options exist to be judged by ear. Re-run that comparison before changing the default. Manual extended edits keep using mix minus vocals.

## Extended edits

Mode `extend` (`extend.py`, column `jobs.extend` JSON, only via `POST /api/jobs?from_job=...`) makes `intro | song | outro`. `extend.build` is pure numpy and takes a `stems_for(start, end)` callback, so tests need no GPU. Rules to keep: the song is copied untouched at 44.1 kHz stereo and its first downbeat lands on a bar line of the intro (a silent lead-in is trimmed to 10 ms before the downbeat, an audible one is kept); loops are whole bars on the grid, locally re-aligned to the drums' real hits with `analysis.attack_positions` because the global tempo drifts over a song; seams and joins are 10 ms crossfades and layers change on bar lines with 20 ms ramps; the song is cut where its last steady drum groove ends. Only the windows feeding the loops are separated (`inference.isolate_stems`), or sliced from a finished whole-song `all` job's stems (`jobs.full_stems_folder`); the worker runs `python -m stemlab.extend` inside the held inference lock, and `POST /api/jobs/{id}/extend-preview` runs it with `--preview`, waiting at most 30 s for the lock (exit code 75, HTTP 503). BPM and key tags are written into the FLAC with `ffmpeg -c copy` and into MP3 downloads through `exports.track_tags`. UI: the header's **Extender** booth (`session.booth === "extend"`, beside Separate and Playlist; the crate stays visible) shows `ExtendPage.svelte` for the song selected in the crate, loaded through `openForExtender` in `deck.js`; it shares `session.file`/`sourceJob`/`wave` with the Load step, so opening a song there replaces a file chosen but not yet separated. Creating returns to the Separate booth's Result view. The Ranges and Extender pages share one hidden section player (`SectionAudio.svelte`, `session.previewing`), which plays From to To and is paused when the booth changes. Verify structurally, not by ear: run the output through the beat tracker and check the downbeats stay on the bar grid across both joins.

Mode `generate` (`generate.py`, column `jobs.generate` JSON `{prompt, duration, seed}`, only via `POST /api/generate`) has no uploaded song: `jobs.has_source(row)` is false, so Original, tagging and "Edit this song again" are skipped for it, and its row stores 48 kHz stereo and the requested duration. An optional reference is stored as `reference.wav|mp3|flac` in the job folder (`jobs.reference_path`; a crate song is hard-linked with `routes.reuse_source`), and the child trims it to its middle `REFERENCE_SECONDS`. ACE-Step pins `torch==2.10.0`, newer than this project's, so `worker.generate_command` runs `generate.py` with the interpreter in `settings.ace_step_dir/ace/.venv` and `-P` (so this folder's modules cannot shadow ACE-Step's); `generate.py` therefore imports nothing from `stemlab` and loads ACE-Step lazily. It uses the `acestep-v15-sft` model (50 steps) with the 1.7B language model (`thinking=True`, bfloat16, `pt` backend) and a forced instrumental: listening tests against turbo without the language model (turbo sounded thin and low-energy) chose this, and it also gave a steady grid at the requested tempo. The language model loads through a full-precision copy (about 7 GB for a moment), so it is loaded before the diffusion model, or a 12 GB budget runs out of memory. `PYTORCH_ALLOC_CONF=expandable_segments:True` is set before PyTorch starts: a reference adds about 1.9 GB of fixed cost (independent of its length), and this brings the peak of the whole card from about 13.7 GB to about 12.7 GB at 120 s (12.8 GB at 240 s, 810 MB of which was the desktop). Measured wall time, models loaded each job: about 15 s for 30 s of music, 80 s for 120 s, 135 s for 240 s. Tried and not working: `task_type="complete"` on the base model with a vocal as `src_audio` did not follow the vocal (waveform and envelope correlation near 0), so do not offer vocal-conditioned accompaniment without new evidence. Tests: `tests/test_generate.py` (fake child, no GPU) and `tests/browser/generate.spec.cjs`.

A manual edit is `extend = {"operations": [...]}` (`extend._operations` validates, `_check_positions` checks bars and overlaps, `build_manual` assembles). Rules: positions are bars of the original song (0-based in the API, 1-based on screen); the song is cut at bar lines locally aligned to its own hits (`boundary`), each fragment is repeated or trimmed to its bars and a replace fits its hole exactly; pieces are joined by `_assemble` (10 ms crossfades). `inference.separate_fragment` separates one fragment with that operation's own choices through `estimate`, so the Roformer voice models work; all sounds at one volume uses the unseparated mix, and drums+bass+other at one volume with the voice off is always `mix - vocals` (key `instrumental`). A manual edit ignores existing full-song stems (the listener chose models). UI: the manual panel of `ExtendPage.svelte` with `lib/manual.js`; `extend-preview` takes `only` to render one operation with `PREVIEW_AROUND` seconds of context.

## Playlist

The header switches **Separate** / **Playlist** (`booth` in `frontend/src/App.svelte`). Playlist hides the crate and uses the main column (`PlaylistPage.svelte`; folder, pin, and held live in `frontend/src/lib/playlist.js` and clear on reload). Separate is unchanged. `POST /api/playlist/pick` opens a native directory dialog and waits (`zenity --file-selection --directory`, then `kdialog --getexistingdirectory`, then tkinter). Cancel returns `{"cancelled": true}` and does not scan. A chosen path is checked with `_resolved_directory`, the same rule as `GET /api/playlist/browse`. The booth does not ask for a typed path and does not request a folder until that button is used. `POST /api/playlist/scans` body `{path}` starts a scan, `GET /api/playlist/scans/{id}` polls it (`running`, `completed`, `cancelled`, or `failed`; `tracks` and `unread` stay empty until `completed`), and `DELETE /api/playlist/scans/{id}` cancels it and kills the child. The scan includes only direct children whose names end in `.wav` or `.mp3` (`_playlist_audio`): subfolders are navigation, dotfiles are skipped, and a symlink is included only when its resolved path is still a direct child of the chosen directory. One `python -m stemlab.analysis` child runs at a time, on the file in place. Readings are cached in `readings` (`jobs.py`) by resolved path, size, and `st_mtime_ns`. A track with no BPM or no Camelot is `unread` with a reason; a warning with both still lands in `tracks`. `POST /api/playlist/order` body `{tracks, pinned, held}` drops held paths and rows missing BPM or Camelot, then calls `order_tracks` (`playlist.py`). The opener is the slowest BPM, then filename, unless `pinned` is one of those tracks. A legal next track is a Camelot neighbor (same code, one wheel step, 12 meeting 1, or the same number with A and B flipped) within 8% tempo, preferring the written octave over half or double. It must also keep the mood: valence (0 dark to 1 bright) may differ by at most 0.2 (`_MOOD_GAP` in `playlist.py`), so a happy song never follows a sad one; a track with no valence fits anywhere, and a break prefers a track that keeps the mood. Valence and energy come from the analysis child (`analysis._mood`: key lean toward major, brightness, scale consonance, tempo; energy adds loudness and onset activity), are stored with the cached readings, and are only a heuristic from the audio: lyrics are not read. When nothing legal remains the next row is marked `break` and the list continues. `GET /api/playlist/audio?path=` streams that file with HTTP Range; the resolved path must be a `.wav` or `.mp3` whose parent still contains it as a direct child. One player, from the start of the file. No crossfade, no M3U, no Mixxx write.

## Playlist

The header switches **Separate** / **Playlist** (`booth` in `frontend/src/App.svelte`). Playlist hides the crate and uses the main column (`PlaylistPage.svelte`; folder, pin, and held live in `frontend/src/lib/playlist.js` and clear on reload). Separate is unchanged. `POST /api/playlist/pick` opens a native directory dialog and waits (`zenity --file-selection --directory`, then `kdialog --getexistingdirectory`, then tkinter). Cancel returns `{"cancelled": true}` and does not scan. A chosen path is checked with `_resolved_directory`, the same rule as `GET /api/playlist/browse`. The booth does not ask for a typed path and does not request a folder until that button is used. `POST /api/playlist/scans` body `{path}` starts a scan, `GET /api/playlist/scans/{id}` polls it (`running`, `completed`, `cancelled`, or `failed`; `tracks` and `unread` stay empty until `completed`), and `DELETE /api/playlist/scans/{id}` cancels it and kills the child. The scan includes only direct children whose names end in `.wav` or `.mp3` (`_playlist_audio`): subfolders are navigation, dotfiles are skipped, and a symlink is included only when its resolved path is still a direct child of the chosen directory. One `python -m stemlab.analysis` child runs at a time, on the file in place. Readings are cached in `readings` (`jobs.py`) by resolved path, size, and `st_mtime_ns`. A track with no BPM or no Camelot is `unread` with a reason; a warning with both still lands in `tracks`. `POST /api/playlist/order` body `{tracks, pinned, held}` drops held paths and rows missing BPM or Camelot, then calls `order_tracks` (`playlist.py`). The opener is the slowest BPM, then filename, unless `pinned` is one of those tracks. A legal next track is a Camelot neighbor (same code, one wheel step, 12 meeting 1, or the same number with A and B flipped) within 8% tempo, preferring the written octave over half or double. It must also keep the mood: valence (0 dark to 1 bright) may differ by at most 0.2 (`_MOOD_GAP` in `playlist.py`), so a happy song never follows a sad one; a track with no valence fits anywhere, and a break prefers a track that keeps the mood. Valence and energy come from the analysis child (`analysis._mood`: key lean toward major, brightness, scale consonance, tempo; energy adds loudness and onset activity), are stored with the cached readings, and are only a heuristic from the audio: lyrics are not read. When nothing legal remains the next row is marked `break` and the list continues. `GET /api/playlist/audio?path=` streams that file with HTTP Range; the resolved path must be a `.wav` or `.mp3` whose parent still contains it as a direct child. One player, from the start of the file. No crossfade, no M3U, no Mixxx write.

## Discussed possibilities — not implemented requirements

The user reported clipped/missing vocal fragments and instrument bleed. We discussed `htdemucs_ft`, extra shifts and greater overlap as experiments, not guaranteed fixes. Inference is configurable per job as independent stages: `model` (Demucs for drums/bass/other: `htdemucs`, `htdemucs_ft`, `hdemucs_mmi` or `ft_mmi`, which averages the fine-tuned and MMI models; `DEMUCS_MODELS` in `config.py` maps each choice to model names and is the only place to add one), `vocals` (`demucs`, or Roformer choices from `CHECKPOINTS` in `roformer.py`: `melband`, `bs`, `beta4`, `bs1296`, `ensemble`, `ensemble_all`; each is a UVR-catalog checkpoint run through `audio-separator`, and a new one must load through `demix()` and return a vocals stem, see `vocals_of`) and `instruments_from` (`residual`, `mix`, or `inverse`: mix minus the Roformer vocals, no Demucs, valid only when `outputs.is_instrumental(plan)`; the API rejects other combinations and it is not a valid global default), plus `shifts` and `overlap` for the Demucs stage. Defaults are `htdemucs_ft`, `ensemble`, `residual`, 2 shifts and 0.5 overlap (`STEMLAB_MODEL`, `STEMLAB_VOCALS`, `STEMLAB_INSTRUMENTS_FROM`, `STEMLAB_SHIFTS`, `STEMLAB_OVERLAP`). The Roformer stage (`roformer.py`) bypasses `audio-separator`'s file output (it normalizes peaks and writes integer WAVs) by calling `demix()` directly. The `diffq` dependency is overridden out in `pyproject.toml` because it needs Python headers to build and only the library's own Demucs code imports it. The user reported a bubbly artifact in the bass from some model combinations; the cause was not diagnosed, which is why every stage is selectable. Quality gains are based on published benchmarks and were not verified on the user's problem fragments. Diagnose a problematic audio fragment before claiming a quality improvement.

We also discussed quality presets, gentle/aggressive vocal cleanup, original-audio blending and live stem volume/mute/solo controls. These were question-only discussions; do not implement them automatically. There is no universal model “separation strength” parameter. Quality/model changes require reprocessing; mixing can be interactive after separation. Cleanup can damage syllables and quiet vocals. Full post-processing stem controls would require retaining internal stems for modes that currently export only a combined result.

## Desktop app and other platforms

Linux and Windows are supported; macOS is not. Keep platform differences in one place each: `filelock.py` (`try_lock`/`unlock`/`inherit`; `fcntl` or `msvcrt`, and a locked descriptor cannot be passed to a child on Windows), `environment.py` (`venv_python`, `default_mixxx_db`). Do not call `fcntl` or hardcode `.venv/bin/python` elsewhere.

`desktop/` is an Electron shell around the same server. `desktop/backend.js` (no Electron imports, tested with `npm test --prefix desktop`) picks a free port, starts `python -m stemlab.local` with `STEMLAB_EXIT_WITH_PARENT=1` and a pipe on stdin, waits for `/health/live` and stops it; the launcher exits when that pipe closes, so a crashed shell leaves no server behind. `desktop/main.js` runs `scripts/bootstrap.py` through the bundled `uv` on first start (packaged builds only; from a checkout it uses `.venv` and never rebuilds it), then opens the window on `http://127.0.0.1:<port>`. Two flavours: the small build installs PyTorch on the user's first start and `scripts/bootstrap.py` is the only place that chooses `cuda` or `inference`; the full build (`npm run dist:full`, `desktop/electron-builder.full.cjs`) carries `resources/runtime/{python,site-packages}` made by `desktop/scripts/bundle-runtime.mjs`, and `main.js` runs it with `PYTHONPATH` instead of a venv (`backend.bundledRuntime`). Windows full is a zip because NSIS caps an installer at 2 GB. `routes.analysis_interpreter` falls back to `sys.executable` when there is no `.venv` beside the code, which is the case in any installed app. `uv.lock` covers Linux and win32 (`[tool.uv] environments`); regenerate it with the CI's uv version (0.8.22). The interface build is `node frontend/scripts/publish.mjs`, so it runs on Windows.

Verified on Linux only: the shell's backend start, stop and parent-exit, the AppImage and deb builds, a first-run environment install from the packaged layout (CPU build), and the tests. Not verified: any run on Windows, the Electron window itself (it crashed under a headless display here), installing the deb, and the GPU build of the first-run install.

