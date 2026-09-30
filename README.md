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

1. Choose or drop a mono/stereo WAV or MP3 (up to 200 MB and 15 minutes by default). When the file has tags, the title, artist, album, genre, year, and cover show on this step. They are read in the browser.
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

The optional **Ranges** controls apply the separation to one or more stretches of a track. For **Vocals only**, **No vocals** and **Custom mix** you get the whole song back: the effect covers just those ranges and everything else is the original audio, joined with a 10 ms crossfade at the cuts. One range with **All stems** returns the four stems covering just that section. Several ranges with **All stems** return four tracks the length of the song, with audio only inside the ranges and silence elsewhere, so they still line up. Only the ranges are separated, so a short stretch is much faster than the whole track, and each job does only the work its output needs: Vocals only skips the drums/bass/other stage when Roformer makes the vocals, the fine-tuned Demucs runs just the models for the stems you keep (one of four for vocals, three of four for No vocals), and the Roformer is skipped when the instruments come from the original track and the vocals are not wanted. Each extra range is separated on its own, so two ranges take about twice as long as one. The track's waveform is drawn with its cues marked: click a cue (or anywhere on the waveform) to set the start, click another for the end, and a third click starts over. **Add range** keeps that stretch and lets you mark another. The buttons below the waveform pick a whole stretch between two cues into the From and To fields. **Preview section** plays the times in those fields, and **Whole track** clears every range. You can also type times in seconds. The waveform is decoded in your browser and needs a file it can decode; without it the cue buttons and time fields still work. Cues come from these sources:

- **WAV cue markers** stored in the file (cue points and their labels) are read in the browser as soon as you choose the file.
- **Rekordbox:** it keeps hot cues in its own database, not in the audio. In Rekordbox use *File → Export Collection in xml format*, then add that XML under **Rekordbox XML**. The track is matched by file name (the uploaded file must have the same name as in your collection) and only hot cues (not memory cues) are listed.

- **Mixxx:** hot cues are read from your local Mixxx library (`~/.mixxx/mixxxdb.sqlite`, or `STEMLAB_MIXXX_DB`), opened read-only, as soon as you choose a file. Mixxx does not write cues into the audio files by default. The track is matched by file name and must appear exactly once in the library; only hot cues (not main cue, intro or outro markers) are listed.

MP3 files without a Mixxx entry and other DJ software (Serato, Traktor, Engine DJ) are not read; type the times instead. The models get about 5 seconds of extra audio on each side of a range for context, which is trimmed from the result, so the effect starts and ends exactly on your cues. Whole-song results are 44.1 kHz stereo like every other output (a 48 kHz upload is resampled). The chosen ranges are saved with the job and reused on retry.

The **Separation quality** controls choose each stage for every track: the **Vocals** model, the **Drums, bass & other** Demucs model (`htdemucs`, `htdemucs_ft`, `hdemucs_mmi`, or the last two averaged; in the library's published scores `hdemucs_mmi` is slightly ahead on bass and `htdemucs_ft` on drums and vocals), what those instruments are separated **from**, and the Demucs shifts and overlap. They default to the `STEMLAB_*` values below and are saved with the job, so retries reuse them. Jobs created before these options existed show what they actually ran with (`htdemucs`, Demucs vocals, 0 shifts, 25% overlap). The Roformer models come from the Ultimate Vocal Remover (UVR) catalog through the `audio-separator` library, a curated few of the best-scoring vocal models that share one loader; other UVR model types (MDX-Net, VR), de-reverb, denoise and karaoke tools are not included. If the bass has an artifact such as a bubbly sound, try **Original track** for the instruments, or a different vocal model, and compare.

Each job saves its selection, including across retries and page reloads. Existing jobs retain all four stems through an automatic SQLite migration. Mixes sum the selected model estimates without individually normalizing sources. Choosing fewer outputs changes the exported audio, not the model's underlying four-source analysis or separation quality.

Original uploads remain available in their input format (WAV or MP3). Generated results are always WAV, avoiding another lossy encoding pass. Converting MP3 to WAV does not restore information already lost in MP3 compression. MP3 decoding uses the bundled libsndfile in SoundFile's Linux wheels; no external conversion service or FFmpeg is needed on the supported setup.

The default vocal setting runs two vocal models (MelBand Roformer and BS-Roformer, averaged), subtracts the vocals from the track, and runs `htdemucs_ft` on the remainder for drums, bass and other, so vocals cannot bleed into the instrument stems and the four stems add back up to the original. For **No vocals** (or a Custom mix of exactly drums, bass and other), **Mix minus vocals** skips Demucs altogether: the result is the original track minus the vocal model's vocals, so everything that is not the voice stays exactly as recorded (including the bass character that Demucs would otherwise regenerate), at the cost of any leftover vocal traces and of getting the instruments only together, never as separate stems. It is faster too, since only the Roformer runs. Choosing **Original track** as the instrument source runs Demucs on the untouched mix instead, and choosing **Demucs** for vocals skips Roformer entirely. Published benchmark scores for the Roformer models are higher than Demucs on vocals, but this has not been measured on your material, so compare on tracks you know. Roformer needs CUDA, uses roughly 2 GB of GPU memory for the vocal stage and takes several minutes for a three-minute track. The Roformer checkpoints download on first use: MelBand 0.9 GB, BS-Roformer 0.6 GB each and Big Beta 4 1.5 GB (about 3.8 GB for all four). The default ensemble needs about 1.6 GB of them (into `data/models/roformer/`) plus the approximately 320 MB `htdemucs_ft` model (`STEMLAB_MODEL=htdemucs` is the ~80 MB single model). Later runs reuse the local cache; audio never leaves the machine. Progress displays real stages, not an estimated percentage. Stems are 44.1 kHz stereo, 32-bit float WAV to avoid clipping or separate normalization. Original sample rate and duration appear in the UI. Model separation is approximate and can contain artifacts/bleed; “other” combines instruments outside the three named categories.

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
| `STEMLAB_MIXXX_DB` | `~/.mixxx/mixxxdb.sqlite` | Mixxx library to read hot cues from (absolute path; ignored if missing) |
| `STEMLAB_MAX_UPLOAD_MB` | `200` | Streaming upload limit |
| `STEMLAB_MAX_DURATION_SECONDS` | `900` | Decoded duration limit |
| `STEMLAB_JOB_TIMEOUT_SECONDS` | `7200` | Hard inference timeout |
| `STEMLAB_CPU_THREADS` | `4` | PyTorch CPU thread count |
| `STEMLAB_MODEL` | `htdemucs_ft` | Demucs model for drums, bass and other: `htdemucs_ft` (four fine-tuned models), `htdemucs` (fastest), `hdemucs_mmi` (Hybrid Demucs v3 MMI, ~160 MB) or `ft_mmi` (fine-tuned and MMI averaged, about twice the time of `htdemucs_ft`) |
| `STEMLAB_VOCALS` | `ensemble` | Vocal model: `melband`, `bs` (BS-Roformer 1297), `beta4` (MelBand Big Beta 4, 1.5 GB), `bs1296` (BS-Roformer 1296), `ensemble` (MelBand + BS 1297 averaged), `ensemble_all` (all four averaged, slowest) or `demucs` (no Roformer; the only option on CPU) |
| `STEMLAB_INSTRUMENTS_FROM` | `residual` | With Roformer vocals, what Demucs separates: `residual` (track minus vocals) or `mix` (the original track). The per-track choice also offers `inverse` (see below), which cannot be a global default |
| `STEMLAB_SHIFTS` | `2` | Demucs random-shift averaging passes; each adds roughly one more full run. `0` disables; the UI allows 0–5 |
| `STEMLAB_OVERLAP` | `0.5` | Demucs segment overlap (0.1–0.9); higher smooths seams, costs time |
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

The upload also accepts `start` and `end` (seconds) to separate only that section, or `ranges=0-5,10-15` for several stretches. A single pair sent as `ranges` is stored the same way as `start` and `end`. Each range must be at least one second, inside the track, and must not overlap another; at most 12 ranges. Do not send `start`/`end` together with `ranges`. `end` must be within the track. The upload accepts `mode=all` (default), `mode=vocals`, `mode=instrumental`, or `mode=custom&keep=vocals,bass`. Custom mode requires at least one unique source from `vocals,drums,bass,other`. Other modes reject `keep`. Each job response includes `mode`, `keep`, `ranges` (the stretches, or null for the whole track), and `outputs` (file ID, label, and included sources). Only the original and that job's requested outputs can be downloaded.

## Development and validation

```sh
uv sync --frozen                    # lightweight API/tests only
uv run ruff check .
uv run ruff format --check .
uv run pytest
npm run build --prefix frontend
docker compose -f compose.yaml -f compose.gpu.yaml config --quiet

# Opt-in real-model test (downloads weights if absent):
uv run --frozen --extra cuda python scripts/verify_inference.py
```

Tests cover validation, range downloads, queue failures, retry identities, cancellation, deletion and interrupted jobs. CI runs Python checks and a Docker queue smoke test; real GPU inference is an explicit local check. Model output smoke tests validate format and shape, not perceptual separation quality.

Browser checks run against a live app and perform real inference; they create and delete their own test track:

```sh
# In one terminal, run a separate local test instance:
STEMLAB_PORT=8765 uv run --frozen --extra cuda python -m stemlab.local
# In another, build the interface, then run the checks:
npm ci
npm run build --prefix frontend
npx playwright install chromium
npm run test:browser
```

The checks cover all output modes, WAV and MP3 uploads/playback, ZIP contents, reload persistence, deletion, invalid audio, keyboard selection, and a 390px mobile viewport. They use `.venv/bin/python` to create synthetic audio fixtures. Screenshots are saved under `test-results/`. Set `STEMLAB_TEST_URL` to target another local instance. Node builds the interface; the running app is still the Python server. While changing the interface, `npm run dev --prefix frontend` serves it with live reload and proxies API calls to `http://127.0.0.1:8000` (`STEMLAB_DEV_API` overrides that).

Source layout: `routes.py` handles upload/jobs/downloads; `jobs.py` owns SQLite state; `worker.py` manages inference processes; `inference.py` runs Demucs; `local.py` starts the direct local services; `frontend/` is the Svelte interface, built into `src/stemlab/web/ui/`.

## Open source

App code is MIT licensed. Runtime uses [FastAPI](https://github.com/fastapi/fastapi), [Celery](https://github.com/celery/celery), [Valkey](https://valkey.io/topics/introduction/), [PyTorch](https://pytorch.org/blog/pytorch-2-7/) and [Demucs](https://github.com/facebookresearch/demucs). The original Demucs repository is archived; this app pins its released engine and a compatible PyTorch stack. CUDA runtime libraries have NVIDIA's own license, and require no paid API or service.
