#!/usr/bin/env bash
# Scans the Android Gradle dependency lockfiles (frontend/android/gradle/locks) with OSV-Scanner, which knows Maven
# advisories. The npm and Python lockfiles are covered by npm audit and pip-audit. The scanner runs from an image pinned
# by digest (v2.7.0). Gradle names its lockfiles per project, so each one is passed as a gradle.lockfile explicitly.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../.." && pwd)"
image="ghcr.io/google/osv-scanner@sha256:4f3b7e2c64b9d38a5febc5a7e4a3dfef1d1362f726dea7a2ef4762b46469fcd0"

args=()
for lock in "$root"/frontend/android/gradle/locks/*.lockfile; do
  [ -e "$lock" ] || continue
  args+=(-L "gradle.lockfile:${lock#"$root"/}")
done
if [ "${#args[@]}" -eq 0 ]; then
  echo "osv-gradle.sh: no Gradle lockfiles found under frontend/android/gradle/locks" >&2
  exit 1
fi

docker run --rm -v "$root:/src:ro" -w /src "$image" scan "${args[@]}"
