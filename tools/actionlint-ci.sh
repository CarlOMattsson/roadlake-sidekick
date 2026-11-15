#!/usr/bin/env bash
# actionlint over every tracked workflow file, as the CI actionlint job runs it: the pinned image (ACTIONLINT_IMAGE in
# tools/ci-images.sh), with no network and a read-only checkout. The image's own ShellCheck checks the `run:` blocks; it is
# the version of SHELLCHECK_IMAGE, so no rule is turned off here. Used by CI and by tools/check-all.sh.
#
#   bash tools/actionlint-ci.sh [DIR]     DIR is a git checkout (default: this one)
# Exit 77 with a SKIPPED line when Docker is missing.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/ci-images.sh
. "$HERE/ci-images.sh"

ROOT="$(cd "${1:-$HERE/..}" && pwd)"
cd "$ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "SKIPPED: docker missing (install: https://docs.docker.com/engine/install/), so actionlint did not run in the CI image"
  exit 77
fi

# The workflows of this repository and, in the working repository, the copies that the export overlay publishes instead.
workflows=()
while IFS= read -r -d '' file; do
  workflows+=("$file")
done < <(git ls-files -z -- ':(glob).github/workflows/*.yml' ':(glob).github/workflows/*.yaml' \
  ':(glob)tools/*/overlay/.github/workflows/*.yml' ':(glob)tools/*/overlay/.github/workflows/*.yaml')

if [ "${#workflows[@]}" -eq 0 ]; then
  echo "actionlint-ci: no workflow files found in $ROOT" >&2
  exit 1
fi

printf '+ docker run %s (%d workflows)\n' "$ACTIONLINT_IMAGE" "${#workflows[@]}"
docker run --rm --network none --read-only -u "$(id -u):$(id -g)" -v "$ROOT:/mnt:ro" -w /mnt "$ACTIONLINT_IMAGE" -oneline "${workflows[@]}"
