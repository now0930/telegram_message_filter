#!/usr/bin/env bash
set -Eeuo pipefail

# Backwards-compatible name. Future updates stay in one runtime directory.
script_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "$script_root/update_single_runtime.sh" "$@"
