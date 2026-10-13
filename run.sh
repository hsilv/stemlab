#!/bin/sh
set -eu

cd "$(dirname "$(readlink -f "$0")")"

if [ ! -x .venv/bin/python ]; then
  echo "Missing .venv/bin/python. See README.md to install the environment." >&2
  exit 1
fi

exec .venv/bin/python -m stemlab.local
