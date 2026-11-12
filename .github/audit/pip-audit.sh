#!/usr/bin/env bash
# Scans every locked Python dependency of the backend (backend/uv.lock: runtime and the dev group, which holds the build,
# lint, type and test tooling that runs in CI and on contributors' machines) with pip-audit.
# Exceptions live in pip-audit-ignores.txt next to this script, one per line:
# `<advisory id> | <expiry YYYY-MM-DD> | <reason>`. An entry without a reason or a valid expiry date fails the run, and so
# does an entry whose date has passed: an exception must always be explained and must be decided again before it lapses.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../.." && pwd)"
ignores="$here/pip-audit-ignores.txt"

today="${PIP_AUDIT_TODAY:-$(date +%F)}"
args=()
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in '' | '#'*) continue ;; esac
  IFS='|' read -r id expiry reason <<< "$line"
  id="$(echo "$id" | tr -d '[:space:]')"
  expiry="$(echo "$expiry" | tr -d '[:space:]')"
  if [ -z "$id" ] || [ -z "${reason//[[:space:]]/}" ] ||
    ! [[ "$expiry" =~ ^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$ ]]; then
    echo "pip-audit-ignores.txt: every entry needs '<id> | <expiry YYYY-MM-DD> | <reason>': $line" >&2
    exit 1
  fi
  # ISO dates compare correctly as strings. The expiry day itself is the last day the exception holds.
  if [[ "$expiry" < "$today" ]]; then
    echo "pip-audit-ignores.txt: the exception for $id expired on $expiry; fix the dependency or decide again: $line" >&2
    exit 1
  fi
  args+=(--ignore-vuln "$id")
done < "$ignores"

requirements="$(mktemp)"
trap 'rm -f "$requirements"' EXIT
uv export --project "$root/backend" --frozen --all-groups --no-emit-project --no-hashes --quiet -o "$requirements"

# Every requirement is an exact pin from the lockfile, so no dependency resolution (and no pip) is needed.
uvx pip-audit==2.10.1 -r "$requirements" --no-deps --disable-pip --progress-spinner off ${args[@]+"${args[@]}"}
