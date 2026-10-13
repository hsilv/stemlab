"""Create StemLab's Python environment with the right PyTorch build for this machine.

Standard library only, so it runs before anything is installed:

    python scripts/bootstrap.py                  # NVIDIA GPU found: cuda, else CPU
    python scripts/bootstrap.py --extra inference
    python scripts/bootstrap.py --env C:\\Users\\me\\stemlab-env --uv C:\\tools\\uv.exe

The desktop app runs the same script on first launch. It only wraps `uv sync --frozen --extra X`,
so the result is exactly what the README's manual commands make.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def has_nvidia_gpu():
    """True when the NVIDIA driver answers; PyTorch carries its own CUDA runtime."""
    tool = shutil.which("nvidia-smi")
    if not tool:
        return False
    try:
        result = subprocess.run([tool, "-L"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and "GPU" in result.stdout


def choose_extra(requested, gpu=None):
    if requested != "auto":
        return requested
    return "cuda" if (has_nvidia_gpu() if gpu is None else gpu) else "inference"


def sync_command(uv, project, extra):
    return [str(uv), "sync", "--frozen", "--project", str(project), "--extra", extra]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--extra", choices=["auto", "cuda", "inference"], default="auto")
    parser.add_argument("--project", type=Path, default=ROOT, help="the folder with pyproject.toml")
    parser.add_argument("--env", type=Path, help="where to create the environment (default .venv)")
    parser.add_argument("--uv", type=Path, help="the uv executable (default: found on PATH)")
    parser.add_argument("--dry-run", action="store_true", help="print the command and stop")
    args = parser.parse_args(argv)

    uv = args.uv or shutil.which("uv")
    if not uv:
        print(
            "uv was not found. Install it from https://docs.astral.sh/uv/getting-started/"
            "installation/ or pass --uv.",
            file=sys.stderr,
        )
        return 2
    extra = choose_extra(args.extra)
    command = sync_command(uv, args.project, extra)
    env = dict(os.environ)
    if args.env:
        env["UV_PROJECT_ENVIRONMENT"] = str(args.env)
    print(f"STAGE:Installing the {'GPU (CUDA)' if extra == 'cuda' else 'CPU'} build", flush=True)
    print(" ".join(command), flush=True)
    if args.dry_run:
        return 0
    return subprocess.run(command, env=env).returncode


if __name__ == "__main__":
    sys.exit(main())
