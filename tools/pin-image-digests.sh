#!/usr/bin/env bash
# Pin external container images by digest: rewrites `image: name:tag` (compose) and
# `FROM`/`COPY --from=` (Dockerfile) references to `name:tag@sha256:<digest>`.
#
# Default is a read-only report of every external reference that is not pinned (exit 1 if any).
# `--write` resolves each missing digest from the registry and rewrites the file in place; refs that
# cannot be resolved are listed and left untouched (exit 1), never guessed. The pin keeps the tag next
# to the digest, so a reader sees the version and the digest is what the daemon verifies.
#
# usage: tools/pin-image-digests.sh [--write] [FILE...]
# Default FILEs are the Dockerfile and compose files of the release, work and test setups (DEFAULT_FILES below).
# Digest lookup order: `docker buildx imagetools inspect`, `skopeo inspect`, then the registry HTTP API
# (curl, anonymous pull token; manifest list digest from the Docker-Content-Digest header).
# The same detection rules are enforced in CI.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_FILES=(
  backend/Dockerfile
  deploy/selfhost/compose.yaml
  deploy/work/compose.yaml
  deploy/compose.dev.yaml
  deploy/compose.test.yaml
)
ACCEPT='application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json'

write=0
files=()
while [ $# -gt 0 ]; do
  case "$1" in
    --write) write=1 ;;
    -h | --help)
      sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    -*)
      echo "pin-image-digests.sh: unknown option" >&2
      exit 2
      ;;
    *) files+=("$1") ;;
  esac
  shift
done
if [ "${#files[@]}" -eq 0 ]; then
  for f in "${DEFAULT_FILES[@]}"; do files+=("$ROOT/$f"); done
fi

# Prints the unpinned external refs of a file, one per line. Local and templated names and the names of
# earlier `FROM ... AS <stage>` build stages (as in `COPY --from=<stage>`) are skipped.
unpinned_refs() {
  local stages
  stages="$(sed -nE 's/^FROM[[:space:]].*[[:space:]][Aa][Ss][[:space:]]+([^[:space:]]+).*$/\1/p' "$1")"
  sed -nE \
    -e 's/^[[:space:]]*image:[[:space:]]*"?([^"[:space:]#]+)"?.*$/\1/p' \
    -e 's/^FROM[[:space:]]+(--[^[:space:]]+[[:space:]]+)*([^[:space:]]+).*$/\2/p' \
    -e 's/^.*COPY[[:space:]]+--from=([^[:space:]]+).*$/\1/p' "$1" |
    grep -v -e '@sha256:' -e '\$' -e '^scratch$' -e '^sidekick-' -e '^roadlake-sidekick' |
    { grep -vxF "$stages" || true; } |
    grep -E '^[a-z0-9][a-z0-9._/-]*(:[A-Za-z0-9._-]+)?$' | sort -u || true
}

registry_digest() { # $1 = name:tag
  local ref="$1" name tag host repo token url
  name="${ref%%:*}"
  tag="${ref#*:}"
  [ "$tag" != "$ref" ] || tag=latest
  case "${name%%/*}" in
    *.*)
      host="${name%%/*}"
      repo="${name#*/}"
      ;;
    *)
      host="registry-1.docker.io"
      repo="$name"
      [[ "$repo" == */* ]] || repo="library/$repo"
      ;;
  esac
  if [ "$host" = "registry-1.docker.io" ]; then
    url="https://auth.docker.io/token?service=registry.docker.io&scope=repository:$repo:pull"
  else
    url="https://$host/token?scope=repository:$repo:pull"
  fi
  token="$(curl -fsS --max-time 20 "$url" | sed -nE 's/.*"token":"([^"]+)".*/\1/p')"
  curl -fsSI --max-time 20 -H "Authorization: Bearer $token" -H "Accept: $ACCEPT" \
    "https://$host/v2/$repo/manifests/$tag" |
    tr -d '\r' | awk 'tolower($1) == "docker-content-digest:" {print $2}' | head -n 1
}

# SHA-256 of zero bytes: what a failed fetch piped into sha256sum used to produce. Never a real manifest.
EMPTY_SHA256="sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

valid_digest() { # $1 = candidate; true only for a well-formed digest that is not the hash of empty input
  [[ "$1" =~ ^sha256:[0-9a-f]{64}$ ]] && [ "$1" != "$EMPTY_SHA256" ]
}

skopeo_digest() { # $1 = name:tag; digest of the raw manifest, only if skopeo exited 0 with non-empty output
  local ref="$1" raw sum
  raw="$(mktemp)" || return 1
  # The manifest goes through a file: $(...) would strip trailing newlines and change the hash, and every
  # step's exit status is checked so that a failed or empty fetch is never hashed into a plausible digest.
  if skopeo inspect --raw "docker://$ref" >"$raw" 2>/dev/null && [ -s "$raw" ] && sum="$(sha256sum <"$raw")"; then
    rm -f "$raw"
    printf 'sha256:%s\n' "${sum%% *}"
    return 0
  fi
  rm -f "$raw"
  return 1
}

resolve() { # $1 = name:tag; prints sha256:<hex> or nothing. A source counts only if it exited 0 with a valid digest.
  local ref="$1" digest="" out
  if command -v docker >/dev/null 2>&1 && docker buildx version >/dev/null 2>&1; then
    if out="$(docker buildx imagetools inspect "$ref" 2>/dev/null)"; then
      digest="$(printf '%s\n' "$out" | awk '/^Digest:/ {print $2; exit}')"
    fi
    valid_digest "$digest" || digest=""
  fi
  if [ -z "$digest" ] && command -v skopeo >/dev/null 2>&1; then
    digest="$(skopeo_digest "$ref" || true)"
    valid_digest "$digest" || digest=""
  fi
  if [ -z "$digest" ] && command -v curl >/dev/null 2>&1; then
    digest="$(registry_digest "$ref" 2>/dev/null || true)"
    valid_digest "$digest" || digest=""
  fi
  if [ -n "$digest" ]; then
    printf '%s\n' "$digest"
  fi
  return 0
}

missing=0
for file in "${files[@]}"; do
  [ -f "$file" ] || {
    echo "pin-image-digests.sh: no such file: ${file#"$ROOT"/}" >&2
    exit 2
  }
  while IFS= read -r ref; do
    [ -n "$ref" ] || continue
    if [ "$write" -eq 0 ]; then
      echo "UNPINNED ${file#"$ROOT"/}: $ref"
      missing=1
      continue
    fi
    digest="$(resolve "$ref")"
    if [ -z "$digest" ]; then
      echo "UNRESOLVED ${file#"$ROOT"/}: $ref (left unchanged)" >&2
      missing=1
      continue
    fi
    escaped="${ref//./\\.}" # refs hold only [a-z0-9._/:-]; the dot is the only regex metacharacter
    sed -i -E "s|([[:space:]=\"'])$escaped(\"\|[[:space:]]\|\$)|\1$ref@$digest\2|" "$file"
    echo "PINNED ${file#"$ROOT"/}: $ref@$digest"
  done < <(unpinned_refs "$file")
done
exit "$missing"
