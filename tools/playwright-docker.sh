#!/usr/bin/env bash
# Runs a command in frontend/ inside the pinned Playwright image (PLAYWRIGHT_IMAGE in tools/ci-images.sh). CI runs its
# browser tests the same way, so the browser build and the fonts (which decide card heights) are the same locally.
#
#   bash tools/playwright-docker.sh [--root DIR] COMMAND...
#   bash tools/playwright-docker.sh npx playwright test --config playwright.mcp-app.config.ts
#
# --root DIR  the checkout to test (default: this one); its frontend/node_modules and built files are used as they are.
# PW_WORKERS, MOBILE_AUDIT_OUT and TZ are passed on when set. A MOBILE_AUDIT_OUT outside the checkout is mounted too.
# Exit 77 with a SKIPPED line when Docker is missing (the convention of tools/check-all.sh); other exit codes are the command's.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/ci-images.sh
. "$HERE/ci-images.sh"

ROOT="$(cd "$HERE/.." && pwd)"
if [ "${1:-}" = "--root" ]; then
  [ $# -ge 2 ] || { echo "playwright-docker: --root needs a value" >&2; exit 2; }
  ROOT="$(cd "$2" && pwd)"
  shift 2
fi
[ $# -gt 0 ] || { echo "playwright-docker: no command given" >&2; exit 2; }

if ! command -v docker >/dev/null 2>&1; then
  echo "SKIPPED: docker missing (install: https://docs.docker.com/engine/install/), so the browser tests did not run in the CI image"
  exit 77
fi

mounts=(-v "$ROOT:$ROOT")
# A node_modules that is a link (a shared install, or the one linked into an export) must be reachable inside the
# container at its real place.
if [ -e "$ROOT/frontend/node_modules" ]; then
  modules="$(realpath "$ROOT/frontend/node_modules")"
  case "$modules/" in
    "$ROOT"/*) ;;
    *) mounts+=(-v "$modules:$modules:ro") ;;
  esac
fi
envs=()
for name in PW_WORKERS MOBILE_AUDIT_OUT TZ; do
  if [ -n "${!name:-}" ]; then
    envs+=(-e "$name=${!name}")
  fi
done
if [ -n "${MOBILE_AUDIT_OUT:-}" ]; then
  mkdir -p "$MOBILE_AUDIT_OUT"
  mounts+=(-v "$MOBILE_AUDIT_OUT:$MOBILE_AUDIT_OUT")
fi

printf '+ docker run %s (in %s/frontend): %s\n' "$PLAYWRIGHT_IMAGE" "$ROOT" "$*"
exec docker run --rm --init --ipc=host -u "$(id -u):$(id -g)" -e HOME=/tmp -e CI=1 \
  "${envs[@]}" "${mounts[@]}" -w "$ROOT/frontend" "$PLAYWRIGHT_IMAGE" "$@"
