#!/usr/bin/env bash
# Trivy over the API image, as the release workflow scans it before it signs the digest (the same Trivy version and the
# same selection: OS packages and libraries, HIGH and CRITICAL findings that have a fix). The scanner is the pinned image
# TRIVY_IMAGE in tools/ci-images.sh. Used by tools/check-all.sh --release.
#
#   bash tools/image-scan.sh [IMAGE]    IMAGE is a local image; without it backend/Dockerfile is built from this
#                                       checkout (a temporary tag, removed again) and that image is scanned
# Only the platform of this machine is scanned here; the release workflow scans linux/amd64 and linux/arm64.
# Exit 77 with a SKIPPED line when Docker is missing or the vulnerability database cannot be fetched.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/ci-images.sh
. "$HERE/ci-images.sh"

ROOT="$(cd "$HERE/.." && pwd)"
SOCKET=/var/run/docker.sock
# Trivy keeps its vulnerability database here between runs (it downloads about 130 MB the first time and when stale).
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/roadlake-sidekick/trivy"

if ! command -v docker >/dev/null 2>&1; then
  echo "SKIPPED: docker missing (install: https://docs.docker.com/engine/install/), so the image was not scanned"
  exit 77
fi
if [ ! -S "$SOCKET" ]; then
  echo "SKIPPED: $SOCKET not found, so Trivy cannot read the local image"
  exit 77
fi
# The database comes from this host (the one the workflow's Trivy downloads it from); without a cached copy there is no scan.
if [ ! -d "$CACHE/db" ] && ! python3 -c 'import socket; socket.create_connection(("mirror.gcr.io", 443), 4).close()' 2>/dev/null; then
  echo "SKIPPED: the vulnerability database is not cached and mirror.gcr.io is unreachable, so the image was not scanned"
  exit 77
fi

image="${1:-}"
if [ -z "$image" ]; then
  image="roadlake-sidekick-scan:local"
  printf '+ docker build -f backend/Dockerfile -t %s .\n' "$image"
  docker build -q -f "$ROOT/backend/Dockerfile" -t "$image" "$ROOT" >/dev/null
  trap 'docker image rm "$image" >/dev/null 2>&1 || true' EXIT
fi

mkdir -p "$CACHE"
printf '+ docker run %s image --severity HIGH,CRITICAL --ignore-unfixed %s\n' "$TRIVY_IMAGE" "$image"
docker run --rm -u "$(id -u):$(stat -c %g "$SOCKET")" -e HOME=/tmp \
  -v "$SOCKET:$SOCKET" -v "$CACHE:/cache" \
  "$TRIVY_IMAGE" image --cache-dir /cache --scanners vuln --pkg-types os,library \
  --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 --format table --skip-version-check "$image"
