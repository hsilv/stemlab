# Claude instructions for StemLab

Read and follow [AGENTS.md](AGENTS.md) before working in this repository. It is the shared source of project instructions for all coding agents. Consult [README.md](README.md) for user-facing setup and API details, and verify behavior against the current source.

## Important reminders

- This is an implemented local WAV/MP3 separation app with GPU support, an interactive output selector, history, previews and downloads. Preserve those workflows.
- Keep audio local and prefer free/open-source dependencies. The interface is Svelte 5 in `frontend/`; FastAPI serves the static build from `src/stemlab/web/ui/`.
- Use the existing `outputs.py` plan and shared worker pipeline when changing export modes. Preserve stored selections, old jobs and the original upload format.
- Preserve the installed inference extra: plain `uv run` or `uv sync` may remove CUDA dependencies. Prefer `.venv/bin/…` for checks in the configured environment, or specify the intended uv extra.
- Use a separate port/data directory for browser tests, and check for active jobs before restarting the user's app. Never assume services are currently running or Docker is available.
- Quality presets, aggressive cleanup and live mixing controls were discussed only as possibilities. They are not implemented or authorized follow-up tasks unless the current request asks for them.
- A question-only request calls for an answer, not repository changes. Distinguish verified behavior from proposed improvements and from tests you could not run.

## Common checks

```sh
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest
npm run build --prefix frontend
```

Use the real-inference and browser workflows in AGENTS.md when relevant to the change; documentation-only changes need no audio-processing run. Keep project-wide instructions in AGENTS.md rather than duplicating them here, and update README when user-visible behavior changes.
