#!/usr/bin/env bash
# Disposable-container drill: install -> update -> backup -> destroy -> restore, for the self-hosted stack
# (deploy/selfhost: update.sh, its encrypted snapshot) and for the work package (tools/work.sh: encrypted database
# and Hindsight backups with their own key), each in its own throw-away compose project.
#
#   bash tools/drill.sh selfhost|work|all [--from-image REF] [--to-image REF] [--cert-identity ID]
#                                          [--local-images] [--allow-same-schema] [--log FILE] [--dry-run]
#
#   --from-image REF   the previously released api image to install first (env DRILL_FROM_IMAGE)
#   --to-image REF     the image to update to (env DRILL_TO_IMAGE); both must be REGISTRY/REPO@sha256:<64 hex>
#   --cert-identity ID signer identity update.sh must find in the cosign signature (env DRILL_CERT_IDENTITY);
#                      needed for selfhost, which verifies the real signature (cosign must be installed)
#   --local-images     no released images: build the api image twice from this checkout (versions X.Y.Z and X.Y.Z+1),
#                      push both to a throw-away registry on 127.0.0.1 to get real digests, and drill with them.
#                      cosign is a stand-in that only checks the shape of the call, so the signature itself is NOT
#                      verified in this mode (that needs released images); implies --allow-same-schema. Needs
#                      docker, python3 and the registry image (pulled when missing). Not combinable with --dry-run
#                      or with --from-image/--to-image.
#   --allow-same-schema  accept an update that does not move the schema version (a patch release without migrations)
#   --log FILE         where the step log goes (default: a new file in $TMPDIR; its path is printed at the end)
#   --dry-run          a fake docker and cosign in a temp bin dir; nothing real is started (same as DRILL_FAKE_DOCKER=1)
#   --project NAME     base name of the compose projects; MUST start with sk-drill- (anything else: exit 2, nothing runs)
#
# Safety, by construction:
#   * every compose project is named sk-drill-<random>-<scenario>; the script refuses (exit 2) any other name, and
#     the EXIT/INT/TERM trap runs `docker compose -p <that project> down -v --remove-orphans` for those projects only
#     (plus the leftover volumes that carry the label of one of them) and removes the images --local-images built
#     (by their exact references), then removes the temp dir;
#   * all state (env files, secrets, backups, keys, a copy of the deploy files) lives in one mktemp -d; the real
#     deploy directories, env files and secrets of the repository are never read, written or copied (env files and
#     secrets directories are left out of the copy);
#   * published ports are random, bound to 127.0.0.1, and never one of the reserved ports (default 55432, 55433, 55434, 55436, 8100, 8101;
#     SIDEKICK_RESERVED_PORTS, comma-separated, adds more and never removes any);
#   * the self-hosted stack runs with its `memory` profile (the real Hindsight container, a dummy model address, no key
#     worth the name), so the drill covers the Hindsight volume the way the guide archives and restores it;
#   * the scenarios run the real update.sh and the real tools/work.sh (copied into the temp dir).
#
# DRILL_FAKE_FAIL (dry run only) makes the fake docker misbehave to prove the drill notices: a comma list of
# lose-marker, no-schema-move, wrong-key-accepted, lose-hindsight. DRILL_FAKE_LOG names the file the fake docker logs
# every call to (default: inside the temp dir, so gone after the run). DRILL_KEEP_TEMP=1 keeps the temp dir
# (the compose projects are still removed).
#
# Every step prints its duration; the table of durations follows the summary. In GitHub Actions a failed step also
# becomes an error annotation and the table goes to the job summary.
#
# Exit status: 0 all steps passed, 1 a step failed, 2 usage error or refused project name.
set -euo pipefail
umask 077

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_PREFIX="sk-drill-"
# Reserved ports: the drill must never touch these (long-running databases and their API ports, plus the test pool's 55433).
# SIDEKICK_RESERVED_PORTS (comma-separated) only adds to this list.
RESERVED_PORTS=(55432 55433 55434 55436 8100 8101)
# The checks are tools/drill_policy.py (the host's python3); what the cleanup may remove stays in this file.
drill_policy() { python3 -I "$REPO/tools/drill_policy.py" "$@"; }
if [ -n "${SIDEKICK_RESERVED_PORTS:-}" ]; then
  extra_reserved="$(drill_policy reserved-ports "$SIDEKICK_RESERVED_PORTS")" || exit 2
  while IFS= read -r _p; do
    [ -z "$_p" ] || RESERVED_PORTS+=("$_p")
  done <<<"$extra_reserved"
fi

# Nothing from the caller's shell may steer the stacks of the drill.
unset SIDEKICK_API_IMAGE SIDEKICK_API_IMAGE_PREVIOUS SIDEKICK_WORK_API_IMAGE SIDEKICK_WORK_PROJECT \
  SIDEKICK_WORK_BACKUP_KEY_FILE SIDEKICK_BACKUP_ENCRYPTION_KEY SIDEKICK_RELEASE_CERT_IDENTITY \
  COMPOSE_FILE COMPOSE_PROJECT_NAME COMPOSE_PROFILES

usage() {
  sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
  exit 2
}

# ---------------------------------------------------------------------------------------------------------
# Arguments

scenario=""
dry=0
from_image="${DRILL_FROM_IMAGE:-}"
to_image="${DRILL_TO_IMAGE:-}"
identity="${DRILL_CERT_IDENTITY:-}"
allow_same_schema=0
local_images=0
base_project=""
LOG=""
[ "${DRILL_FAKE_DOCKER:-}" = 1 ] && dry=1

[ $# -ge 1 ] || usage
case "$1" in
  selfhost | work | all) scenario="$1"; shift ;;
  *) usage ;;
esac
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) dry=1; shift ;;
    --allow-same-schema) allow_same_schema=1; shift ;;
    --local-images) local_images=1; shift ;;
    --from-image) [ $# -ge 2 ] || usage; from_image="$2"; shift 2 ;;
    --to-image) [ $# -ge 2 ] || usage; to_image="$2"; shift 2 ;;
    --cert-identity) [ $# -ge 2 ] || usage; identity="$2"; shift 2 ;;
    --log) [ $# -ge 2 ] || usage; LOG="$2"; shift 2 ;;
    --project) [ $# -ge 2 ] || usage; base_project="$2"; shift 2 ;;
    *) usage ;;
  esac
done

rand_hex8() { od -An -N4 -tx1 /dev/urandom | tr -d ' \n'; }

valid_project() { [[ "$1" =~ ^sk-drill-[a-z0-9][a-z0-9-]*$ ]]; }

# Every project name passes through here before anything is started (and again before anything is removed).
require_drill_project() {
  if ! valid_project "$1"; then
    echo "drill: refusing to run: compose project name must start with ${PROJECT_PREFIX} (lower case letters, digits, hyphens)" >&2
    exit 2
  fi
}

base_project="${base_project:-${PROJECT_PREFIX}$(rand_hex8)}"
require_drill_project "$base_project"
SH_PROJECT="${base_project}-sh"
WK_PROJECT="${base_project}-wk"
REG_PROJECT="${base_project}-reg"
require_drill_project "$SH_PROJECT"
require_drill_project "$WK_PROJECT"
require_drill_project "$REG_PROJECT"

if [ "$local_images" = 1 ]; then
  if [ "$dry" = 1 ] || [ -n "$from_image" ] || [ -n "$to_image" ]; then
    echo "drill: --local-images builds and runs real images; it cannot be combined with --dry-run, --from-image or --to-image" >&2
    exit 2
  fi
  identity="${identity:-drill@example.invalid}"
  allow_same_schema=1 # both images come from the same checkout: the schema cannot move
  from_image="local" to_image="local" # placeholders until the images are built (see local_images_build)
fi

if [ "$dry" = 1 ]; then
  from_image="${from_image:-registry.example/sidekick@sha256:$(printf 'a%.0s' $(seq 64))}"
  to_image="${to_image:-registry.example/sidekick@sha256:$(printf 'b%.0s' $(seq 64))}"
  identity="${identity:-drill@example.invalid}"
fi
if [ "$local_images" = 0 ]; then
  drill_policy image-pair --from "$from_image" --to "$to_image" || exit 2
fi
if [ "$scenario" != work ] && [ -z "$identity" ]; then
  echo "drill: selfhost needs --cert-identity (or DRILL_CERT_IDENTITY): update.sh verifies the real signature" >&2
  exit 2
fi

# ---------------------------------------------------------------------------------------------------------
# Temp dir, log, cleanup

TMP="$(mktemp -d "${TMPDIR:-/tmp}/sk-drill.XXXXXX")"
if [ -z "$LOG" ]; then
  LOG="$(mktemp "${TMPDIR:-/tmp}/sk-drill-log.XXXXXX")"
else
  : >"$LOG"
fi
mkdir -p "$TMP/kv" "$TMP/bin"
PROJECTS=()

say() { printf '%s\n' "$*" | tee -a "$LOG"; }

cleanup() {
  local rc=$? project vol
  trap - EXIT INT TERM
  set +e
  # Only the projects of this run. A name that is not sk-drill-* is skipped, never passed on to docker.
  for project in ${PROJECTS[@]+"${PROJECTS[@]}"}; do
    valid_project "$project" || continue
    docker compose -p "$project" down -v --remove-orphans >>"$LOG" 2>&1
    # Volumes of this project that `down` did not reach (for example one created ahead of the first `up`).
    for vol in $(docker volume ls -q --filter "label=com.docker.compose.project=$project" 2>/dev/null); do
      case "$vol" in "${project}_"*) docker volume rm "$vol" >>"$LOG" 2>&1 ;; esac
    done
  done
  # The images --local-images built, by their exact references (listed in kv/local_refs), never by a pattern.
  if [ -f "$TMP/kv/local_refs" ]; then
    while IFS= read -r ref; do
      [[ "$ref" =~ ^127\.0\.0\.1:[0-9]+/sidekick[:@][A-Za-z0-9:._-]+$ ]] && docker image rm "$ref" >>"$LOG" 2>&1
    done <"$TMP/kv/local_refs"
  fi
  if [ "${DRILL_KEEP_TEMP:-}" = 1 ]; then
    echo "drill: temp dir kept: $TMP" >&2
  elif [ -d "$TMP" ] && [[ "$TMP" == */sk-drill.* ]]; then
    rm -rf -- "$TMP"
  fi
  echo "drill: log: $LOG" >&2
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# ---------------------------------------------------------------------------------------------------------
# Fake docker and cosign (--dry-run): the shim keeps a small state file and logs every call. It refuses (exit 99)
# any project, volume or bind that is not an sk-drill- one.

write_fake_tools() {
  local fake_dir="$TMP/fake" python
  python="$(command -v python3)"
  mkdir -p "$fake_dir"
  export DRILL_FAKE_STATE="$fake_dir/state.json"
  export DRILL_FAKE_LOG="${DRILL_FAKE_LOG:-$fake_dir/calls.log}"
  export DRILL_FAKE_FROM="$from_image" DRILL_FAKE_TO="$to_image"
  : >"$DRILL_FAKE_LOG"
  # The fake docker is tools/drill_fake_docker.py (the host's python3); the shim only starts it.
  printf '#!/bin/sh\nexec %q -I %q "$@"\n' "$python" "$REPO/tools/drill_fake_docker.py" >"$TMP/bin/docker"
  chmod 755 "$TMP/bin/docker"
  printf '#!/bin/sh\nexit 0\n' >"$TMP/bin/cosign"
  chmod 755 "$TMP/bin/cosign"
  export PATH="$TMP/bin:$PATH"
  export SIDEKICK_UPDATE_POLL_SECONDS=0.1 SIDEKICK_UPDATE_HEALTH_TIMEOUT=60 SIDEKICK_WORK_READY_POLL=0.1
}

preflight_real() {
  local tool
  for tool in docker python3 od tr sed awk; do
    command -v "$tool" >/dev/null 2>&1 || { echo "drill: $tool is required" >&2; exit 2; }
  done
  if [ "$scenario" != work ] && [ "$local_images" = 0 ]; then
    command -v cosign >/dev/null 2>&1 || { echo "drill: cosign is required (update.sh verifies the signature, fail closed)" >&2; exit 2; }
  fi
  if [ "$scenario" != selfhost ]; then
    command -v openssl >/dev/null 2>&1 || { echo "drill: openssl is required (tools/work.sh)" >&2; exit 2; }
  fi
  docker compose version >/dev/null 2>&1 || { echo "drill: docker compose v2 is required" >&2; exit 2; }
}

if [ "$dry" = 1 ]; then
  write_fake_tools
else
  preflight_real
fi

# ---------------------------------------------------------------------------------------------------------
# Helpers

kv_set() { printf '%s' "$2" >"$TMP/kv/$1"; }
kv_get() { cat "$TMP/kv/$1"; }

rand_secret() { python3 -c 'import secrets, sys; print(secrets.token_urlsafe(int(sys.argv[1])))' "${1:-48}"; }
rand_hex() { python3 -c 'import secrets; print(secrets.token_hex(32))'; }
fernet_key() { python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())'; }

USED_PORTS=()
# Sets PICKED to a random port in 20000-39999 that is not reserved, not picked before and not listening on
# 127.0.0.1. Not run in a command substitution: USED_PORTS must survive the call.
PICKED=""
pick_port() {
  PICKED="$(drill_policy pick-port --reserved "${RESERVED_PORTS[*]}" --used "${USED_PORTS[*]-}")" || return 1
  USED_PORTS+=("$PICKED")
}

# The deploy files a scenario needs, without env files and secrets of the repository (a developer's own are never copied).
copy_selfhost_files() { # $1 = destination directory
  mkdir -p "$1"
  (cd "$REPO/deploy/selfhost" && find . -mindepth 1 -maxdepth 1 \
    ! -name '*.env' ! -name '*secrets' ! -name 'update-state' ! -name 'Caddyfile' ! -name '*.partial' \
    -exec cp -a {} "$1/" \;)
  cp "$1/Caddyfile.example" "$1/Caddyfile"
}

expect_eq() { # label actual expected
  if [ "$2" != "$3" ]; then
    echo "$1: expected '$3', got '$2'" >&2
    return 1
  fi
}

# The container image of a service of a compose project (a carrier with tar, sh and cat for volume files).
carrier_image() { # project service
  docker ps -a --filter "label=com.docker.compose.project=$1" --filter "label=com.docker.compose.service=$2" \
    --format '{{.Image}}' | sed -n 1p
}
hs_volume() { # project
  docker volume ls -q --filter "label=com.docker.compose.project=$1" \
    --filter "label=com.docker.compose.volume=hindsight_pg0" | sed -n 1p
}
hs_write() { # project carrier-service token
  local vol img
  vol="$(hs_volume "$1")"
  img="$(carrier_image "$1" "$2")"
  { [ -n "$vol" ] && [ -n "$img" ]; } || { echo "no Hindsight volume or carrier image" >&2; return 1; }
  docker run --rm --network none -v "$vol:/dst" --entrypoint sh "$img" -c "printf '%s' '$3' > /dst/drill-marker.txt"
}
hs_read() { # project carrier-service
  local vol img
  vol="$(hs_volume "$1")"
  img="$(carrier_image "$1" "$2")"
  { [ -n "$vol" ] && [ -n "$img" ]; } || { echo "no Hindsight volume or carrier image" >&2; return 1; }
  docker run --rm --network none -v "$vol:/src:ro" --entrypoint cat "$img" /src/drill-marker.txt
}

MARKER_SQL() { printf "CREATE TABLE public.drill_marker (token text PRIMARY KEY); INSERT INTO public.drill_marker VALUES ('%s');" "$1"; }

STEP_COUNT=0
STEP_OK=1
TIMINGS=() # "PASS|FAIL scenario/name seconds", in run order
# step SCENARIO NAME FUNCTION...: runs the function in a subshell with errexit, output to the log; sets STEP_OK.
# It must never be called from a condition (`step ... || x`, `if step ...`): bash would then ignore errexit inside the
# step and a failing command would not fail it.
step() {
  local scen="$1" name="$2" out="$TMP/step.out" rc errexit=0 started="$SECONDS" took
  shift 2
  STEP_COUNT=$((STEP_COUNT + 1))
  : >"$out"
  case $- in *e*) errexit=1 ;; esac
  set +e
  ( set -euo pipefail; "$@" ) >"$out" 2>&1 </dev/null
  rc=$?
  if [ "$errexit" = 1 ]; then set -e; fi
  took=$((SECONDS - started))
  { printf -- '--- %s/%s (exit %s, %ss)\n' "$scen" "$name" "$rc" "$took"; cat "$out"; } >>"$LOG"
  if [ "$rc" -eq 0 ]; then
    STEP_OK=1
    TIMINGS+=("PASS $scen/$name $took")
    say "PASS $scen/$name (${took}s)"
  else
    STEP_OK=0
    TIMINGS+=("FAIL $scen/$name $took")
    say "FAIL $scen/$name (exit $rc, ${took}s)"
    tail -n 15 "$out" | sed 's/^/    /'
    # A failed step names itself in the Actions run, so the log does not have to be opened to see which one broke.
    if [ "${GITHUB_ACTIONS:-}" = true ]; then
      printf '::error title=drill %s/%s failed::exit %s after %ss, see the drill log artifact\n' "$scen" "$name" "$rc" "$took"
    fi
  fi
}

# The durations, as text and (in GitHub Actions) as a table in the job summary.
report_timings() {
  local line status step took total=0
  [ "${#TIMINGS[@]}" -gt 0 ] || return 0
  say "TIMINGS (seconds):"
  for line in "${TIMINGS[@]}"; do
    read -r status step took <<<"$line"
    total=$((total + took))
    say "  $status $step $took"
  done
  say "  total $total"
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    {
      printf '### Drill steps\n\n| Step | Result | Seconds |\n| --- | --- | ---: |\n'
      for line in "${TIMINGS[@]}"; do
        read -r status step took <<<"$line"
        printf '| %s | %s | %s |\n' "$step" "$status" "$took"
      done
      printf '| total | | %s |\n' "$total"
    } >>"$GITHUB_STEP_SUMMARY"
  fi
}

# run_steps SCENARIO NAME:FUNCTION...: the steps in order, stopping at the first failure (return 1).
run_steps() {
  local scen="$1" pair
  shift
  for pair in "$@"; do
    step "$scen" "${pair%%:*}" "${pair#*:}"
    [ "$STEP_OK" = 1 ] || return 1
  done
}

# ---------------------------------------------------------------------------------------------------------
# --local-images: two api images built from this checkout, behind a throw-away registry, so that they have real digests
# (update.sh pulls by digest). The registry image is pinned by digest like every other image of the repository.

REGISTRY_IMAGE="registry:2@sha256:a3d8aaa63ed8681a604f1dea0aa03f100d5895b6a58ace528858a7b332415373"
REG_ADDR=""

# The signature step of update.sh needs a cosign that answers; a locally built image has no signature to verify. This
# stand-in only checks the shape of the call (verify, a local drill image, the drill identity and an issuer). The real
# signature check is the drill with released images.
write_cosign_standin() {
  cat >"$TMP/bin/cosign" <<SH
#!/usr/bin/env bash
[ "\${1:-}" = verify ] || exit 1
[[ "\${2:-}" =~ ^127\\.0\\.0\\.1:[0-9]+/sidekick@sha256:[0-9a-f]{64}\$ ]] || exit 1
shift 2
[ "\${1:-}" = --certificate-identity ] && [ "\${2:-}" = "$identity" ] || exit 1
[ "\${3:-}" = --certificate-oidc-issuer ] && [ -n "\${4:-}" ]
SH
  chmod 755 "$TMP/bin/cosign"
  export PATH="$TMP/bin:$PATH"
}

local_images_build() {
  local versions version next head min role ver tag out digest
  mkdir -p "$TMP/registry"
  printf 'services:\n  registry:\n    image: %s\n    ports:\n      - "127.0.0.1:%s:5000"\n' \
    "$REGISTRY_IMAGE" "${REG_ADDR##*:}" >"$TMP/registry/compose.yaml"
  docker compose -p "$REG_PROJECT" -f "$TMP/registry/compose.yaml" up -d --wait --wait-timeout 120
  for _ in $(seq 1 30); do
    if (exec 3<>"/dev/tcp/127.0.0.1/${REG_ADDR##*:}") 2>/dev/null; then break; fi
    sleep 1
  done
  # The release workflow's inputs, from the same files: the version of the source, the newest migration, the stepping stone.
  versions="$(drill_policy release-versions "$REPO/backend/pyproject.toml")"
  version="${versions% *}"
  next="${versions#* }"
  head="$(find "$REPO/migrations" -maxdepth 1 -name '[0-9]*.py' -printf '%f\n' | sort | tail -n 1)"
  head="${head%.py}"
  min="$(tr -d '[:space:]' <"$REPO/deploy/selfhost/min-upgrade-from.txt")"
  [ -n "$head" ] && [ -n "$min" ] || { echo "no migration or min-upgrade-from found" >&2; return 1; }
  for role in from to; do
    ver="$version"
    [ "$role" = to ] && ver="$next"
    tag="$REG_ADDR/sidekick:$role"
    echo "$tag" >>"$TMP/kv/local_refs" # removed again by cleanup
    docker build -q -f "$REPO/backend/Dockerfile" -t "$tag" \
      --build-arg SIDEKICK_MIGRATION_CLASS=expand --build-arg "SIDEKICK_SCHEMA_HEAD=$head" \
      --build-arg "SIDEKICK_MIN_UPGRADE_FROM=$min" --label "org.opencontainers.image.version=$ver" "$REPO" >/dev/null
    out="$(docker push "$tag" 2>&1)"
    digest="$(printf '%s\n' "$out" | drill_policy pushed-digest)" \
      || { printf '%s\n' "$out" >&2; echo "no digest from the push of $tag" >&2; return 1; }
    echo "$REG_ADDR/sidekick@$digest" >>"$TMP/kv/local_refs"
    kv_set "${role}_image" "$REG_ADDR/sidekick@$digest"
    echo "built $tag as version $ver: $REG_ADDR/sidekick@$digest"
  done
  [ "$(kv_get from_image)" != "$(kv_get to_image)" ] || { echo "both builds have the same digest" >&2; return 1; }
}

# ---------------------------------------------------------------------------------------------------------
# Scenario 1: the self-hosted stack with update.sh

# Shaped like the repository: update.sh finds tools/workctl two directories above itself.
SH_REPO="$TMP/selfhost"
SH_DIR="$SH_REPO/deploy/selfhost"
sh_compose() {
  docker compose -p "$SH_PROJECT" -f "$SH_DIR/compose.yaml" -f "$SH_DIR/drill.override.yaml" \
    --profile memory --env-file "$SH_DIR/selfhost.env" --env-file "$SH_DIR/release.env" "$@"
}
sh_psql() { sh_compose exec -T postgres psql -U postgres -d sidekick -v ON_ERROR_STOP=1 -Atc "$1"; }
sh_schema() { sh_psql "select count(*) from _yoyo_migration"; }
sh_head() { sh_psql "select migration_id from _yoyo_migration order by applied_at_utc desc, migration_id desc limit 1"; }
sh_update_sh() { bash "$SH_DIR/update.sh" -p "$SH_PROJECT" -f "$SH_DIR/compose.yaml" -f "$SH_DIR/drill.override.yaml" "$@"; }
# Encrypt or decrypt stdin with the key of selfhost.env (the container's env_file), the way update.sh does.
sh_crypto() { sh_compose run --rm -T --no-deps api python -I -c "$(cat "$SH_DIR/snapshot_crypto.py")" "$1"; }
# The same with another key (wrong or empty), given through the environment, never on a command line.
sh_crypto_key() { # key mode
  SIDEKICK_BACKUP_ENCRYPTION_KEY="$1" sh_compose run --rm -T --no-deps -e SIDEKICK_BACKUP_ENCRYPTION_KEY api \
    python -I -c "$(cat "$SH_DIR/snapshot_crypto.py")" "$2"
}

sh_install() {
  local app mig pg db_key uuid tenant
  copy_selfhost_files "$SH_DIR"
  mkdir -p "$SH_REPO/tools"
  cp -R "$REPO/tools/workctl" "$SH_REPO/tools/workctl"
  find "$SH_REPO/tools/workctl" -name __pycache__ -prune -exec rm -rf {} +
  app="$(rand_hex)"; mig="$(rand_hex)"; pg="$(rand_hex)"; db_key="$(fernet_key)"; tenant="$(rand_secret)"
  kv_set sh_backup_key "$db_key"
  kv_set sh_tenant "$tenant"
  {
    printf 'POSTGRES_PASSWORD=%s\nSIDEKICK_DB_APP_PASSWORD=%s\nSIDEKICK_DB_MIGRATOR_PASSWORD=%s\n' "$pg" "$app" "$mig"
    printf 'SIDEKICK_MIGRATION_DATABASE_URL=postgresql+psycopg://sidekick_migrator:%s@postgres:5432/sidekick\n' "$mig"
  } >"$SH_DIR/db.env"
  write_selfhost_env "$app" "$db_key" "00000000-0000-4000-8000-000000000000" "$tenant"
  printf 'SIDEKICK_API_IMAGE=%s\n' "$from_image" >"$SH_DIR/release.env"
  printf 'services:\n  api:\n    ports: !override\n      - "127.0.0.1:%s:8000"\n' "$SH_PORT" >"$SH_DIR/drill.override.yaml"
  write_hindsight_env "$tenant"
  chmod 600 "$SH_DIR"/*.env
  [ "$dry" = 1 ] || docker pull "$from_image" >/dev/null
  # README, "First start" step 3: the owner is created before the identity line can name it.
  uuid="$(sh_compose run --rm -T api sidekick-admin create-user --login drill --display-name Drill | tail -n 1)"
  [[ "$uuid" =~ ^[0-9a-fA-F-]{36}$ ]] || { echo "create-user did not print a UUID" >&2; return 1; }
  write_selfhost_env "$app" "$db_key" "$uuid" "$tenant"
  sh_compose up -d --wait --wait-timeout 300
  echo "installed $from_image on 127.0.0.1:$SH_PORT"
}

# The memory profile of the guide, with the real Hindsight container and a model address that goes nowhere: it starts
# and keeps its volume, which is all the drill needs of it. The worker idles (SIDEKICK_MEMORY_ENABLED=false).
write_hindsight_env() { # tenant-key
  {
    printf 'HINDSIGHT_API_LLM_PROVIDER=openai\nHINDSIGHT_API_LLM_BASE_URL=http://model.drill.invalid:8000/v1\n'
    printf 'HINDSIGHT_API_LLM_MODEL=drill-model\nHINDSIGHT_API_LLM_API_KEY=not-needed\n'
    printf 'HINDSIGHT_API_ENABLE_OBSERVATIONS=false\nHINDSIGHT_API_RETAIN_CHUNK_SIZE=3000\n'
    printf 'HINDSIGHT_API_RETAIN_MAX_COMPLETION_TOKENS=4000\n'
    printf 'HINDSIGHT_API_EMBEDDINGS_PROVIDER=local\nHINDSIGHT_API_RERANKER_PROVIDER=local\n'
    printf 'HINDSIGHT_API_TENANT_API_KEY=%s\n' "$1"
  } >"$SH_DIR/hindsight.env"
}

write_selfhost_env() { # app-password backup-key owner-uuid tenant-key
  {
    printf 'SELFHOST_DOMAIN=drill.invalid\nSIDEKICK_ENVIRONMENT=production\n'
    printf 'SIDEKICK_DATABASE_URL=postgresql+psycopg://sidekick_app:%s@postgres:5432/sidekick\n' "$1"
    printf 'SIDEKICK_CURSOR_SIGNING_SECRET=%s\nSIDEKICK_TOKEN_PEPPER=%s\n' "$(rand_secret)" "$(rand_secret)"
    printf 'SIDEKICK_MCP_AUTH_MODE=github_oauth\nSIDEKICK_MCP_PUBLIC_BASE_URL=https://drill.invalid\n'
    printf 'SIDEKICK_MCP_OAUTH_GITHUB_CLIENT_ID=drill-client-id\nSIDEKICK_MCP_OAUTH_GITHUB_CLIENT_SECRET=%s\n' "$(rand_secret)"
    printf 'SIDEKICK_MCP_OAUTH_SIGNING_KEY=%s\nSIDEKICK_MCP_OAUTH_STORAGE_DIR=/var/lib/sidekick/oauth-storage\n' "$(rand_secret)"
    printf 'SIDEKICK_MCP_OAUTH_ALLOWED_IDENTITIES=github:1=%s\n' "$3"
    printf 'SIDEKICK_MCP_OAUTH_SCOPES=projects:read,tasks:read,contacts:read,shopping:read\n'
    printf 'SIDEKICK_MEMORY_ENABLED=false\nSIDEKICK_MEMORY_PROVIDER=hindsight\nSIDEKICK_BACKUP_ENABLED=false\n'
    printf 'SIDEKICK_MEMORY_HINDSIGHT_BASE_URL=http://hindsight:8888\nSIDEKICK_MEMORY_HINDSIGHT_API_TOKEN=%s\n' "$4"
    printf 'SIDEKICK_MEMORY_ID_DERIVATION_KEY=%s\n' "$(rand_secret)"
    printf 'SIDEKICK_BACKUP_ENCRYPTION_KEY=%s\n' "$2"
  } >"$SH_DIR/selfhost.env.tmp"
  mv "$SH_DIR/selfhost.env.tmp" "$SH_DIR/selfhost.env"
}

sh_marker() {
  local token
  token="drill-$(rand_hex8)"
  kv_set sh_marker "$token"
  kv_set sh_hs "$token-hs"
  sh_psql "$(MARKER_SQL "$token")" >/dev/null
  expect_eq "marker row" "$(sh_psql "select token from public.drill_marker")" "$token"
  hs_write "$SH_PROJECT" hindsight "$token-hs"
  expect_eq "Hindsight volume file" "$(hs_read "$SH_PROJECT" hindsight)" "$token-hs"
  kv_set sh_schema_before "$(sh_schema)"
  kv_set sh_head_before "$(sh_head)"
}

sh_update() {
  [ "$dry" = 1 ] || docker pull "$to_image" >/dev/null
  sh_update_sh --apply --image "$to_image" --cert-identity "$identity"
  expect_eq "update journal" "$(tail -n 1 "$SH_DIR/update-state/journal.log" | awk '{print $2}')" DONE
  grep -qx "SIDEKICK_API_IMAGE=$to_image" "$SH_DIR/release.env" || { echo "release.env does not pin the new image" >&2; return 1; }
}

sh_verify_updated() {
  local before after snapshot
  expect_eq "marker row after update" "$(sh_psql "select token from public.drill_marker")" "$(kv_get sh_marker)"
  expect_eq "Hindsight volume file after update" "$(hs_read "$SH_PROJECT" hindsight)" "$(kv_get sh_hs)"
  before="$(kv_get sh_schema_before)"
  after="$(sh_schema)"
  kv_set sh_schema_after "$after"
  if [ "$after" -gt "$before" ]; then
    echo "schema moved: $before -> $after migrations ($(kv_get sh_head_before) -> $(sh_head))"
  elif [ "$allow_same_schema" = 1 ]; then
    echo "schema unchanged ($after migrations), accepted by --allow-same-schema"
  else
    echo "schema did not move ($before -> $after); the new image has no migration the old one lacked (--allow-same-schema)" >&2
    return 1
  fi
  # The pre-update snapshot update.sh took must decrypt and still list the marker table.
  snapshot="$(ls -1 "$SH_DIR"/update-state/snapshots/sidekick-pre-*.dump.enc | sed -n 1p)"
  [ -s "$snapshot" ] || { echo "no pre-update snapshot" >&2; return 1; }
  sh_update_sh --decrypt-snapshot "$snapshot" >"$TMP/pre-update.dump"
  [ -s "$TMP/pre-update.dump" ] || { echo "snapshot decrypted to nothing" >&2; return 1; }
  sh_compose exec -T postgres pg_restore -l <"$TMP/pre-update.dump" | grep drill_marker >/dev/null
  rm -f "$TMP/pre-update.dump"
}

sh_backup() {
  local dir="$SH_DIR/drill-backups"
  local img vol file
  mkdir -p "$dir"
  sh_compose exec -T postgres pg_dump -U postgres -d sidekick -Fc | sh_crypto encrypt >"$dir/sidekick.dump.enc"
  # The guide's archive: Hindsight stopped for the copy, the volume tarred by a one-off container of its image.
  img="$(carrier_image "$SH_PROJECT" hindsight)"
  vol="$(hs_volume "$SH_PROJECT")"
  sh_compose stop hindsight
  docker run --rm --network none -v "$vol:/src:ro" --entrypoint tar "$img" -C /src -czf - . \
    | sh_crypto encrypt >"$dir/hindsight.tar.gz.enc"
  sh_compose up -d --wait --wait-timeout 300 hindsight
  for file in "$dir"/sidekick.dump.enc "$dir"/hindsight.tar.gz.enc; do
    [ -s "$file" ] || { echo "empty backup file" >&2; return 1; }
    expect_eq "backup format" "$(sed -n 1p "$file")" "SIDEKICK-SNAPSHOT-1"
    if grep -a "$(kv_get sh_marker)" "$file" >/dev/null; then echo "the backup holds the marker in clear" >&2; return 1; fi
  done
  # A fresh restore must work from this set alone: the key file of selfhost.env is the only secret needed.
  expect_eq "decrypt round trip" "$(sh_crypto decrypt <"$dir/hindsight.tar.gz.enc" | tar -tz | grep -c drill-marker.txt)" 1
}

sh_destroy() {
  sh_compose down -v --remove-orphans
  expect_eq "volumes left after down -v" "$(docker volume ls -q --filter "label=com.docker.compose.project=$SH_PROJECT" | wc -l | tr -d ' ')" 0
}

sh_key_closed() {
  local file="$SH_DIR/drill-backups/sidekick.dump.enc" out
  if out="$(sh_crypto_key "$(fernet_key)" decrypt <"$file")"; then echo "a wrong key decrypted the backup" >&2; return 1; fi
  expect_eq "output with a wrong key" "$out" ""
  if out="$(sh_crypto_key "" decrypt <"$file")"; then echo "an empty key decrypted the backup" >&2; return 1; fi
  expect_eq "output with an empty key" "$out" ""
}

sh_restore() {
  local dir="$SH_DIR/drill-backups" img vol
  sh_compose up -d --wait --wait-timeout 300 postgres hindsight
  if sh_psql "select token from public.drill_marker" >/dev/null 2>&1; then
    echo "the marker exists on a fresh volume; the drill would prove nothing" >&2
    return 1
  fi
  sh_crypto decrypt <"$dir/sidekick.dump.enc" >"$TMP/restore.dump"
  [ -s "$TMP/restore.dump" ] || { echo "empty dump" >&2; return 1; }
  sh_compose exec -T postgres pg_restore -U postgres -d sidekick --exit-on-error --single-transaction <"$TMP/restore.dump"
  rm -f "$TMP/restore.dump"
  # The guide: stop Hindsight, empty the volume, unpack the archive, start it.
  img="$(carrier_image "$SH_PROJECT" hindsight)"
  vol="$(hs_volume "$SH_PROJECT")"
  if hs_read "$SH_PROJECT" hindsight >/dev/null 2>&1; then
    echo "the Hindsight marker file exists on a fresh volume; the drill would prove nothing" >&2
    return 1
  fi
  sh_compose stop hindsight
  sh_crypto decrypt <"$dir/hindsight.tar.gz.enc" | docker run --rm -i --network none \
    -v "$vol:/dst" --entrypoint sh "$img" -c 'find /dst -mindepth 1 -delete && tar -C /dst -xzf -'
  sh_compose run --rm -T --no-deps migrate
  sh_compose up -d --wait --wait-timeout 300
}

sh_verify_restored() {
  expect_eq "marker row after restore" "$(sh_psql "select token from public.drill_marker")" "$(kv_get sh_marker)"
  expect_eq "Hindsight volume file after restore" "$(hs_read "$SH_PROJECT" hindsight)" "$(kv_get sh_hs)"
  expect_eq "schema version after restore" "$(sh_schema)" "$(kv_get sh_schema_after)"
}

scenario_selfhost() {
  pick_port
  SH_PORT="$PICKED"
  if [ "$dry" = 1 ]; then rm -f "$DRILL_FAKE_STATE"; fi
  PROJECTS+=("$SH_PROJECT")
  export COMPOSE_PROJECT_NAME="$SH_PROJECT"
  say "selfhost: project $SH_PROJECT, api on 127.0.0.1:$SH_PORT"
  run_steps selfhost install:sh_install marker:sh_marker update:sh_update verify-updated:sh_verify_updated \
    backup:sh_backup destroy-volumes:sh_destroy key-fails-closed:sh_key_closed restore:sh_restore \
    verify-restored:sh_verify_restored
}

# ---------------------------------------------------------------------------------------------------------
# Scenario 2: the work package with tools/work.sh

WK_REPO="$TMP/work/repo"
WK_ENV="$WK_REPO/deploy/work/work.env"
wk() { (cd "$WK_REPO" && SIDEKICK_WORK_PROJECT="$WK_PROJECT" SIDEKICK_WORK_LANG=en bash tools/work.sh "$@"); }
wk_pg() {
  local cid
  cid="$(docker ps -q --filter "label=com.docker.compose.project=$WK_PROJECT" --filter "label=com.docker.compose.service=postgres" | sed -n 1p)"
  [ -n "$cid" ] || { echo "no postgres container" >&2; return 1; }
  docker exec "$cid" psql -U postgres -d sidekick -v ON_ERROR_STOP=1 -Atc "$1"
}
wk_schema() { wk_pg "select count(*) from _yoyo_migration"; }
wk_set_image() {
  { grep -v '^SIDEKICK_WORK_API_IMAGE=' "$WK_ENV" || true; printf 'SIDEKICK_WORK_API_IMAGE=%s\n' "$1"; } >"$WK_ENV.tmp"
  mv "$WK_ENV.tmp" "$WK_ENV"
}

wk_install() {
  mkdir -p "$WK_REPO/tools" "$WK_REPO/deploy/work"
  cp "$REPO/tools/work.sh" "$WK_REPO/tools/work.sh"
  # work.sh delegates its logic to the standard-library package tools/workctl.
  cp -R "$REPO/tools/workctl" "$WK_REPO/tools/workctl"
  find "$WK_REPO/tools/workctl" -name __pycache__ -prune -exec rm -rf {} +
  copy_selfhost_files "$WK_REPO/deploy/selfhost"
  cp "$REPO/deploy/work/compose.yaml" "$REPO/deploy/work/gateway.haproxy.cfg" "$REPO/deploy/work/work.env.example" "$WK_REPO/deploy/work/"
  {
    printf 'SIDEKICK_WORK_MODEL_BASE_URL=http://model.drill.invalid:8000/v1\nSIDEKICK_WORK_MEMORY_MODEL=drill-model\n'
    printf 'SIDEKICK_WORK_INSTANCE_LABEL=Sidekick Drill\nSIDEKICK_WORK_LOCALE=en\nSIDEKICK_WORK_TIMEZONE=UTC\n'
    printf 'SIDEKICK_WORK_PORT=%s\nSIDEKICK_ENABLED_ROOMS=work\nSIDEKICK_WORK_API_IMAGE=%s\n' "$WK_PORT" "$from_image"
  } >"$WK_ENV"
  chmod 600 "$WK_ENV"
  [ "$dry" = 1 ] || docker pull "$from_image" >/dev/null
  wk init
  wk start
  echo "installed $from_image, gateway on 127.0.0.1:$WK_PORT"
}

wk_marker() {
  local token
  token="drill-$(rand_hex8)"
  kv_set wk_marker "$token"
  kv_set wk_hs "$token-hs"
  wk_pg "$(MARKER_SQL "$token")" >/dev/null
  expect_eq "marker row" "$(wk_pg "select token from public.drill_marker")" "$token"
  hs_write "$WK_PROJECT" hindsight "$token-hs"
  expect_eq "Hindsight volume file" "$(hs_read "$WK_PROJECT" hindsight)" "$token-hs"
  kv_set wk_schema_before "$(wk_schema)"
}

wk_update() {
  # What `work.sh update` does first: a backup of the database and the memory. The code route (git pull, build) is
  # replaced by the released image: the new image goes into work.env and `start` recreates the stack, which reruns the migrator.
  wk backup
  [ "$dry" = 1 ] || docker pull "$to_image" >/dev/null
  wk_set_image "$to_image"
  wk start
}

wk_verify_updated() {
  local before after
  expect_eq "marker row after update" "$(wk_pg "select token from public.drill_marker")" "$(kv_get wk_marker)"
  expect_eq "Hindsight volume file after update" "$(hs_read "$WK_PROJECT" hindsight)" "$(kv_get wk_hs)"
  before="$(kv_get wk_schema_before)"
  after="$(wk_schema)"
  kv_set wk_schema_after "$after"
  if [ "$after" -gt "$before" ]; then
    echo "schema moved: $before -> $after migrations"
  elif [ "$allow_same_schema" = 1 ]; then
    echo "schema unchanged ($after migrations), accepted by --allow-same-schema"
  else
    echo "schema did not move ($before -> $after) (--allow-same-schema)" >&2
    return 1
  fi
}

wk_backup() {
  local db mem ts
  wk backup
  db="$(ls -1 "$WK_REPO"/deploy/work/backups/sidekick-*.sql.enc | tail -n 1)"
  ts="${db##*/sidekick-}"; ts="${ts%.sql.enc}"
  mem="$WK_REPO/deploy/work/backups/hindsight-$ts.tar.gz.enc"
  kv_set wk_ts "$ts"
  local file
  for file in "$db" "$mem"; do
    [ -s "$file" ] || { echo "missing or empty $file" >&2; return 1; }
    expect_eq "backup format" "$(sed -n 1p "$file")" "SIDEKICK-SNAPSHOT-1"
    if grep -a "$(kv_get wk_marker)" "$file" >/dev/null; then echo "a backup holds the marker in clear" >&2; return 1; fi
  done
  [ -s "$WK_REPO/deploy/work/secrets/backup.key" ] || { echo "no backup key" >&2; return 1; }
  fernet_key >"$TMP/wrong.key"
}

wk_destroy() {
  docker compose -p "$WK_PROJECT" down -v --remove-orphans
  expect_eq "volumes left after down -v" "$(docker volume ls -q --filter "label=com.docker.compose.project=$WK_PROJECT" | wc -l | tr -d ' ')" 0
}

wk_fresh() {
  wk start
  if wk_pg "select token from public.drill_marker" >/dev/null 2>&1; then
    echo "the marker exists on a fresh stack; the drill would prove nothing" >&2
    return 1
  fi
}

wk_key_closed() {
  local ts rc
  ts="$(kv_get wk_ts)"
  rc=0
  SIDEKICK_WORK_BACKUP_KEY_FILE="$TMP/wrong.key" wk restore "$ts" || rc=$?
  [ "$rc" -ne 0 ] || { echo "restore accepted a wrong key" >&2; return 1; }
  rc=0
  SIDEKICK_WORK_BACKUP_KEY_FILE="$TMP/no-such.key" wk restore "$ts" || rc=$?
  [ "$rc" -ne 0 ] || { echo "restore went on without a key" >&2; return 1; }
  if wk_pg "select token from public.drill_marker" >/dev/null 2>&1; then
    echo "a refused restore changed the database" >&2
    return 1
  fi
}

wk_restore() {
  printf '%s\n' "$WK_PROJECT" | wk restore "$(kv_get wk_ts)" --apply
}

wk_verify_restored() {
  expect_eq "marker row after restore" "$(wk_pg "select token from public.drill_marker")" "$(kv_get wk_marker)"
  expect_eq "Hindsight volume file after restore" "$(hs_read "$WK_PROJECT" hindsight)" "$(kv_get wk_hs)"
  expect_eq "owner user after restore" "$(wk_pg "select count(*) from sidekick.users where username = 'jobb'")" 1
  expect_eq "schema version after restore" "$(wk_schema)" "$(kv_get wk_schema_after)"
}

scenario_work() {
  pick_port
  WK_PORT="$PICKED"
  if [ "$dry" = 1 ]; then rm -f "$DRILL_FAKE_STATE"; fi
  PROJECTS+=("$WK_PROJECT")
  export COMPOSE_PROJECT_NAME="$WK_PROJECT"
  say "work: project $WK_PROJECT, gateway on 127.0.0.1:$WK_PORT"
  run_steps work install:wk_install marker:wk_marker update:wk_update verify-updated:wk_verify_updated \
    backup:wk_backup destroy-volumes:wk_destroy fresh-stack:wk_fresh key-fails-closed:wk_key_closed \
    restore:wk_restore verify-restored:wk_verify_restored
}

# ---------------------------------------------------------------------------------------------------------

FAILED=()
PASSED=()
# The scenario runs as a plain command (not in a condition), so that errexit stays in force inside its steps.
run_scenario() {
  local rc
  set +e
  "scenario_$1"
  rc=$?
  set -e
  if [ "$rc" -eq 0 ]; then PASSED+=("$1"); else FAILED+=("$1"); fi
}

if [ "$dry" = 1 ]; then say "drill: DRY RUN with a fake docker; nothing real is started"; fi
case "$scenario" in
  selfhost) planned="$SH_PROJECT" ;;
  work) planned="$WK_PROJECT" ;;
  *) planned="$SH_PROJECT $WK_PROJECT" ;;
esac
if [ "$local_images" = 1 ]; then planned="$REG_PROJECT $planned"; fi
say "drill: projects ${planned}; reserved ports: ${RESERVED_PORTS[*]}"

if [ "$local_images" = 1 ]; then
  say "drill: --local-images: the signature is NOT verified (cosign is a stand-in); released images are needed for that"
  write_cosign_standin
  pick_port
  REG_ADDR="127.0.0.1:$PICKED"
  PROJECTS+=("$REG_PROJECT")
  step setup local-images local_images_build
  if [ "$STEP_OK" != 1 ]; then
    report_timings
    say "SUMMARY: FAIL (the local images could not be built)"
    exit 1
  fi
  from_image="$(kv_get from_image)"
  to_image="$(kv_get to_image)"
fi
case "$scenario" in
  selfhost) run_scenario selfhost ;;
  work) run_scenario work ;;
  all)
    run_scenario selfhost
    run_scenario work
    ;;
esac

if [ "${#FAILED[@]}" -eq 0 ]; then
  say "SUMMARY: PASS ($STEP_COUNT steps; scenarios: ${PASSED[*]})"
  report_timings
  exit 0
fi
say "SUMMARY: FAIL (failed scenarios: ${FAILED[*]}; passed: ${PASSED[*]-none})"
report_timings
exit 1
