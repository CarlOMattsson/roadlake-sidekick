#!/usr/bin/env bash
# ShellCheck over every tracked shell script, as the CI shellcheck job runs it: the pinned image (SHELLCHECK_IMAGE in
# tools/ci-images.sh), severity warning, and the file selection below. Used by CI and by tools/check-all.sh.
#
#   bash tools/shellcheck-ci.sh [DIR]     DIR is a git checkout (default: this one)
# Exit 77 with a SKIPPED line when Docker is missing.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/ci-images.sh
. "$HERE/ci-images.sh"

ROOT="$(cd "${1:-$HERE/..}" && pwd)"
cd "$ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "SKIPPED: docker missing (install: https://docs.docker.com/engine/install/), so shellcheck did not run in the CI image"
  exit 77
fi

# *.sh files and extensionless tracked files whose first line is a sh or bash shebang.
scripts=()
while IFS= read -r -d '' file; do
  case "$file" in
    *.sh) ;;
    *) [ -f "$file" ] && head -c 128 "$file" | head -n 1 | grep -aEq '^#!.*\b(ba)?sh\b' || continue ;;
  esac
  scripts+=("$file")
done < <(git ls-files -z)

printf '+ docker run %s --severity=warning (%d scripts)\n' "$SHELLCHECK_IMAGE" "${#scripts[@]}"
docker run --rm -u "$(id -u):$(id -g)" -v "$ROOT:/mnt:ro" -w /mnt "$SHELLCHECK_IMAGE" --severity=warning "${scripts[@]}"
