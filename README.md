# StemLab

A local WAV/MP3 separation app. Upload a track, choose **vocals only**, **no vocals**, **all four stems**, or a **custom mix** of vocals, drums, bass and other instruments. Preview the result and download WAVs or a ZIP. Includes persistent history, cancellation, retries and deletion. No paid services or API keys.

## Run locally with your NVIDIA GPU (recommended)

Requires Linux, Python 3.11/3.12, [uv](https://docs.astral.sh/uv/getting-started/installation/) and an NVIDIA driver supporting CUDA 12.8. PyTorch bundles the CUDA runtime; a separate CUDA toolkit installation is not needed.

```sh
cd stemlab
uv sync --frozen --extra cuda
uv run --frozen --extra cuda python -m stemlab.local
```

Open **http://localhost:8000**. The launcher starts the API and a persistent SQLite job worker; Docker and Valkey are not needed for this mode. Press Ctrl+C to stop both. Queued jobs remain on disk and resume when restarted. Interrupted running jobs become retryable after the stale-job grace period (120 seconds).

The CUDA build uses PyTorch 2.7.1 with CUDA 12.8, which supports the RTX 5060 Ti / Blackwell generation. `STEMLAB_DEVICE=auto` selects CUDA when available. Force GPU use with `STEMLAB_DEVICE=cuda`; this reports failure instead of silently using CPU if CUDA is unavailable.

```sh
# CPU-only installation / launch:
uv sync --frozen --extra inference
uv run --frozen --extra inference python -m stemlab.local
```

The two extras are mutually exclusive. Always include the chosen extra when invoking `uv run`, or uv will remove inference dependencies from the environment. You can also invoke `.venv/bin/python -m stemlab.local` directly after installing.

## Use the app

1. Choose or drop a mono/stereo WAV or MP3 (up to 200 MB and 15 minutes by default).
2. Choose an output mode. In **Custom mix**, check the sounds to keep together; unchecked sounds are excluded. The output preview updates immediately.
3. Click **Separate track**. Upload progress and processing stages appear in the UI.
4. Select a track in history to preview the original and your selected outputs, or download the ZIP.
5. Cancel queued/running jobs, retry failures, or delete finished jobs to reclaim disk space.

| Mode | Generated files |
| --- | --- |
| Vocals only | `vocals.wav` |
| No vocals | `instrumental.wav` — drums, bass and other instruments together |
| All stems | `vocals.wav`, `drums.wav`, `bass.wav`, `other.wav` |
| Custom mix | `mix.wav` — only your checked sources, combined |

Each job saves its selection, including across retries and page reloads. Existing jobs retain all four stems through an automatic SQLite migration. Mixes sum the selected model estimates without individually normalizing sources. Choosing fewer outputs changes the exported audio, not the model's underlying four-source analysis or separation quality.

Original uploads remain available in their input format (WAV or MP3). Generated results are always WAV, avoiding another lossy encoding pass. Converting MP3 to WAV does not restore information already lost in MP3 compression. MP3 decoding uses the bundled libsndfile in SoundFile's Linux wheels; no external conversion service or FFmpeg is needed on the supported setup.

The first separation downloads the approximately 80 MB `htdemucs` model. Later runs reuse the local cache; audio never leaves the machine. Progress displays real stages, not an estimated percentage. Stems are 44.1 kHz stereo, 32-bit float WAV to avoid clipping or separate normalization. Original sample rate and duration appear in the UI. Model separation is approximate and can contain artifacts/bleed; “other” combines instruments outside the three named categories.

Files and SQLite metadata live in `data/`; model weights are cached in `data/models/`. Files are retained until you delete the job. A ZIP duplicates stem storage for fast downloads. Allow several GB of free disk space for long tracks. History displays the latest 100 jobs; older jobs remain accessible by ID through the API.

## Docker Compose

Requires a running Docker daemon and Compose. CPU:

```sh
docker compose up --build --wait
```

NVIDIA GPU worker (Docker Engine with [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)):

```sh
docker compose -f compose.yaml -f compose.gpu.yaml up --build --wait
```

Only the worker receives GPU access. The API, Celery worker and Valkey queue share persistent local volumes. Both modes bind the API to localhost. Linux Docker Desktop may not expose the host GPU; use native Docker Engine for the GPU configuration, or use the direct local launcher above.

```sh
docker compose logs -f api worker
docker compose exec -T api python -c "from stemlab.worker import ping; print(ping.delay().get(timeout=30))"
docker compose down
```

Use the same `-f` options when managing the GPU stack. Stopping preserves data; `down --volumes` deletes it. Rebuild after source changes. Container images are version-scoped, not digest-pinned.

## Configuration

Copy `.env.example` to `.env` to override settings. Shell environment takes precedence. In Compose, service URLs and storage paths are set by Compose.

| Setting | Default | Purpose |
| --- | --- | --- |
| `STEMLAB_DEVICE` | `auto` | `auto`, `cuda`, or `cpu` |
| `STEMLAB_PORT` | `8000` | Local web port |
| `STEMLAB_DATA_DIR` | `data` | Metadata, source files and results |
| `STEMLAB_MAX_UPLOAD_MB` | `200` | Streaming upload limit |
| `STEMLAB_MAX_DURATION_SECONDS` | `900` | Decoded duration limit |
| `STEMLAB_JOB_TIMEOUT_SECONDS` | `7200` | Hard inference timeout |
| `STEMLAB_CPU_THREADS` | `4` | PyTorch CPU thread count |
| `STEMLAB_QUEUE_MODE` | `celery` | Launcher automatically uses `local` |
| `STEMLAB_BROKER_URL` | `redis://localhost:6379/0` | Celery queue |
| `STEMLAB_RESULT_BACKEND` | `redis://localhost:6379/1` | Celery task results |
| `TORCH_HOME` | `data/models` | Model cache; optional environment override |

WAV/MP3 content is validated by decoding, including extension/content agreement, duration, channel count, sample rate (8–192 kHz), and finite samples. Filenames never become disk paths. Files are streamed to disk with size limits. This is a single-machine app, not a multi-user/public service: authentication and quotas would be needed for public hosting. Keep SQLite and the file lock directory on a local filesystem. Run one worker for predictable GPU memory use.

## API

Interactive documentation: **http://localhost:8000/docs**.

| Method | Route | Purpose |
| --- | --- | --- |
| POST | `/api/jobs?filename=track.wav` | Raw WAV (`audio/wav`) or MP3 (`audio/mpeg`) body, returns job |
| GET | `/api/jobs` | Latest 100 jobs |
| GET | `/api/jobs/{id}` | Status, stage and error |
| POST | `/api/jobs/{id}/cancel` | Cancel or request running job cancellation |
| POST | `/api/jobs/{id}/retry` | Retry a failed/cancelled job |
| DELETE | `/api/jobs/{id}` | Remove terminal job and files |
| GET | `/api/jobs/{id}/audio/{stem}` | Original WAV/MP3 or a generated WAV listed in the job's `outputs`; supports range playback |
| GET | `/api/jobs/{id}/download` | ZIP containing only the requested output files |
| GET | `/api/config` | Upload limits and engine settings |
| GET | `/health/live`, `/health/ready` | HTTP liveness and queue storage readiness |

Add `?download=true` to an audio URL for an attachment. Readiness checks queue storage; Compose separately checks worker responsiveness. Local mode polls SQLite every second. Jobs follow `queued → running → completed/failed`, with `cancelling → cancelled` for active cancellation. Failed dispatch is visible and retryable. Running inference executes in a child process so cancellation and timeouts can stop GPU work. Locks prevent overlapping attempts; stale job recovery will not release an attempt while its process still holds the lock.

The upload accepts `mode=all` (default), `mode=vocals`, `mode=instrumental`, or `mode=custom&keep=vocals,bass`. Custom mode requires at least one unique source from `vocals,drums,bass,other`. Other modes reject `keep`. Each job response includes `mode`, `keep`, and `outputs` (file ID, label, and included sources). Only the original and that job's requested outputs can be downloaded.

## Development and validation

```sh
uv sync --frozen                    # lightweight API/tests only
uv run ruff check .
uv run ruff format --check .
uv run pytest
node --check src/stemlab/web/app.js
docker compose -f compose.yaml -f compose.gpu.yaml config --quiet

# Opt-in real-model test (downloads weights if absent):
uv run --frozen --extra cuda python scripts/verify_inference.py
```

Tests cover validation, range downloads, queue failures, retry identities, cancellation, deletion and interrupted jobs. CI runs Python checks and a Docker queue smoke test; real GPU inference is an explicit local check. Model output smoke tests validate format and shape, not perceptual separation quality.

Browser checks run against a live app and perform real inference; they create and delete their own test track:

```sh
# In one terminal, run a separate local test instance:
STEMLAB_PORT=8765 uv run --frozen --extra cuda python -m stemlab.local
# In another:
npm ci
npx playwright install chromium
npm run test:browser
```

The checks cover all output modes, WAV and MP3 uploads/playback, ZIP contents, reload persistence, deletion, invalid audio, keyboard selection, and a 390px mobile viewport. They use `.venv/bin/python` to create synthetic audio fixtures. Screenshots are saved under `test-results/`. Set `STEMLAB_TEST_URL` to target another local instance. Node is needed only for these browser checks, not to run the application.

Source layout: `routes.py` handles upload/jobs/downloads; `jobs.py` owns SQLite state; `worker.py` manages inference processes; `inference.py` runs Demucs; `local.py` starts the direct local services; `web/` contains the responsive vanilla HTML/CSS/JS frontend.

## Open source

App code is MIT licensed. Runtime uses [FastAPI](https://github.com/fastapi/fastapi), [Celery](https://github.com/celery/celery), [Valkey](https://valkey.io/topics/introduction/), [PyTorch](https://pytorch.org/blog/pytorch-2-7/) and [Demucs](https://github.com/facebookresearch/demucs). The original Demucs repository is archived; this app pins its released engine and a compatible PyTorch stack. CUDA runtime libraries have NVIDIA's own license, and require no paid API or service.
