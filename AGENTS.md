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

Inputs are mono/stereo WAV or MP3. Default limits are 200 MB and 900 seconds, with sample rates from 8 to 192 kHz. Validate actual decoded content, not just extensions or MIME headers. Original audio remains available in its input format.

| Mode | Exported outputs |
| --- | --- |
| `all` | Four WAVs: vocals, drums, bass, other |
| `vocals` | `vocals.wav` only |
| `instrumental` | `instrumental.wav`: drums + bass + other |
| `custom` | `mix.wav`: the selected sources summed together |

The selector previews output grouping before submission. A custom selection must contain at least one unique supported source. `keep` is valid only for custom mode. Mode and selection persist with the job and survive retries. Older jobs migrate to `all`.

All generated audio is 44.1 kHz stereo, 32-bit float WAV. Preserve relative levels when summing sources; do not independently normalize or clip them. WAV export does not restore information lost in an MP3 input. ZIPs contain only the requested outputs.

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

A job can cover one section of the track (`range_start`/`range_end`) or several (`ranges`, a JSON list of `[start, end]` pairs; NULL with both range columns NULL means the whole track). One pair is stored in `range_start`/`range_end` either way, so older jobs and the single-section path stay the same. The API validates ranges after decoding, `inference.read_section` reads each one with `CONTEXT_SECONDS` of extra audio and reports the exact trim. For every mode except `all`, `write_outputs` splices each processed section into the original song (`splice`, 10 ms crossfade at inner edges) so the result is the whole song. `all` with one section returns section-only stems; `all` with several ranges returns full-length stems with audio only inside the ranges. Mixxx cues are read server-side from its SQLite library (`mixxx.py`, read-only, `GET /api/mixxx/cues`). The section picker (waveform, markers, stretch buttons, preview) is `frontend/src/components/RangesPage.svelte` with `frontend/src/lib/waveform.js`; the From/To inputs are its single source of truth, and the edges of that selection and of each saved range can be dragged. `tests/browser/section.spec.cjs` tests it without inference (`STEMLAB_TEST_URL` pointing at an API-only server with `STEMLAB_QUEUE_MODE=local`). Inference computes only what the output plan needs: stages are skipped, and `restrict()` runs only the `htdemucs_ft` bag members for the wanted stems (unwanted stems come back as zeros and must not be exported). Other cue parsing lives only in `frontend/src/lib/cues.js` (WAV cue chunks and Rekordbox XML); `tests/browser/cues.spec.cjs` tests it without a server: `npx playwright test tests/browser/cues.spec.cjs`.

## Discussed possibilities — not implemented requirements

The user reported clipped/missing vocal fragments and instrument bleed. We discussed `htdemucs_ft`, extra shifts and greater overlap as experiments, not guaranteed fixes. Inference is configurable per job as independent stages: `model` (Demucs for drums/bass/other: `htdemucs`, `htdemucs_ft`, `hdemucs_mmi` or `ft_mmi`, which averages the fine-tuned and MMI models; `DEMUCS_MODELS` in `config.py` maps each choice to model names and is the only place to add one), `vocals` (`demucs`, or Roformer choices from `CHECKPOINTS` in `roformer.py`: `melband`, `bs`, `beta4`, `bs1296`, `ensemble`, `ensemble_all`; each is a UVR-catalog checkpoint run through `audio-separator`, and a new one must load through `demix()` and return a vocals stem, see `vocals_of`) and `instruments_from` (`residual`, `mix`, or `inverse`: mix minus the Roformer vocals, no Demucs, valid only when `outputs.is_instrumental(plan)`; the API rejects other combinations and it is not a valid global default), plus `shifts` and `overlap` for the Demucs stage. Defaults are `htdemucs_ft`, `ensemble`, `residual`, 2 shifts and 0.5 overlap (`STEMLAB_MODEL`, `STEMLAB_VOCALS`, `STEMLAB_INSTRUMENTS_FROM`, `STEMLAB_SHIFTS`, `STEMLAB_OVERLAP`). The Roformer stage (`roformer.py`) bypasses `audio-separator`'s file output (it normalizes peaks and writes integer WAVs) by calling `demix()` directly. The `diffq` dependency is overridden out in `pyproject.toml` because it needs Python headers to build and only the library's own Demucs code imports it. The user reported a bubbly artifact in the bass from some model combinations; the cause was not diagnosed, which is why every stage is selectable. Quality gains are based on published benchmarks and were not verified on the user's problem fragments. Diagnose a problematic audio fragment before claiming a quality improvement.

We also discussed quality presets, gentle/aggressive vocal cleanup, original-audio blending and live stem volume/mute/solo controls. These were question-only discussions; do not implement them automatically. There is no universal model “separation strength” parameter. Quality/model changes require reprocessing; mixing can be interactive after separation. Cleanup can damage syllables and quiet vocals. Full post-processing stem controls would require retaining internal stems for modes that currently export only a combined result.
