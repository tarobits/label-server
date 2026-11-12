#!/bin/sh
# Preserve the caller's working directory and pass every option unchanged.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$root/scripts/install.py" "$@"
