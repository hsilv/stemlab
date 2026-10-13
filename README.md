# StemLab

A local WAV/MP3/FLAC separation app. Upload a track, choose **vocals only**, **no vocals**, **all four stems**, or a **custom mix** of vocals, drums, bass and other instruments. Preview the result and download WAVs or a ZIP. Includes persistent history, cancellation, retries and deletion. No paid services or API keys.

## Install

StemLab runs entirely on your machine. Pick one way to install it:

| | For | You get |
| --- | --- | --- |
| [Desktop app](#desktop-app-windows-and-linux) | Most people | An installer and its own window. The first start sets everything up |
| [From source on Windows](#from-source-on-windows) | Windows, developers | The app in your browser, started from PowerShell |
| [From source on Linux](#run-from-source-linux-and-windows) | Linux, developers | The same, started from a terminal (described below) |

### What you need first

- **A computer with an NVIDIA GPU is recommended.** Run `nvidia-smi`: it should list your card and a *CUDA Version* of 12.8 or higher. Update the driver if not (RTX 50-series cards need a recent driver). PyTorch carries its own CUDA runtime, so you do not install the CUDA toolkit.
- **No NVIDIA GPU?** The CPU build works, but one separation takes many minutes.
- **Disk space:** about 7 GB for the Python environment with CUDA (much less on CPU) and several GB more for the separation models, which download the first time you use each one. Keep 10 GB free.
- **Internet** for the first start only (environment and models). Your audio never leaves the machine.
- **ffmpeg** (source installs only): needed for MP3 downloads and the Tags booth. Windows: `winget install Gyan.FFmpeg`. Debian/Ubuntu: `sudo apt install ffmpeg`. Both desktop installers already contain it.

### Desktop app (Windows and Linux)

The desktop app is the same interface in its own window. It starts and stops the local server for you and keeps your jobs under your user profile (`%APPDATA%\StemLab` on Windows, `~/.config/StemLab` on Linux).

It comes in two sizes:

| | Full | Small |
| --- | --- | --- |
| Python, PyTorch (CUDA) and all packages | Inside the installer | Downloaded on the first start (several GB) |
| ffmpeg and ffprobe | Inside | Inside |
| Separation models | Downloaded the first time each is used | The same |
| Internet needed | Only for models | For setup and for models |
| Windows file | A zip: extract it and run `StemLab.exe` (an installer cannot hold more than 2 GB) | `StemLab Setup *.exe` |
| Linux file | `StemLab-*-full.deb` | `stemlab-desktop_*_amd64.deb` or `.AppImage` |

Not included in either: the NVIDIA driver (it comes from your system) and the Generate booth's ACE-Step checkout and weights.

1. Install it:
   - **Windows:** run the small installer (`StemLab Setup *.exe`), or extract the full zip anywhere and run `StemLab.exe`.
   - **Debian and Ubuntu (recommended on Linux):** `sudo apt install ./StemLab-0.1.0-full.deb` (or the small `stemlab-desktop_0.1.0_amd64.deb`). It installs under `/opt/StemLab` and adds a **StemLab** entry to your applications menu.
   - **Any other Linux:** make the AppImage executable and run it: `chmod +x StemLab-0.1.0.AppImage && ./StemLab-0.1.0.AppImage`. AppImages need FUSE 2: on Ubuntu 22.04 and later install `libfuse2` (`libfuse2t64` on 24.04 and later), or run it with `--appimage-extract-and-run`.
2. Start **StemLab**. The full build opens straight away. The small build first opens a setup window while it installs the audio tools: it picks the NVIDIA build when it finds a GPU, otherwise the CPU build, which takes a few minutes and a few GB of download, once.
3. Choose a track. The first separation also downloads its model; the progress shows in the job.

Closing the window stops the server. If jobs are waiting or running, it asks first: waiting jobs continue next time, a running one can be retried.

**Building the installers** (not published yet; needs Node 22+ on the platform you build for, so build the Windows files on Windows):

```sh
npm ci --prefix frontend
npm run build --prefix frontend     # puts the interface into the Python package
npm ci --prefix desktop
npm run dist --prefix desktop       # small: fetches uv and ffmpeg, packages into desktop/dist/
npm run dist:full --prefix desktop  # full: also bundles Python and PyTorch (about 20 GB free needed)
```

`dist:full` runs `desktop/scripts/bundle-runtime.mjs`: a standalone Python 3.12 plus every package from `uv.lock`, CUDA build by default (`node desktop/scripts/bundle-runtime.mjs inference` makes a CPU-only runtime). ffmpeg and ffprobe come from BtbN's LGPL builds, which include the MP3 encoder; their license text is saved beside them, and you should read ffmpeg's [legal notes](https://ffmpeg.org/legal.html) before redistributing. Windows files are unsigned unless you configure code signing, so SmartScreen will warn. The desktop app keeps its own data under your user profile, so a machine that also has a source install holds two copies of the environment (several GB each).

To try the window from a checkout without packaging: `npm ci --prefix desktop && npm start --prefix desktop` (it uses the repository's `.venv`; create it as below first).

### From source on Windows

In PowerShell (Windows 10 or 11, 64-bit):

```powershell
winget install --id astral-sh.uv -e
git clone <this repository> stemlab
cd stemlab
uv sync --frozen --extra cuda            # NVIDIA GPU; use --extra inference for CPU only
npm ci --prefix frontend                 # Node 22+ from https://nodejs.org
npm run build --prefix frontend
.\run.ps1
```

Open **http://localhost:8000**. `uv` downloads Python 3.12 for you, so you need no separate Python. If PowerShell blocks `run.ps1`, run `powershell -ExecutionPolicy Bypass -File .\run.ps1`. To choose CUDA or CPU automatically, run `uv run --no-project python scripts/bootstrap.py` instead of `uv sync`.

Windows support is new. It follows the same code as Linux (locks, paths and child processes are handled per platform), and a CI job runs the test suite on Windows, but the full GPU workflow has had less testing than on Linux. Please report problems with your Windows version, GPU and the log in `data\<job id>\worker.log`.

### Troubleshooting

- **"Interface build missing"**: build the interface (`npm ci --prefix frontend`, `npm run build --prefix frontend`). The installer includes it.
- **Separation is slow or fails with a CUDA error**: check `nvidia-smi`, then start with `STEMLAB_DEVICE=cuda` to see the real error instead of a CPU fallback.
- **Out of memory**: close other GPU programs, or lower *Shifts* in the quality settings.
- **MP3 download or Tags says ffmpeg is missing**: install ffmpeg (above) and restart.
- **Port 8000 is taken** (source installs): set `STEMLAB_PORT=8001`. The desktop app chooses a free port by itself.
- **Start over**: stop the app and delete its data folder (the `data` folder of a source install, or the user profile folder above). This removes your job history and downloaded models.

## Run from source (Linux and Windows)

Requires Python 3.11/3.12, [uv](https://docs.astral.sh/uv/getting-started/installation/) and an NVIDIA driver supporting CUDA 12.8 (Linux; on Windows see above). PyTorch bundles the CUDA runtime; a separate CUDA toolkit installation is not needed.

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

The two extras are mutually exclusive. Always include the chosen extra when invoking `uv run`, or uv will remove inference dependencies from the environment. After installing, start the app with:

```sh
./run.sh
```

That uses the existing `.venv` (`.venv/bin/python -m stemlab.local`) and leaves the installed extra in place. The script can be run from any directory.

## Use the app

1. (To edit a song you already uploaded, open it in the crate and press **Edit this song again**; it skips the upload and reuses the stored tempo, key and downbeat. The crate groups every edit of a song under one entry, newest first.) Choose or drop a mono/stereo WAV, MP3 or FLAC (up to 200 MB and 15 minutes by default). When the file has tags, the title, artist, album, genre, year, and cover show on this step. They are read in the browser. StemLab also reads the tempo, Camelot key, and a 4/4 beat grid. A neural beat tracker (Beat This!) decides which pulse is the beat and where each bar starts, so syncopated reggaeton rhythms are not read at 4:3 of their real tempo, and the key is read from the isolated bass and instruments, with the vocals and drums removed. The first reading downloads the beat tracker's 78 MB model; if it or the separator is unavailable, a signal-only reading is used. This step stays put until that reading finishes or fails. You then see the BPM to two decimals, the key (for example `8A · A minor`), and a waveform of the original: play it, click the wave or the thin overview to seek, and use **Set downbeat** to move the grid onto the nearest beat. A note appears when part of the track does not hold that grid, or when no steady tempo was found. If the reading fails, the page says why and you can continue without a grid. Nothing is written to Mixxx or into the file's tags.
2. Choose an output mode. In **Custom mix**, check the sounds to keep together; unchecked sounds are excluded. The output preview updates immediately.
3. Click **Separate track**. Upload progress and processing stages appear in the UI.
4. Select a track in history to preview the original and your selected outputs, or download the ZIP.

The waveform is coloured by what is in it: low sound (kicks, bass) toward orange, mids toward green and highs toward pale blue. For a finished **All stems** job, **Open the mixer** loads the four stems and plays them together with a mute and solo button per stem and a waveform per lane; nothing is rendered or stored. The crate lists each track with its tempo and Camelot key and a status dot, and a strip at the bottom of the page follows whichever preview played last (play or pause, position, seek) while each output keeps its own player and download link.
5. Cancel queued/running jobs, retry failures, or delete finished jobs to reclaim disk space.

| Mode | Generated files |
| --- | --- |
| Vocals only | `vocals.flac` |
| No vocals | `instrumental.flac` — drums, bass and other instruments together |
| All stems | `vocals.flac`, `drums.flac`, `bass.flac`, `other.flac` |
| Custom mix | `mix.flac` — only your checked sources, combined |

The optional **Ranges** controls apply the separation to one or more stretches of a track. For **Vocals only**, **No vocals** and **Custom mix** you get the whole song back: the effect covers just those ranges and everything else is the original audio, joined with a 10 ms crossfade at the cuts. One range with **All stems** returns the four stems covering just that section. Several ranges with **All stems** return four tracks the length of the song, with audio only inside the ranges and silence elsewhere, so they still line up. Only the ranges are separated, so a short stretch is much faster than the whole track, and each job does only the work its output needs: Vocals only skips the drums/bass/other stage when Roformer makes the vocals, the fine-tuned Demucs runs just the models for the stems you keep (one of four for vocals, three of four for No vocals), and the Roformer is skipped when the instruments come from the original track and the vocals are not wanted. Each extra range is separated on its own, so two ranges take about twice as long as one. The track's waveform is drawn with its cues marked, and with the beat grid when the reading produced one: click a cue (or anywhere on the waveform) to set the start, click another for the end, and a third click starts over. **Add range** keeps that stretch and lets you mark another. The buttons below the waveform pick a whole stretch between two cues into the From and To fields. **Preview section** plays the times in those fields, separate from the waveform on the Load step, and **Whole track** clears every range. The **Snap to the beat grid** switch (on by default when a grid was found) makes clicks on the waveform, dragged edges and the arrow keys snap to the nearest beat (arrow keys move one beat, or one bar with Shift); switch it off to place an edge exactly (arrow keys then move 0.01 s, or 0.1 s with Shift). The needle follows **Preview section** as it plays. Cues and typed times stay exactly as entered. Scroll over the waveform to zoom in at the pointer (up to 400x), and drag the zoomed waveform sideways to move along it, so you can fine-adjust an edge. You can also type times in seconds. The waveform is decoded in your browser and needs a file it can decode; without it the cue buttons and time fields still work. Cues come from these sources:

- **WAV cue markers** stored in the file (cue points and their labels) are read in the browser as soon as you choose the file.
- **Rekordbox:** it keeps hot cues in its own database, not in the audio. In Rekordbox use *File → Export Collection in xml format*, then add that XML under **Rekordbox XML**. The track is matched by file name (the uploaded file must have the same name as in your collection) and only hot cues (not memory cues) are listed.

- **Mixxx:** hot cues are read from your local Mixxx library (`~/.mixxx/mixxxdb.sqlite`, or `STEMLAB_MIXXX_DB`), opened read-only, as soon as you choose a file. Mixxx does not write cues into the audio files by default. The track is matched by file name and must appear exactly once in the library; only hot cues (not main cue, intro or outro markers) are listed.

MP3 files without a Mixxx entry and other DJ software (Serato, Traktor, Engine DJ) are not read; type the times instead. The models get about 5 seconds of extra audio on each side of a range for context, which is trimmed from the result, so the effect starts and ends exactly on your cues. Whole-song results are 44.1 kHz stereo like every other output (a 48 kHz upload is resampled). The chosen ranges are saved with the job and reused on retry.

The **Separation quality** controls choose each stage for every track: the **Vocals** model, the **Drums, bass & other** Demucs model (`htdemucs`, `htdemucs_ft`, `hdemucs_mmi`, or the last two averaged; in the library's published scores `hdemucs_mmi` is slightly ahead on bass and `htdemucs_ft` on drums and vocals), what those instruments are separated **from**, and the Demucs shifts and overlap. They default to the `STEMLAB_*` values below and are saved with the job, so retries reuse them. Jobs created before these options existed show what they actually ran with (`htdemucs`, Demucs vocals, 0 shifts, 25% overlap). The Roformer models come from the Ultimate Vocal Remover (UVR) catalog through the `audio-separator` library, a curated few of the best-scoring vocal models that share one loader; other UVR model types (MDX-Net, VR), de-reverb, denoise and karaoke tools are not included. If the bass has an artifact such as a bubbly sound, try **Original track** for the instruments, or a different vocal model, and compare.

Each job saves its selection, including across retries and page reloads. Existing jobs retain all four stems through an automatic SQLite migration. Mixes sum the selected model estimates without individually normalizing sources. Choosing fewer outputs changes the exported audio, not the model's underlying four-source analysis or separation quality.

Original uploads remain available in their input format (WAV or MP3). Generated results are 24-bit FLAC: lossless (no further lossy encoding pass) and roughly 45-60% smaller than the 32-bit float WAV earlier versions wrote. Jobs finished before that keep their WAV stems and still play and download. Any finished track can be downloaded as FLAC, 24-bit WAV or 320 kbps MP3 (the **Download as** menu on the track; the files and the ZIP are converted when you download, nothing extra is stored). MP3 needs `ffmpeg` with libmp3lame on the server (`sudo apt install ffmpeg`; the Docker image includes it); without it that choice is hidden. If an output would exceed full scale, all outputs of the job share one gain reduction, so relative levels are kept and nothing clips. Converting MP3 to WAV does not restore information already lost in MP3 compression. MP3 decoding uses the bundled libsndfile in SoundFile's Linux wheels; no external conversion service or FFmpeg is needed on the supported setup.

The default vocal setting runs two vocal models (MelBand Roformer and BS-Roformer, averaged), subtracts the vocals from the track, and runs `htdemucs_ft` on the remainder for drums, bass and other, so vocals cannot bleed into the instrument stems and the four stems add back up to the original. For **No vocals** (or a Custom mix of exactly drums, bass and other), **Mix minus vocals** skips Demucs altogether: the result is the original track minus the vocal model's vocals, so everything that is not the voice stays exactly as recorded (including the bass character that Demucs would otherwise regenerate), at the cost of any leftover vocal traces and of getting the instruments only together, never as separate stems. It is faster too, since only the Roformer runs. Choosing **Original track** as the instrument source runs Demucs on the untouched mix instead, and choosing **Demucs** for vocals skips Roformer entirely. Published benchmark scores for the Roformer models are higher than Demucs on vocals, but this has not been measured on your material, so compare on tracks you know. Roformer needs CUDA, uses roughly 2 GB of GPU memory for the vocal stage and takes several minutes for a three-minute track. The Roformer checkpoints download on first use: MelBand 0.9 GB, BS-Roformer 0.6 GB each and Big Beta 4 1.5 GB (about 3.8 GB for all four). The default ensemble needs about 1.6 GB of them (into `data/models/roformer/`) plus the approximately 320 MB `htdemucs_ft` model (`STEMLAB_MODEL=htdemucs` is the ~80 MB single model). Later runs reuse the local cache; audio never leaves the machine. Progress displays real stages, not an estimated percentage. Stems are 44.1 kHz stereo 24-bit FLAC (older jobs: 32-bit float WAV) with no separate normalization. Original sample rate and duration appear in the UI. Model separation is approximate and can contain artifacts/bleed; “other” combines instruments outside the three named categories.

**Instrumental models.** For **No vocals** the Stems step offers, under *Instruments from*, three models that output the whole instrumental directly instead of subtracting the vocals: BS-Roformer Resurrection, MelBand Inst V2 and MelBand Bleedless v3 (each downloads once, 0.5 to 1.6 GB, and needs the GPU). In a test that mixed real voice-free music with a voice, none recovered the instrumental better than *Mix minus vocals* with the default two-model vocals (about 16.0 dB against 15.4 to 15.6 dB, and they alter audio that has no voice more), so *Mix minus vocals* stays the recommended choice and these are there to compare by ear.

Files and SQLite metadata live in `data/`; model weights are cached in `data/models/`. Files are retained until you delete the job. A ZIP duplicates stem storage for fast downloads. Allow several GB of free disk space for long tracks. History displays the latest 100 jobs; older jobs remain accessible by ID through the API.

## Extended version (intro and outro for DJs)

Pick a song in the crate and open the **Extender** tab in the header (it needs a steady tempo; without one the page says so). An intro goes before the song and an outro after it, both cut on the song's beat grid: the song's first bar starts exactly at the end of the intro, and the song itself is copied untouched.

- **Intro**: 4, 8, 16 or 32 bars (16 by default), or none. The loop comes from the first steady drums, the first bars, or a fragment you select on the waveform (for example the chorus), and plays as layers entering one by one (drums, then bass, then the other instruments), drums and bass, the instrumental, or the mix as it is.
- **Outro**: the same lengths. The song is cut where its last steady groove ends and that groove loops while the layers leave: voice first, then the other instruments, then the bass, and the drums fade out in the last bar. The loop can also be a fragment you choose.
- **Hear selection** plays the stretch you have selected on the waveform (the needle follows it), and **Hear it** next to a chosen fragment plays that fragment again, so you can judge a loop before using it.
- **Preview the joins** renders only the intro and the start of the song, then the end of the song and the outro, so you can listen before making the edit.
- The result is another edit of the same song (FLAC, with BPM and key in its tags; the MP3 download carries them too). Only the stretches that feed the loops are separated, a few seconds of GPU; if the song already has a finished whole-song **All stems** edit, they are cut from it instead. The voice is never looped in the outro or in a layered, drums-and-bass or instrumental intro, but a "mix" intro repeats it.

### Manual mode

The Extender tab has an **Automatic / Manual** switch. Manual builds the edit from a list of operations, each placing a processed fragment of the same song:

- **Paste at the start**, **paste at the end**, **insert in the middle** (before a bar, so the rest of the song moves later by whole bars) or **replace part of the song** (a range of bars, which the fragment is repeated or trimmed to fill exactly). Positions are bar numbers of the original song, so an earlier insertion never shifts a later one; operations that touch the same bars are refused.
- Select the fragment on the waveform (it snaps to the beat grid), press **Use the selection**, and for a paste or an insert choose its length in bars (a shorter fragment repeats, a longer one is trimmed).
- Each sound (voice, drums, bass, other instruments) is switched on or off and given a volume. **Separation models** chooses, per operation, the Demucs model, where the voice comes from (Demucs or the Roformer choices, which need the GPU), the shifts and the overlap; the defaults are the ones on the Stems step. When everything but the voice is on at one volume, the instruments are always taken as the song minus the voice, so nothing the separation misses is lost. With every sound at one volume the fragment is the song as it is and nothing is separated.
- **Hear it in the song** renders one operation with 12 seconds of the song either side. A result is another edit of the song, written like the automatic one (BPM and key in its tags).

## Generate a backing track

The **Generate** booth writes a new instrumental from a description such as "warm lo-fi hip hop, mellow drums, soft electric piano, relaxed", with a length from 10 to 240 seconds. Optionally add a reference (a song or one of its stems from the crate, or a WAV/MP3 file; only its middle 30 seconds are used) to steer the style, sound and tempo. The reference is guidance, not a copy. Each press makes a different take; the result appears in the crate as a **Backing track** with a single `backing.flac` (48 kHz stereo, 24-bit) that downloads like any other output. Everything runs on this machine with [ACE-Step 1.5](https://github.com/ACE-Step/ACE-Step-1.5) (code under the MIT license; read the Hugging Face model card for the weights' terms). The output is generated by a model, so listen before you use it. It makes no vocals, does not follow a vocal you give it (not working in testing), and is not trained on or labelling your library.

ACE-Step needs a newer PyTorch than the one StemLab pins, so it lives in its own environment next to the app. One-time setup (about 5 GB of packages and 14 GB of weights; needs [uv](https://docs.astral.sh/uv/)):

```sh
mkdir -p data/ace-step && cd data/ace-step
git clone --depth 1 https://github.com/ACE-Step/ACE-Step-1.5.git ace
cd ace && uv sync
./.venv/bin/acestep-download --dir ../checkpoints
./.venv/bin/acestep-download --dir ../checkpoints --model acestep-v15-sft --skip-main
```

This does not touch StemLab's own environment. Until it exists the booth says generation is not set up. Set `STEMLAB_ACE_STEP_DIR` to keep it elsewhere (it must hold `ace/` and `checkpoints/`).

It uses the slow, higher-quality `sft` model (50 steps) with ACE-Step's 1.7B language model, which plans the tempo, key and structure from your description. In listening tests this sounded far better than the fast 8-step `turbo` model, which gave thin, low-energy music for "house music". On an RTX 5060 Ti (16 GB) the job peaks at about 12 GB of VRAM, with or without a reference and at any length. Each track starts by loading the models (about 30 s), then takes roughly 15 s for 30 s of music, 80 s for 2 minutes and 135 s for 4 minutes. It runs inside the same one-job-at-a-time GPU lock as separation. A card with less than about 12 GB free will run out of memory.

## Tags: keep the song's identity on every version

Instrumentals, stems, mixes and extended edits carry the tags of the song they came from, so a DJ library files them with it. When a job finishes, each output gets the original upload's title, artist, album, genre, year, track and other fields, and its cover. The title says what the file is: `Song (Instrumental)`, `Song (Vocals)`, `Song (Extended)`, and so on. Tempo and key are the job's own reading (BPM and INITIALKEY in a FLAC, TBPM and TKEY in an MP3). Downloads converted to MP3 or WAV carry the same tags; a WAV keeps the text fields but has nowhere for a cover, tempo or key. Needs `ffmpeg` and `ffprobe` on the server; without them nothing is tagged and nothing fails. Jobs finished before this feature keep their untagged stems.

The **Tags** tab does the same on demand. Choose where the tags come from and where they go, each either a song from the crate (its original upload or any finished output) or a file you choose (MP3, FLAC or WAV, recognized by what is inside, not by its name). The page shows what each carries, lets you change the version added to the title and leave the cover out, and downloads a copy of the target. Neither file is changed, and the target keeps its own tempo and key.

## Playlist

The header switches between **Separate** and **Playlist**. Separate keeps the crate and the steps above. Playlist hides the crate and uses the main column.

**Choose a folder.** A dialog on this machine asks which directory to use; cancel leaves the previous choice and does not scan. The scan includes only the WAV and MP3 files sitting directly in that folder. Subfolders are not included. Names that start with a dot are skipped. A symlink is included only when the file it resolves to is still a direct child of the chosen folder. Each file is measured for tempo and Camelot key, the same reading the Load step uses, and the result is remembered by path, size, and modification time, so an unchanged file is not measured again. The order, a pin, and **Left out** last until you reload the page.

A track with no BPM or no Camelot stays under **No reading**, with the reason. Every other track appears once. The opener is the slowest BPM, then the file name. **Pin** makes that track the opener and rebuilds the list. **Remove** moves a track to **Left out** and rebuilds; **Restore** puts it back. The next track is a Camelot neighbor (the same code, one step on the wheel, or the same number with A and B swapped) whose tempo is within 8% and whose mood is close (see below), staying at the written BPM when any neighbor fits there and using half or double time only when none does. When no neighbor is close enough, the list still continues and marks that join **Break**. Play starts at the beginning of the file you pick. There is no crossfade, and nothing is written back to the folder or to Mixxx.

**Mood.** Each track also gets a valence (dark to bright) and an energy (calm to driving), estimated from the audio: how strongly the key leans major or minor, the brightness of the sound, how much of the harmony stays on the scale, tempo, loudness and rhythmic activity. The rows show them as, for example, "Dark · Steady". A next track must not be much happier or sadder than the one before it (valence within 0.2), so a bright song is never followed straight away by a dark one; when nothing qualifies, the break takes a track that keeps the mood if it can. This is a heuristic from the sound, not from the lyrics, which are not read. Tracks measured before this feature have no mood and fit anywhere until they are measured again.

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
| `STEMLAB_VOCALS` | `ensemble` | Vocal model: `melband`, `bs` (BS-Roformer 1297), `beta4` (MelBand Big Beta 4, 1.5 GB), `bs1296` (BS-Roformer 1296), `resurrection` (BS-Roformer Resurrection by Unwa, an instrumental-first model whose vocal stem is what it removes), `ensemble` (MelBand + BS 1297 averaged), `ensemble_all` (all four averaged, slowest) or `demucs` (no Roformer; the only option on CPU) |
| `STEMLAB_INSTRUMENTS_FROM` | `residual` | With Roformer vocals, what Demucs separates: `residual` (track minus vocals) or `mix` (the original track). The per-track choice also offers `inverse` (see below), which cannot be a global default |
| `STEMLAB_SHIFTS` | `2` | Demucs random-shift averaging passes; each adds roughly one more full run. `0` disables; the UI allows 0–5 |
| `STEMLAB_OVERLAP` | `0.5` | Demucs segment overlap (0.1–0.9); higher smooths seams, costs time |
| `STEMLAB_ACE_STEP_DIR` | `data/ace-step` | Folder with the ACE-Step checkout (`ace/`, with its own `.venv`) and its weights (`checkpoints/`), used by Generate |
| `STEMLAB_QUEUE_MODE` | `celery` | Launcher automatically uses `local` |
| `STEMLAB_BROKER_URL` | `redis://localhost:6379/0` | Celery queue |
| `STEMLAB_RESULT_BACKEND` | `redis://localhost:6379/1` | Celery task results |
| `TORCH_HOME` | `data/models` | Model cache; optional environment override |

WAV/MP3 content is validated by decoding, including extension/content agreement, duration, channel count, sample rate (8–192 kHz), and finite samples. Filenames never become disk paths. Files are streamed to disk with size limits. This is a single-machine app, not a multi-user/public service: authentication and quotas would be needed for public hosting. Keep SQLite and the file lock directory on a local filesystem. Run one worker for predictable GPU memory use.

## API

Interactive documentation: **http://localhost:8000/docs**.

| Method | Route | Purpose |
| --- | --- | --- |
| POST | `/api/analyses?filename=track.wav` | Raw WAV or MP3 body. Returns 202 with `id`, `status: running`, and `stage` |
| GET | `/api/analyses/{id}` | Poll until `completed` or `failed`. Completion adds `bpm`, `camelot`, `key_name`, `downbeat`, and `warning` |
| GET | `/api/jobs/{id}/audio/{stem}?format=flac\|wav\|mp3` and `/api/jobs/{id}/download?format=…` | Convert a finished stem or the ZIP on download; omit `format` for the stored file. `/api/config` lists `export_formats` |
| POST | `/api/tags/files?filename=x` | Raw MP3, FLAC or WAV body for the Tags tab; recognized by content. Returns `{ref, name}`; kept for an hour |
| GET | `/api/tags?ref=` and `/api/tags/cover?ref=` | Tags, tempo, cover and container of `job:<id>:<original or output>` or `file:<id>`; the cover as PNG |
| POST | `/api/tags/copy` | JSON `{source, target, version?, cover?}`. Returns a tagged copy of the target; `version` null uses the target output's own name, `""` adds none |
| POST | `/api/jobs?filename=track.wav` | Raw WAV (`audio/wav`) or MP3 (`audio/mpeg`) body, returns job |
| POST | `/api/jobs?from_job={id}&mode=extend&extend={json}` | Extended edit: `extend` is `{"intro": {"bars": 4\|8\|16\|32, "source": "stable_drums\|first_bars\|fragment", "treatment": "layered\|drums_bass\|instrumental\|mix", "fragment": [start, end]}, "outro": {"bars", "source": "last_bars\|fragment", "fragment"}}`, or `{"operations": [{"action": "start\|end\|insert\|replace", "fragment": [start, end], "bars", "at", "span": [first, last], "stems": {"vocals", "drums", "bass", "other": 0..1}, "model", "vocals", "shifts", "overlap"}]}` for a manual edit (bar numbers start at 0); 422 without a tempo or with bad choices |
| POST | `/api/generate?prompt=...&duration=30&seed=...` | Backing track (mode `generate`). `prompt` 1–500 characters, `duration` 10–240 s, `seed` optional (random and stored otherwise). Reference: send a raw WAV/MP3 body with `filename`, or `reference_job={id}&reference_stem=original\|<output id>` for a crate song; not both. 422 on bad input, 503 when ACE-Step is not set up. `/api/config` reports `generate.ready` |
| POST | `/api/jobs/{id}/extend-preview` | JSON `{extend, bpm?, downbeat?, only?}` (`only`: the manual operation to hear). Returns a short FLAC of the joins; 503 while the separator is busy |
| POST | `/api/jobs?from_job={id}` | No body: another edit of an already uploaded song. The new job gets its own hard link (or copy) of the original, so the upload is not repeated and deleting one edit never affects another. Takes the same options as an upload; `filename` is ignored |
| GET | `/api/jobs` | Latest 100 jobs |
| GET | `/api/jobs/{id}` | Status, stage and error |
| POST | `/api/jobs/{id}/cancel` | Cancel or request running job cancellation |
| POST | `/api/jobs/{id}/retry` | Retry a failed/cancelled job |
| DELETE | `/api/jobs/{id}` | Remove terminal job and files |
| GET | `/api/jobs/{id}/audio/{stem}` | Original WAV/MP3 or a generated WAV listed in the job's `outputs`; supports range playback |
| GET | `/api/jobs/{id}/download` | ZIP containing only the requested output files |
| GET | `/api/config` | Upload limits and engine settings |
| POST | `/api/playlist/pick` | Opens a native directory dialog and waits. Returns `{cancelled: false, path, name}` or `{cancelled: true}`. The path is checked the same way as browse |
| GET | `/api/playlist/browse?path=` | Child folders of an absolute directory. `parent` is null at the filesystem root |
| POST | `/api/playlist/scans` | JSON `{path}`. Starts a scan of the top-level WAV and MP3 files. Returns 202 with `id`, `status: running`, `done`, and `total` |
| GET | `/api/playlist/scans/{id}` | Poll until `completed`, `cancelled`, or `failed`. `tracks` and `unread` stay empty until `completed` |
| DELETE | `/api/playlist/scans/{id}` | Cancel the scan and stop its analysis child |
| POST | `/api/playlist/order` | JSON `{tracks, pinned, held}`. Drops held paths and rows with no BPM or Camelot, then returns `{order}` |
| GET | `/api/playlist/audio?path=` | Stream a WAV or MP3 that is a direct child of its parent directory; supports range playback |
| GET | `/health/live`, `/health/ready` | HTTP liveness and queue storage readiness |

Add `?download=true` to an audio URL for an attachment. Readiness checks queue storage; Compose separately checks worker responsiveness. Local mode polls SQLite every second. Jobs follow `queued → running → completed/failed`, with `cancelling → cancelled` for active cancellation. Failed dispatch is visible and retryable. Running inference executes in a child process so cancellation and timeouts can stop GPU work. Locks prevent overlapping attempts; stale job recovery will not release an attempt while its process still holds the lock.

The upload also accepts the reading from the analysis poll as `bpm`, `camelot`, `key_name`, `downbeat`, and `analysis_warning` (the poll calls that last field `warning`). Omitted fields are stored as null, so older jobs stay valid. It also accepts `start` and `end` (seconds) to separate only that section, or `ranges=0-5,10-15` for several stretches. A single pair sent as `ranges` is stored the same way as `start` and `end`. Each range must be at least one second, inside the track, and must not overlap another; at most 12 ranges. Do not send `start`/`end` together with `ranges`. `end` must be within the track. The upload accepts `mode=all` (default), `mode=vocals`, `mode=instrumental`, or `mode=custom&keep=vocals,bass`. Custom mode requires at least one unique source from `vocals,drums,bass,other`. Other modes reject `keep`. Each job response includes `mode`, `keep`, `ranges` (the stretches, or null for the whole track), and `outputs` (file ID, label, and included sources). Only the original and that job's requested outputs can be downloaded.

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

Source layout: `routes.py` handles upload/jobs/downloads and the playlist booth; `jobs.py` owns SQLite state, including cached playlist readings; `playlist.py` orders readable tracks by Camelot and tempo; `worker.py` manages inference processes; `inference.py` runs Demucs; `local.py` starts the direct local services; `frontend/` is the Svelte interface, built into `src/stemlab/web/ui/`.

## Open source

App code is MIT licensed. Runtime uses [FastAPI](https://github.com/fastapi/fastapi), [Celery](https://github.com/celery/celery), [Valkey](https://valkey.io/topics/introduction/), [PyTorch](https://pytorch.org/blog/pytorch-2-7/) and [Demucs](https://github.com/facebookresearch/demucs). The original Demucs repository is archived; this app pins its released engine and a compatible PyTorch stack. CUDA runtime libraries have NVIDIA's own license, and require no paid API or service.
