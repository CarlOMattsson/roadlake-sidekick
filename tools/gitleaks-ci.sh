#!/usr/bin/env bash
# gitleaks over the whole git history, as the CI secrets job runs it: the pinned image (GITLEAKS_IMAGE in
# tools/ci-images.sh) with `detect --redact`, which reads the checkout's own .gitleaks.toml and .gitleaksignore.
# Used by CI and by tools/check-all.sh.
#
#   bash tools/gitleaks-ci.sh [DIR]     DIR is a git checkout or worktree (default: this one)
# Exit 77 with a SKIPPED line when Docker is missing.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/ci-images.sh
. "$HERE/ci-images.sh"

ROOT="$(cd "${1:-$HERE/..}" && pwd)"

if ! command -v docker >/dev/null 2>&1; then
  echo "SKIPPED: docker missing (install: https://docs.docker.com/engine/install/), so gitleaks did not run in the CI image"
  exit 77
fi

mounts=(-v "$ROOT:$ROOT:ro")
# A linked worktree keeps its history in the main repository's git directory; it must be reachable at the same path.
common="$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir)"
case "$common/" in
  "$ROOT"/*) ;;
  *) mounts+=(-v "$common:$common:ro") ;;
esac

printf '+ docker run %s detect --redact (full history of %s)\n' "$GITLEAKS_IMAGE" "$ROOT"
docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp \
  -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e "GIT_CONFIG_VALUE_0=*" \
  "${mounts[@]}" -w "$ROOT" "$GITLEAKS_IMAGE" detect --no-banner --redact -v --exit-code=2 --source "$ROOT"
