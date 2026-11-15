#!/usr/bin/env bash
# Scans every lockfile in the repository with OSV-Scanner, the scanner the OpenSSF Scorecard Vulnerabilities check uses, so
# this audit and the Scorecard cannot drift apart: the npm lockfiles (frontend, website, and the website's Lighthouse and
# diagram tools), backend/uv.lock, and the Android Gradle lockfiles. The recursive scan finds the former and honours
# .gitignore (no node_modules); Gradle names its lockfiles per project (frontend/android/gradle/locks), which the scanner
# does not recognise by name, so each one is passed as a gradle.lockfile explicitly. Exceptions live in osv-scanner.toml
# at the repository root, each with a reason and an expiry date. The scanner runs from an image pinned by digest (v2.7.0).
set -euo pipefail

# An optional argument names another tree to scan; the local gate passes the exported (published) tree, so private
# tools in the source repository, which are never published, do not count.
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "${1:-$here/../..}" && pwd)"
image="ghcr.io/google/osv-scanner@sha256:4f3b7e2c64b9d38a5febc5a7e4a3dfef1d1362f726dea7a2ef4762b46469fcd0"

args=()
for lock in "$root"/frontend/android/gradle/locks/*.lockfile; do
  [ -e "$lock" ] || continue
  args+=(-L "gradle.lockfile:${lock#"$root"/}")
done
if [ "${#args[@]}" -eq 0 ]; then
  echo "osv-scan.sh: no Gradle lockfiles found under frontend/android/gradle/locks" >&2
  exit 1
fi

docker run --rm -v "$root:/src:ro" -w /src "$image" scan source -r "${args[@]}" .
