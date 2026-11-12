#!/usr/bin/env bash
# Update a self-hosted Sidekick installation to a signed, digest-pinned api image.
#
# Default is --dry-run: the script only inspects local files and prints what --apply would do.
# It calls neither docker nor the network in that mode. --apply needs an explicit --image
# <registry/repo@sha256:digest>; a tag alone is refused.
# --check is read-only too, but does call docker and cosign: current pinned digest, signature
# status and schema head (image label versus applied migrations). It changes nothing.
# --decrypt-snapshot FILE writes a decrypted snapshot to stdout (for pg_restore); see below.
#
# Order of --apply (steps 1 and 2 leave the running installation untouched):
#   1 verify the cosign signature of the exact digest        (fail closed: no cosign = refuse)
#   2 pull the new digest, read its migration-class label, and check the upgrade path: the version of the INSTALLED
#     image (label org.opencontainers.image.version of the running api image) must be at least the new image's
#     io.sidekick.min-upgrade-from label (and not newer than the new version). A jump that skips a stepping-stone
#     release, or an installed/new version that cannot be determined, is refused with instructions.
#   3 stop api and every running Sidekick worker (WORKERS below); the database stays up. If the state of a worker
#     cannot be determined (compose ps fails) the update aborts before anything is stopped. Workers are found by any
#     status (running, restarting, paused, created with a restart policy), and after the stop the script checks that
#     no writer runs or restarts any more (else ABORTED before the backup). From here a failure
#     before the migration starts the previous image and workers again (journal ABORTED).
#     Before anything is stopped (step 3) the snapshot directory must have room for another snapshot: at least the
#     size of the newest finished snapshot times SIDEKICK_BACKUP_SPACE_MARGIN_PCT (default 150, at least 100), and at
#     least SIDEKICK_BACKUP_SPACE_FLOOR_MB (default 64). Otherwise the update is refused (ABORTED, nothing touched).
#   4 with every writer stopped, so that no confirmed write is missed: encrypted owner backup with the CURRENT image
#     (existing sidekick-backup-worker), then a pg_dump snapshot of the whole database, ENCRYPTED (the only way
#     back from a bad migration)
#   5 run the explicit migrator, start api and the workers that were running with the new digest
#   6 wait for readiness inside the api container (READINESS_PY, the same code as the compose healthcheck): the
#     running api process answers HTTP (2xx, or the intended 404), and the database answers with the schema at the revision the image expects.
#     An older image without the readiness module is judged by the HTTP answer alone, so a rollback to it passes.
#     Every worker that was started with the api must also be running and, where compose declares a healthcheck,
#     healthy (docker inspect); a worker that never gets there fails this step like the api and triggers step 7.
#   7 on failure: roll back to the previous digest only if the previous image is known to work
#     against the new schema; otherwise leave api stopped and print the restore steps.
# The database is never rolled back automatically. Secrets are never printed.
#
# Interrupts: SIGINT, SIGTERM, SIGHUP and any unexpected exit of --apply run the same recovery as a failed step
# (fail_apply): before the migration the previous image and the workers are started again (ABORTED); after it the
# rollback rules of step 7 apply. The lock is an flock held for the whole run (two runs can never overlap, and a
# lock someone else holds is never touched; the kernel drops it when its holder dies). A half-written snapshot
# (*.partial) and release.env.tmp are removed, and release.env and the journal are only ever replaced by an atomic rename (temporary file in the same directory, flushed; directory flushed after the rename). SIGKILL or
# a power loss cannot be trapped: the next --apply resumes when the journal ends in STARTED, STOPPING_WRITERS or
# RESUMING (the migration had not begun). It reads that recovery state BEFORE the pre-checks: the journal carries the
# list of workers that were stopped (kept on every journal line until a restart has succeeded), and a failing
# pre-check or an interrupt of the resumed run starts api and exactly those workers again. Any later state
# (MIGRATING, ROLLING_BACK, NEEDS_*) still needs a manual decision.
#
# Snapshot encryption: pg_dump output is piped through a one-off api container (same image the
# installation already runs, so no new tool for the customer) that encrypts it with Fernet using
# SIDEKICK_BACKUP_ENCRYPTION_KEY, the same key as the owner backups. The key reaches the container
# through compose's env_file (selfhost.env) or as a secret file (SELFHOST_BACKUP_ENCRYPTION_KEY_FILE, see
# secrets-to-files.sh), never through a command line, and is never printed.
# Fernet is not a streaming format: the dump is held in memory once (fine for a personal
# installation; snapshot_crypto.py refuses a dump over 512 MiB with an explicit message, and a larger
# database needs a streaming scheme, not provided). openssl is not in the
# postgres image and gpg/age would be a new customer-side dependency, hence Fernet.
# File format: "SIDEKICK-SNAPSHOT-1\n" followed by one Fernet token.
# The code for both directions is snapshot_crypto.py (kept next to this script; tools/work.sh uses the same file),
# so the format exists in one place only.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# Free-space check and safe pruning, shared with tools/work.sh.
# shellcheck source=backup_space.sh
. "$SCRIPT_DIR/backup_space.sh"
COMPOSE_FILE="$SCRIPT_DIR/compose.yaml"
# -f/--compose-file (repeatable) replaces the default compose.yaml, exactly like docker compose -f.
# -p/--project-name is passed to docker compose; without it compose derives the name as usual
# (COMPOSE_PROJECT_NAME in the environment is honoured too).
COMPOSE_FILES=()
PROJECT_NAME=""
ENV_FILE="$SCRIPT_DIR/selfhost.env"
RELEASE_FILE="$SCRIPT_DIR/release.env"
STATE_DIR="$SCRIPT_DIR/update-state"
JOURNAL="$STATE_DIR/journal.log"
LOCK_FILE="$STATE_DIR/update.lock" # flock target, never deleted
LOCK_PID_FILE="$STATE_DIR/update.lock.pid" # informational: pid of the run that holds LOCK_FILE
DEFAULT_ISSUER="https://token.actions.githubusercontent.com"
HEALTH_TIMEOUT="${SIDEKICK_UPDATE_HEALTH_TIMEOUT:-180}"
IMAGE_RE='^[a-z0-9][a-z0-9._:/-]*@sha256:[0-9a-f]{64}$'
LABEL_CLASS="io.sidekick.migration-class"
LABEL_VERSION="org.opencontainers.image.version"
LABEL_MIN_FROM="io.sidekick.min-upgrade-from"
VERSION_RE='^[0-9]+\.[0-9]+\.[0-9]+$'
# Every Sidekick worker that runs from the api image, as "profile:service" (see compose.yaml; an empty profile
# means the service runs by default, with no profile). This is the one
# list the updater uses to find which are running, stop them before the migration, start them again with the new
# (or, on rollback, the previous) image and keep them stopped when a manual restore is needed. A new worker
# service in compose.yaml is added here and nowhere else. ntfy, caddy and hindsight are other images, not touched
# (start_api only recreates a running caddy, so that it picks up the current network configuration).
WORKERS=(":automation-worker" "backup:backup" "push:push" "memory:memory-worker")
# Run inside the api container; exit 0 = ready. The api healthcheck in compose.yaml holds the same code (a test
# keeps them equal). 1) The running api process must answer HTTP within 3 s: 2xx, or the intended 404 (the public
# surface hides /health/* in github_oauth mode); any other status (500, 503, ...) or a hung process fails. 2) If this image has the readiness
# module, the database must answer and the schema must be at the image's revision. An older image has no such
# module and is judged by 1) alone, so rolling back to it is not refused.
# shellcheck disable=SC2016
READINESS_PY='import importlib.util, sys, urllib.error, urllib.request
try:
    urllib.request.urlopen("http://127.0.0.1:8000/health/live", timeout=3)
except urllib.error.HTTPError as error:
    if error.code != 404:
        sys.exit(1)
except Exception:
    sys.exit(1)
if importlib.util.find_spec("sidekick.shared.readiness") is None:
    sys.exit(0)
from sidekick.shared.readiness import main
main()'

die() {
  echo "update.sh: $*" >&2
  exit 1
}

usage() {
  cat >&2 <<'EOF'
usage: update.sh [-p NAME] [-f FILE]... [--dry-run] [--apply --image REF@sha256:DIGEST --cert-identity ID] [options]

  -p, --project-name NAME         compose project name (default: compose's own, or COMPOSE_PROJECT_NAME)
  -f, --compose-file FILE         compose file, repeatable, used instead of the default compose.yaml
                                  (give compose.yaml first when adding an override file)
  --dry-run                       default: print the plan, change nothing, call nothing
  --check                         read-only status: current digest, signature, schema head
  --decrypt-snapshot FILE         decrypt an update-state snapshot to stdout (redirect to a file)
  --apply                         perform the update (needs --image and --cert-identity)
  --image REF@sha256:DIGEST       new api image, pinned by digest (a tag alone is refused)
  --cert-identity ID              exact signer identity expected in the signature
                                  (or env SIDEKICK_RELEASE_CERT_IDENTITY); no default; see README.md, "Update"
  --cert-issuer URL               OIDC issuer (default https://token.actions.githubusercontent.com)
  --allow-unknown-migration-class accept an image without the io.sidekick.migration-class label
  --allow-breaking-migration      accept class "breaking"; failure then needs a manual restore
  --allow-unknown-version         proceed although the installed or new version, or the new image's
                                  min-upgrade-from, cannot be determined (never overrides a refused jump)
EOF
  exit 2
}

mode="dry-run"
snapshot_in=""
image=""
identity="${SIDEKICK_RELEASE_CERT_IDENTITY:-}"
issuer="$DEFAULT_ISSUER"
allow_unknown=0
allow_breaking=0
allow_unknown_version=0
while [ $# -gt 0 ]; do
  case "$1" in
    -p | --project-name)
      [ $# -ge 2 ] || usage
      PROJECT_NAME="$2"
      shift 2
      ;;
    -f | --compose-file)
      [ $# -ge 2 ] || usage
      COMPOSE_FILES+=("$2")
      shift 2
      ;;
    --dry-run)
      mode="dry-run"
      shift
      ;;
    --apply)
      mode="apply"
      shift
      ;;
    --check)
      mode="check"
      shift
      ;;
    --decrypt-snapshot)
      [ $# -ge 2 ] || usage
      mode="decrypt"
      snapshot_in="$2"
      shift 2
      ;;
    --image)
      [ $# -ge 2 ] || usage
      image="$2"
      shift 2
      ;;
    --cert-identity)
      [ $# -ge 2 ] || usage
      identity="$2"
      shift 2
      ;;
    --cert-issuer)
      [ $# -ge 2 ] || usage
      issuer="$2"
      shift 2
      ;;
    --allow-unknown-migration-class)
      allow_unknown=1
      shift
      ;;
    --allow-breaking-migration)
      allow_breaking=1
      shift
      ;;
    --allow-unknown-version)
      allow_unknown_version=1
      shift
      ;;
    -h | --help)
      usage
      ;;
    *)
      echo "update.sh: unknown argument" >&2
      usage
      ;;
  esac
done

if [ "${#COMPOSE_FILES[@]}" -eq 0 ]; then
  COMPOSE_FILES=("$COMPOSE_FILE")
fi

# --- shared helpers (local only) -------------------------------------------------------------

read_pin() { # prints the value of $1 from release.env, or nothing
  [ -f "$RELEASE_FILE" ] || return 0
  sed -n "s/^$1=\\(.*\\)\$/\\1/p" "$RELEASE_FILE" | tail -n 1
}

current_pin="$(read_pin SIDEKICK_API_IMAGE)"
if [ -n "$current_pin" ] && ! [[ "$current_pin" =~ $IMAGE_RE ]]; then
  die "release.env holds an unexpected SIDEKICK_API_IMAGE value; fix or remove it first"
fi
previous_ref="${current_pin:-roadlake-sidekick:selfhost}" # what compose resolves today when nothing is pinned

last_journal_state() {
  [ -f "$JOURNAL" ] || return 0
  tail -n 1 "$JOURNAL" | awk '{print $2}'
}

image_label() { # $1 = image ref or id, $2 = label; prints the value, or nothing when absent/unknown
  local value
  value="$(docker image inspect -f "{{ index .Config.Labels \"$2\" }}" "$1" 2>/dev/null || true)"
  case "$value" in
    "<no value>" | unknown) value="" ;;
  esac
  printf '%s\n' "$value"
}

installed_image_ref() { # the image the api container actually runs, else what compose resolves today
  local cid ref=""
  cid="$(compose ps -q api 2>/dev/null || true)"
  if [ -n "$cid" ]; then
    ref="$(docker inspect -f '{{.Image}}' "$cid" 2>/dev/null || true)"
  fi
  printf '%s\n' "${ref:-$previous_ref}"
}

version_lt() { # $1 < $2 for plain X.Y.Z versions
  local -a a b
  local i
  IFS=. read -r -a a <<<"$1"
  IFS=. read -r -a b <<<"$2"
  for i in 0 1 2; do
    if ((10#${a[i]} < 10#${b[i]})); then return 0; fi
    if ((10#${a[i]} > 10#${b[i]})); then return 1; fi
  done
  return 1
}

# Sets compat_kind (ok | unknown | refused) and compat_message for installed=$1, new=$2, minimum upgrade-from=$3.
compat_kind="ok"
compat_message=""
check_upgrade_path() {
  local installed="$1" new="$2" min_from="$3"
  compat_kind="ok"
  compat_message=""
  if ! [[ "$installed" =~ $VERSION_RE ]]; then
    compat_kind="unknown"
    compat_message="the installed version cannot be determined (the running image has no valid $LABEL_VERSION label; a local build or a pre-release image). The upgrade path cannot be verified."
  elif ! [[ "$new" =~ $VERSION_RE ]]; then
    compat_kind="unknown"
    compat_message="the new image has no valid $LABEL_VERSION label, so its version cannot be checked."
  elif ! [[ "$min_from" =~ $VERSION_RE ]]; then
    compat_kind="unknown"
    compat_message="the new image declares no valid $LABEL_MIN_FROM label (installed $installed, new $new); it cannot say which versions it can be updated from."
  elif version_lt "$installed" "$min_from"; then
    compat_kind="refused"
    compat_message="installed version $installed is older than $min_from, the oldest version release $new can be updated from. Update to a release between $min_from and $new first (a stepping-stone), then run this update again. Nothing was changed."
  elif version_lt "$new" "$installed"; then
    compat_kind="refused"
    compat_message="the new image ($new) is older than the installed version ($installed). update.sh does not downgrade; use the pre-update snapshot restore steps in README.md instead. Nothing was changed."
  fi
}

backup_key_present() { # presence only; the value is never read into the script
  [ -f "$ENV_FILE" ] || return 1
  grep -q '^SIDEKICK_BACKUP_ENCRYPTION_KEY=.\+' "$ENV_FILE" && return 0
  # Or a secret file (secrets-to-files.sh): SELFHOST_BACKUP_ENCRYPTION_KEY_FILE names it, relative to this directory.
  local key_file
  key_file="$(sed -n 's/^SELFHOST_BACKUP_ENCRYPTION_KEY_FILE=//p' "$ENV_FILE" | tail -n 1)"
  [ -n "$key_file" ] || return 1
  case "$key_file" in /*) ;; *) key_file="$SCRIPT_DIR/$key_file" ;; esac
  [ -s "$key_file" ]
}

compose() { # release.env (if any) is a second env file, so a pinned SIDEKICK_API_IMAGE is honoured
  local args=() compose_file
  if [ -n "$PROJECT_NAME" ]; then
    args+=(-p "$PROJECT_NAME")
  fi
  for compose_file in "${COMPOSE_FILES[@]}"; do
    args+=(-f "$compose_file")
  done
  args+=(--env-file "$ENV_FILE")
  if [ -f "$RELEASE_FILE" ]; then
    args+=(--env-file "$RELEASE_FILE")
  fi
  docker compose "${args[@]}" "$@"
}

# stdin to stdout through a one-off api container: $1 = encrypt|decrypt. The one implementation of the snapshot
# format is snapshot_crypto.py next to this script (its source is passed with python -I -c, the same way tools/work.sh
# does); the key comes from selfhost.env through compose's env_file, or from a secret file, and is never on a command line.
CRYPTO_SCRIPT="$SCRIPT_DIR/snapshot_crypto.py"
crypto_run() {
  [ -f "$CRYPTO_SCRIPT" ] || { echo "update.sh: snapshot_crypto.py not found next to this script" >&2; return 1; }
  compose run --rm -T --no-deps api python -I -c "$(cat "$CRYPTO_SCRIPT")" "$1"
}

if [ -n "$image" ] && ! [[ "$image" =~ $IMAGE_RE ]]; then
  die "--image must be REGISTRY/REPO@sha256:<64 hex>; tags are mutable and refused"
fi

# Makes one file, or a directory entry, durable: `sync PATH` (coreutils) flushes just that path, an implementation that
# ignores the argument flushes everything.
fsync_path() { sync "$1" 2>/dev/null || sync; }

# --- decrypt a snapshot (stdout only) -------------------------------------------------------

if [ "$mode" = "decrypt" ]; then
  [ -f "$snapshot_in" ] || die "snapshot file not found"
  [ -t 1 ] && die "refusing to write a decrypted database dump to a terminal; redirect stdout to a file (umask 077)"
  command -v docker >/dev/null 2>&1 || die "docker not found"
  [ -f "$ENV_FILE" ] || die "selfhost.env not found next to this script"
  crypto_run decrypt <"$snapshot_in"
  exit $?
fi

# --- read-only status ------------------------------------------------------------------------

if [ "$mode" = "check" ]; then
  rc=0
  echo "update.sh: CHECK (read-only). Nothing is changed."
  echo "  pinned api image (release.env) : ${current_pin:-none (compose default $previous_ref)}"
  echo "  previous image (rollback)      : $(read_pin SIDEKICK_API_IMAGE_PREVIOUS | grep . || echo none)"
  echo "  last update journal state      : $(last_journal_state | grep . || echo none)"
  if ! command -v docker >/dev/null 2>&1; then
    echo "  docker                         : MISSING (running image, schema head not checked)"
  elif [ ! -f "$ENV_FILE" ]; then
    echo "  selfhost.env                   : MISSING (compose state, image labels and schema head not checked)"
  else
    cid="$(compose ps -q api 2>/dev/null || true)"
    if [ -n "$cid" ]; then
      echo "  running api container image    : $(docker inspect -f '{{.Config.Image}}' "$cid" 2>/dev/null || echo unknown)"
    else
      echo "  running api container image    : api not running"
    fi
    img_head="$(docker image inspect -f '{{ index .Config.Labels "io.sidekick.schema-head" }}' "$previous_ref" 2>/dev/null || true)"
    img_class="$(docker image inspect -f "{{ index .Config.Labels \"$LABEL_CLASS\" }}" "$previous_ref" 2>/dev/null || true)"
    echo "  installed version (label)      : $(image_label "$(installed_image_ref)" "$LABEL_VERSION" | grep . || echo unknown)"
    echo "  image schema head (label)      : ${img_head:-unknown (image absent locally or no label)}"
    echo "  image migration class (label)  : ${img_class:-unknown}"
    if [ -n "$(compose ps -q --status running postgres 2>/dev/null || true)" ]; then
      db_head="$(compose exec -T postgres psql -U postgres -d sidekick -Atc 'select migration_id from _yoyo_migration order by applied_at_utc desc, migration_id desc limit 1' 2>/dev/null | grep -E '^[0-9]{3}_' || true)"
      echo "  database schema head (applied) : ${db_head:-unknown}"
      if [ -n "$img_head" ] && [ -n "$db_head" ] && [ "$img_head" != "$db_head" ]; then
        echo "  NOTE: image schema head differs from the database (migrate pending, or db ahead of image)"
      fi
    else
      echo "  database schema head (applied) : postgres not running (not started by --check)"
    fi
  fi
  if [ -z "$current_pin" ]; then
    echo "  signature                      : not applicable (no digest pinned; local build or first install)"
  elif ! command -v cosign >/dev/null 2>&1; then
    echo "  signature                      : NOT CHECKED (cosign missing; install it, do not skip verification)"
  elif [ -z "$identity" ]; then
    echo "  signature                      : NOT CHECKED (give --cert-identity or SIDEKICK_RELEASE_CERT_IDENTITY)"
  elif cosign verify "$current_pin" --certificate-identity "$identity" --certificate-oidc-issuer "$issuer" >/dev/null 2>&1; then
    echo "  signature                      : VALID for the pinned digest"
  else
    echo "  signature                      : INVALID or unreachable for the pinned digest"
    rc=1
  fi
  exit "$rc"
fi

# --- dry run ---------------------------------------------------------------------------------

if [ "$mode" = "dry-run" ]; then
  have() { command -v "$1" >/dev/null 2>&1 && echo present || echo MISSING; }
  worker_names=""
  for entry in "${WORKERS[@]}"; do
    worker_names="$worker_names ${entry#*:}"
  done
  worker_names="${worker_names# }"
  echo "update.sh: DRY RUN. Nothing is executed, no docker or network call is made."
  echo
  echo "Checks (local only):"
  echo "  docker                      : $(have docker)"
  echo "  cosign                      : $(have cosign) (missing = --apply refuses, fail closed)"
  echo "  selfhost.env                : $([ -f "$ENV_FILE" ] && echo present || echo MISSING)"
  echo "  compose files / project     : ${COMPOSE_FILES[*]} / ${PROJECT_NAME:-<compose default>}"
  echo "  SIDEKICK_BACKUP_ENCRYPTION_KEY set (as a value or a secret file): $(backup_key_present && echo yes || echo NO) (--apply refuses without it; also encrypts the snapshot)"
  echo "  signer identity             : $([ -n "$identity" ] && echo given || echo NOT-GIVEN) (--cert-identity or SIDEKICK_RELEASE_CERT_IDENTITY)"
  echo "  current api image           : $previous_ref"
  echo "  last update journal state   : $(last_journal_state | grep . || echo none) (anything but DONE/ROLLED_BACK/ABORTED blocks --apply; STARTED, STOPPING_WRITERS and RESUMING, left by an update that was killed, are resumed)"
  echo
  echo "Plan for --apply with image ${image:-<REF@sha256:DIGEST, required>}:"
  cat <<EOF
  1. cosign verify <image> --certificate-identity <id> --certificate-oidc-issuer $issuer
  2. docker pull <image>; read label $LABEL_CLASS (expand | breaking; missing is refused unless allowed); check the
     upgrade path: installed version (label $LABEL_VERSION of the running image) must be >= the new image's
     $LABEL_MIN_FROM label; a skipped stepping-stone or an unknown version is refused (before anything is stopped)
  3. docker compose up -d --wait postgres; stop api and every running or restarting worker (of: $worker_names) so that nothing
     writes any more (the database stays up; an unknown worker state aborts the update before anything is stopped)
  4. sidekick-backup-worker --once with the current image (a failed backup stops the update and starts the previous
     image again), then pg_dump -Fc piped through the api image, Fernet-encrypted with SIDEKICK_BACKUP_ENCRYPTION_KEY, to
     $STATE_DIR/snapshots/*.dump.enc (mode 600); it is decrypted again and listed with pg_restore --list, flushed to disk
     and renamed into place before the migration starts (a snapshot that fails this stops the update); read it back with
     --decrypt-snapshot FILE > out.dump
  5. run migrate with the new image; write release.env
     (SIDEKICK_API_IMAGE=new, SIDEKICK_API_IMAGE_PREVIOUS=$previous_ref); start api and those workers with the new digest
  6. wait up to ${HEALTH_TIMEOUT}s for readiness (api process answers HTTP; database answers and schema at the image's revision;
     every worker started with it is running and healthy)
  7. on failure: previous image back if class=expand or the schema is unchanged; otherwise api stays
     stopped and the snapshot restore steps are printed. The database is never rolled back automatically.
EOF
  exit 0
fi

# --- apply -----------------------------------------------------------------------------------

[ -n "$image" ] || die "--apply requires --image REF@sha256:DIGEST"
[ -n "$identity" ] || die "--apply requires --cert-identity (the exact release workflow identity)"
command -v docker >/dev/null 2>&1 || die "docker not found"
if ! command -v cosign >/dev/null 2>&1; then
  die "cosign not found, refusing to update (fail closed). Install cosign from https://docs.sigstore.dev/cosign/system_config/installation/ and re-run; do not skip verification"
fi
[ -f "$ENV_FILE" ] || die "selfhost.env not found next to this script"
for compose_file in "${COMPOSE_FILES[@]}"; do
  [ -f "$compose_file" ] || die "compose file not found: $compose_file"
done
backup_key_present || die "SIDEKICK_BACKUP_ENCRYPTION_KEY is not set in selfhost.env (neither as a value nor as SELFHOST_BACKUP_ENCRYPTION_KEY_FILE); an update without a backup is refused"
[ "$image" != "$current_pin" ] || die "the installation already runs this digest"

umask 077
mkdir -p "$STATE_DIR/snapshots"

running_workers=() # entries of WORKERS that were running when the update started
started_workers=() # entries of WORKERS that start_api last started (wait_healthy checks every one of them)
changed=0 # 1 once the migration phase has begun (the schema may differ from before)
writers_stopped=0 # 1 once api and the workers are being stopped: a failure before the migration starts them again
migration_class="unknown"
snapshot_file=""
snapshot_tmp="" # the snapshot while it is being written; renamed to snapshot_file only when complete
before_count="unknown"
apply_running=0 # 1 from the first journal entry until the update is finished: an interrupt then runs fail_apply
in_fail=0 # 1 while fail_apply runs (it ignores further signals and must not be re-entered)
resumed_workers="" # WORKERS entries a killed earlier run had stopped (from the journal), comma separated
resume_note="" # " workers=LIST" when resuming a run that had begun to stop the writers; carried on in the journal
last_line=""

# The lock is an flock(1) on LOCK_FILE, held on file descriptor 9 for the whole run. The kernel drops it when this
# process dies (kill -9, power loss), so there is no stale lock to take over and no window in which two runs can both
# conclude that the other one is gone. The file itself is never deleted (deleting a lock file that another process
# has open or is about to open would let two runs lock different files). LOCK_PID_FILE only says who holds it, for
# the message; a run that does not hold the lock never writes or removes it.
release_lock() {
  rm -f "$LOCK_PID_FILE"
}

acquire_lock() {
  local recorded=""
  command -v flock >/dev/null 2>&1 || die "flock not found (util-linux); refusing to update without a lock"
  exec 9>>"$LOCK_FILE" || die "cannot open the lock file $LOCK_FILE"
  if ! flock -n 9; then
    recorded="$(cat "$LOCK_PID_FILE" 2>/dev/null || true)"
    [[ "$recorded" =~ ^[0-9]+$ ]] || recorded=""
    die "another update is running (lock $LOCK_FILE is held${recorded:+, recorded owner pid $recorded})"
  fi
  # We hold the lock, so a pid still recorded belongs to a run that died without cleaning up.
  recorded="$(cat "$LOCK_PID_FILE" 2>/dev/null || true)"
  [[ "$recorded" =~ ^[0-9]+$ ]] || recorded=""
  if [ -n "$recorded" ]; then
    echo "update.sh: taking over the stale lock of an update process that is gone (pid $recorded)" >&2
  fi
  printf '%s\n' "$$" >"$LOCK_PID_FILE"
}

on_exit() { # EXIT: the one place that always releases the lock, and recovers from an unexpected exit
  local rc=$?
  trap '' INT TERM HUP
  trap - EXIT
  if [ "$apply_running" -eq 1 ] && [ "$in_fail" -eq 0 ]; then
    echo "update.sh: exited unexpectedly (status $rc); restoring a consistent state" >&2
    (fail_apply "unexpected-exit-status-$rc") || true
    [ "$rc" -ne 0 ] || rc=1
  fi
  release_lock
  exit "$rc"
}

on_signal() { # $1 = signal name, $2 = exit status
  trap '' INT TERM HUP
  echo "update.sh: received SIG$1; stopping safely, the installation is being put back into a consistent state" >&2
  if [ "$apply_running" -eq 1 ] && [ "$in_fail" -eq 0 ]; then
    fail_apply "interrupted-by-SIG$1"
  fi
  exit "$2"
}

acquire_lock
trap on_exit EXIT
trap 'on_signal INT 130' INT
trap 'on_signal TERM 143' TERM
trap 'on_signal HUP 129' HUP
rm -f "$JOURNAL.tmp" # a torn temporary file of a killed run; the journal itself is always whole

# The journal is rewritten, never appended in place: the old lines plus the new one go to a temporary file in the same
# directory, the file is flushed, renamed over the journal (atomic) and the directory entry is flushed. After a power
# loss the journal is therefore either the old one or the new one, never a torn line.
journal() {
  local tmp="$JOURNAL.tmp"
  { [ ! -f "$JOURNAL" ] || cat "$JOURNAL"; printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "${2:-}"; } >"$tmp"
  fsync_path "$tmp"
  mv "$tmp" "$JOURNAL"
  fsync_path "$STATE_DIR"
}

worker_ready() { # $1 = a WORKERS entry; ready = running, and healthy where the service has a compose healthcheck
  local entry="$1" cid state
  # shellcheck disable=SC2046 # the same wanted splitting as in live_containers
  cid="$(compose $(worker_profile_args "$entry") ps -q "${entry#*:}" 2>/dev/null)" || return 1
  [ -n "$cid" ] || return 1
  state="$(docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null)" || return 1
  case "$state" in
    "running healthy" | "running none") return 0 ;;
    *) return 1 ;;
  esac
}

# ready = the api runs the expected image and passes the readiness check, AND every worker start_api started (see
# started_workers) is running and, where compose declares a healthcheck, healthy. An update is not finished while a
# worker (memory, push, backup, automation) is down, so a worker that never becomes healthy fails the step like the api.
wait_healthy() { # $1 = expected image ref
  local deadline=$((SECONDS + HEALTH_TIMEOUT)) cid running entry ok
  while [ "$SECONDS" -lt "$deadline" ]; do
    cid="$(compose ps -q api 2>/dev/null || true)"
    if [ -n "$cid" ]; then
      running="$(docker inspect -f '{{.Config.Image}}' "$cid" 2>/dev/null || echo unknown)"
      if [ "$running" = "$1" ] && compose exec -T api python -c "$READINESS_PY" >/dev/null 2>&1; then
        ok=1
        for entry in ${started_workers[@]+"${started_workers[@]}"}; do
          worker_ready "$entry" || { ok=0; break; }
        done
        [ "$ok" -eq 1 ] && return 0
      fi
    fi
    sleep "${SIDEKICK_UPDATE_POLL_SECONDS:-3}"
  done
  return 1
}

worker_profile_args() { # $1 = a WORKERS entry; prints "--profile NAME", or nothing for a default (profile-less) service
  [ -n "${1%%:*}" ] && printf '%s\n%s\n' --profile "${1%%:*}"
  return 0
}

live_containers() { # $1 = a WORKERS entry; prints the id of every container of the service that is or may become active
  local entry="$1" cids cid line policy
  # Every status counts, not only "running": a worker in a restart loop is "restarting" between two attempts and
  # Docker would start it again during the backup, the snapshot or the migration.
  # worker_profile_args prints "--profile" and the name on two lines (or nothing): the splitting is wanted.
  # shellcheck disable=SC2046
  cids="$(compose $(worker_profile_args "$entry") ps -a -q "${entry#*:}" 2>/dev/null)" || return 1
  for cid in $cids; do
    line="$(docker inspect -f '{{.State.Status}} {{.HostConfig.RestartPolicy.Name}}' "$cid" 2>/dev/null)" || return 1
    case "$line" in
      running\ * | restarting\ * | paused\ *) echo "$cid" ;;
      created\ *)
        policy="${line#created }" # a created container is only started by Docker when it has a restart policy
        if [ -n "$policy" ] && [ "$policy" != no ]; then echo "$cid"; fi
        ;;
    esac
  done
}

detect_running_workers() { # fills running_workers from WORKERS (running, restarting, paused); non-zero when unknown
  local entry listed
  local -a found=()
  for entry in "${WORKERS[@]}"; do
    # A failing compose ps is not "not running": guessing would leave a writer running through the snapshot.
    # On failure running_workers is left as it was (the saved list of a resumed run), so fail_apply can still
    # start every one of them again; it is replaced only when the whole inventory succeeded.
    listed="$(live_containers "$entry")" || return 1
    if [ -n "$listed" ]; then
      found+=("$entry")
    fi
  done
  running_workers=(${found[@]+"${found[@]}"})
}

merge_resumed_workers() { # adds the workers a killed earlier run had stopped; only names that are in WORKERS count
  local name entry known known_entry
  for name in ${resumed_workers//,/ }; do
    for entry in "${WORKERS[@]}"; do
      [ "$entry" = "$name" ] || continue
      known=0
      for known_entry in ${running_workers[@]+"${running_workers[@]}"}; do
        [ "$known_entry" = "$entry" ] && known=1
      done
      [ "$known" -eq 1 ] || running_workers+=("$entry")
    done
  done
}

stop_workers() { # stops every running worker, also after a failure; non-zero if any stop failed
  local entry rc=0
  for entry in ${running_workers[@]+"${running_workers[@]}"}; do
    # shellcheck disable=SC2046 # the same wanted splitting as in live_containers
    compose $(worker_profile_args "$entry") stop "${entry#*:}" >/dev/null || rc=1
  done
  return "$rc"
}

verify_writers_stopped() { # non-zero unless api and every worker are stopped and none can start again by itself
  local entry listed
  for entry in ":api" "${WORKERS[@]}"; do
    listed="$(live_containers "$entry")" || return 1
    if [ -n "$listed" ]; then
      echo "update.sh: ${entry#*:} is still running or restarting after the stop" >&2
      return 1
    fi
  done
}

migration_count() { # number of applied yoyo migrations, or "unknown"
  compose exec -T postgres psql -U postgres -d sidekick -Atc 'select count(*) from _yoyo_migration' 2>/dev/null | grep -E '^[0-9]+$' || echo unknown
}

start_api() { # $1 = image ref
  export SIDEKICK_API_IMAGE="$1"
  local profiles=() services=(api) entry
  started_workers=()
  for entry in ${running_workers[@]+"${running_workers[@]}"}; do
    [ -z "${entry%%:*}" ] || profiles+=(--profile "${entry%%:*}")
    services+=("${entry#*:}")
    started_workers+=("$entry")
  done
  # Default-on (profile-less) workers are part of the base stack: start them whether or not they ran before, so an
  # installation that predates a worker gets it with the update. Not reached on the manual-restore path.
  for entry in "${WORKERS[@]}"; do
    [ -z "${entry%%:*}" ] || continue
    case " ${services[*]} " in *" ${entry#*:} "*) ;; *) services+=("${entry#*:}"); started_workers+=("$entry") ;; esac
  done
  # Caddy (vps profile) is recreated with api when it runs: api trusts forwarded headers from Caddy's fixed address on
  # the proxy network only, so a Caddy container created before that network existed (no proxy membership, no `api`
  # pin in extra_hosts) would reach api over edge and have its X-Forwarded-* headers ignored. Its image is not touched.
  if [ -n "$(compose --profile vps ps -q caddy 2>/dev/null)" ]; then
    profiles+=(--profile vps)
    services+=(caddy)
  fi
  compose ${profiles[@]+"${profiles[@]}"} up -d --no-build --pull never "${services[@]}"
}

write_release() { # $1 = new image, $2 = previous ref
  local tmp="$RELEASE_FILE.tmp"
  printf 'SIDEKICK_API_IMAGE=%s\nSIDEKICK_API_IMAGE_PREVIOUS=%s\n' "$1" "$2" >"$tmp"
  fsync_path "$tmp" # durable before it replaces the pointer: after a power loss the old or the new file, never a torn one
  mv "$tmp" "$RELEASE_FILE"
  fsync_path "$(dirname -- "$RELEASE_FILE")"
}

manual_restore_help() {
  cat >&2 <<EOF
update.sh: the database may now be on a newer schema than the previous image supports.
  api and the workers are left STOPPED on purpose. Nothing was restored automatically.
  Pre-update snapshot : ${snapshot_file:-none} (encrypted; update.sh --decrypt-snapshot FILE > out.dump)
  Encrypted owner backups: volume sidekick_state, directory backups/
  The next --apply is refused until the journal records how you resolved this (README.md, "Update").
  Options, in this order:
    1. Fix forward: append "<UTC time> ABORTED manual" to $JOURNAL and re-run with the corrected image.
       The database stays on its new schema.
    2. Restore the snapshot into an EMPTY database, as README.md describes under "Restore the whole database".
       Start the PREVIOUS image ($previous_ref), not the new one in release.env; the snapshot is only a data
       dump, so keep the old database (it is renamed, not dropped) until the restored one is verified. Then put
       release.env back to the previous image and append "<UTC time> ROLLED_BACK manual-restore" to the journal.
EOF
}

fail_apply() { # $1 = phase
  in_fail=1
  trap '' INT TERM HUP # the recovery below must not be interrupted half way
  echo "update.sh: failed in phase: $1" >&2
  rm -f "$RELEASE_FILE.tmp" "$JOURNAL.tmp" ${snapshot_tmp:+"$snapshot_tmp"} 2>/dev/null || true # never leave a half-written file
  if [ "$changed" -eq 0 ] && [ "$writers_stopped" -eq 0 ]; then
    journal ABORTED "phase=$1 (runtime untouched)"
    echo "update.sh: the running installation was not touched." >&2
    exit 1
  fi
  if [ "$changed" -eq 0 ]; then
    # Writers were stopped but the migration had not begun: the schema is unchanged, so start the previous image and
    # the workers again. release.env was not written yet and stays as it is.
    echo "update.sh: starting the previous image $previous_ref again (the migration had not begun)" >&2
    if start_api "$previous_ref" && wait_healthy "$previous_ref"; then
      journal ABORTED "phase=$1 (writers restarted with $previous_ref)"
      echo "update.sh: the installation runs as before." >&2
    else
      journal NEEDS_RESTART "phase=$1 (the previous image did not become ready) workers=$(IFS=,; echo "${running_workers[*]-}")"
      echo "update.sh: the previous image did not become ready. Start it by hand (docker compose up -d), then append" >&2
      echo "  \"<UTC time> ABORTED manual\" to $JOURNAL before the next --apply." >&2
    fi
    exit 1
  fi
  journal ROLLING_BACK "phase=$1"
  local after entry
  after="$(migration_count)"
  if [ "$migration_class" = expand ] || { [ "$before_count" != unknown ] && [ "$before_count" = "$after" ]; }; then
    echo "update.sh: starting the previous image $previous_ref" >&2
    if start_api "$previous_ref" && wait_healthy "$previous_ref"; then
      if [ -f "$RELEASE_FILE" ] && [ -n "$current_pin" ]; then
        write_release "$current_pin" "$image"
      else
        rm -f "$RELEASE_FILE"
        fsync_path "$(dirname -- "$RELEASE_FILE")"
      fi
      journal ROLLED_BACK "phase=$1 previous=$previous_ref"
      echo "update.sh: rolled back to $previous_ref" >&2
      exit 1
    fi
  fi
  journal NEEDS_MANUAL_RESTORE "phase=$1 schema_before=$before_count schema_after=$after"
  compose stop api >/dev/null 2>&1 || true
  stop_workers 2>/dev/null || true
  # start_api also starts the default-on workers that were not running before; none may keep writing here.
  for entry in "${WORKERS[@]}"; do
    [ -n "${entry%%:*}" ] || compose stop "${entry#*:}" >/dev/null 2>&1 || true
  done
  manual_restore_help
  exit 1
}

# Recovery status is read BEFORE any pre-check (signature, pull, version), because a failing pre-check ends in
# fail_apply and that must already know that writers may be stopped and which workers they were. We hold the lock, so
# the process that wrote the last state is gone. Before MIGRATING nothing but the stop of the writers can have
# happened, and the journal carries the list of workers that run stopped (or was about to stop): resume.
state="$(last_journal_state)"
case "$state" in
  "" | DONE | ROLLED_BACK | ABORTED) ;;
  STARTED | STOPPING_WRITERS | RESUMING)
    echo "update.sh: an earlier update was killed in state $state before the migration; resuming" >&2
    last_line="$(tail -n 1 "$JOURNAL")"
    # A "workers=" key (even an empty one) means the earlier run had begun to stop the writers; a plain STARTED,
    # written before that, means nothing was stopped.
    case "$state:$last_line" in
      STOPPING_WRITERS:* | *\ workers=*)
        resumed_workers="$(printf '%s\n' "$last_line" | sed -n 's/.* workers=\([^ ]*\).*/\1/p')"
        resume_note=" workers=$resumed_workers"
        merge_resumed_workers # running_workers = the saved list, so every failure below can start them again
        writers_stopped=1 # a failure or an interrupt must start them again, never journal "untouched"
        ;;
    esac
    rm -f "$STATE_DIR"/snapshots/*.partial "$RELEASE_FILE.tmp"
    journal RESUMING "from=$state$resume_note"
    ;;
  *) die "previous update ended in state $state (see $JOURNAL); resolve it by hand before a new update" ;;
esac

apply_running=1
# The list stays in the journal (on STARTED too) until a restart has succeeded, so a second kill cannot lose it.
journal STARTED "image=$image previous=$previous_ref$resume_note"

echo "update.sh: 1/7 verifying the signature (exact digest, pinned identity and issuer)"
cosign verify "$image" --certificate-identity "$identity" --certificate-oidc-issuer "$issuer" >/dev/null ||
  fail_apply "signature-verification"

echo "update.sh: 2/7 pulling the image, reading its migration class and checking the upgrade path"
docker pull "$image" >/dev/null || fail_apply "pull"
migration_class="$(docker image inspect -f "{{ index .Config.Labels \"$LABEL_CLASS\" }}" "$image" 2>/dev/null || true)"
case "$migration_class" in
  expand) ;;
  breaking) [ "$allow_breaking" -eq 1 ] || fail_apply "migration-class-breaking-not-allowed" ;;
  *)
    migration_class="unknown"
    [ "$allow_unknown" -eq 1 ] || fail_apply "migration-class-missing-not-allowed"
    ;;
esac
installed_version="$(image_label "$(installed_image_ref)" "$LABEL_VERSION")"
new_version="$(image_label "$image" "$LABEL_VERSION")"
check_upgrade_path "$installed_version" "$new_version" "$(image_label "$image" "$LABEL_MIN_FROM")"
case "$compat_kind" in
  ok) echo "update.sh: upgrade path ok: $installed_version -> $new_version" ;;
  unknown)
    echo "update.sh: $compat_message" >&2
    if [ "$allow_unknown_version" -eq 1 ]; then
      echo "update.sh: continuing because of --allow-unknown-version" >&2
    else
      echo "update.sh: refusing. Re-run with --allow-unknown-version only if you know this installation is at or above the new image's minimum version." >&2
      fail_apply "version-compat-unknown"
    fi
    ;;
  *)
    echo "update.sh: $compat_message" >&2
    fail_apply "version-compat-refused"
    ;;
esac

# Room for the snapshot is checked now, while the installation still runs: a full disk found after the stop would
# stop the writers for nothing. The owner backup goes to the state volume and is not measured here.
SNAPSHOT_ERE='sidekick-pre-[0-9]{8}T[0-9]{6}Z\.dump\.enc'
snapshot_keep="${SIDEKICK_SNAPSHOT_KEEP:-5}"
backup_valid_keep "$snapshot_keep" || fail_apply "snapshot-keep-invalid"
space_rc=0
backup_check_space "$STATE_DIR/snapshots" "$(backup_newest_size "$STATE_DIR/snapshots" "$SNAPSHOT_ERE")" || space_rc=$?
case "$space_rc" in
  0) ;;
  1)
    echo "update.sh: not enough free space for a snapshot in $STATE_DIR/snapshots: $BACKUP_SPACE_FREE bytes free, $BACKUP_SPACE_NEEDED needed (newest snapshot times the margin, at least the floor). Free up space and re-run; nothing was stopped." >&2
    fail_apply "snapshot-disk-space"
    ;;
  *)
    echo "update.sh: cannot tell whether $STATE_DIR/snapshots has room for a snapshot (df gave no answer, or SIDEKICK_BACKUP_SPACE_MARGIN_PCT / SIDEKICK_BACKUP_SPACE_FLOOR_MB is not a valid number); nothing was stopped." >&2
    fail_apply "snapshot-disk-space-unknown"
    ;;
esac

echo "update.sh: 3/7 stopping api and the workers (the database stays up)"
compose up -d --wait postgres || fail_apply "start-postgres"
detect_running_workers || fail_apply "worker-status"
merge_resumed_workers
# Intent first: if this process is killed during the stop, the next run can read which workers to start again.
journal STOPPING_WRITERS "workers=$(IFS=,; echo "${running_workers[*]-}")"
writers_stopped=1
compose stop api >/dev/null || fail_apply "stop-api"
stop_workers || fail_apply "stop-workers"
verify_writers_stopped || fail_apply "writers-still-running"
before_count="$(migration_count)"

echo "update.sh: 4/7 encrypted owner backup and database snapshot, with every writer stopped"
compose run --rm -T --no-deps backup sidekick-backup-worker --once || fail_apply "owner-backup"
snapshot_tmp="$STATE_DIR/snapshots/sidekick-pre-$(date -u +%Y%m%dT%H%M%SZ).dump.enc.partial"
if ! { compose exec -T postgres pg_dump -U postgres -d sidekick -Fc | crypto_run encrypt; } >"$snapshot_tmp"; then
  fail_apply "snapshot" # removes the partial file
fi
[ -s "$snapshot_tmp" ] || fail_apply "snapshot-empty"
# The snapshot only counts once it can be read back: decrypt it again (Fernet authenticates the whole file) and let
# pg_restore list the dump's table of contents. Nothing is written to disk. A snapshot that fails is removed and the
# update stops before the migration.
if ! { crypto_run decrypt <"$snapshot_tmp" | compose exec -T postgres pg_restore --list; } >/dev/null; then
  fail_apply "snapshot-unverified" # removes the partial file
fi
snapshot_file="${snapshot_tmp%.partial}"
chmod 600 "$snapshot_tmp"
fsync_path "$snapshot_tmp"
mv "$snapshot_tmp" "$snapshot_file" # complete or absent, never half written
snapshot_tmp=""
fsync_path "$STATE_DIR/snapshots"

echo "update.sh: 5/7 migrating and starting the new image (class: $migration_class)"
changed=1
journal MIGRATING "class=$migration_class snapshot=${snapshot_file##*/}"
export SIDEKICK_API_IMAGE="$image" # from here on compose resolves the new image
compose run --rm -T --no-deps migrate || fail_apply "migrate"
write_release "$image" "$previous_ref"
start_api "$image" || fail_apply "start-api"

echo "update.sh: 6/7 waiting for readiness: database and schema revision (up to ${HEALTH_TIMEOUT}s)"
wait_healthy "$image" || fail_apply "health-check"

apply_running=0 # the new image is healthy: from here an interrupt must not roll anything back
echo "update.sh: 7/7 done"
journal DONE "image=$image"
# Old snapshots are pruned only now, after a successful update: while an update is failing or needs a restore, no
# restore point is touched. The newest SIDEKICK_SNAPSHOT_KEEP finished snapshots stay and the one just taken is
# never removed; only names of the exact finished form are considered (never a .partial or any other file).
if pruned="$(backup_prune_finished "$STATE_DIR/snapshots" "$SNAPSHOT_ERE" "$snapshot_keep" "${snapshot_file##*/}")"; then
  fsync_path "$STATE_DIR/snapshots"
  echo "update.sh: kept the newest $snapshot_keep snapshots in $STATE_DIR/snapshots, removed $pruned older"
else
  echo "update.sh: warning: could not prune old snapshots in $STATE_DIR/snapshots" >&2
fi
echo "update.sh: updated to $image; previous image kept as $previous_ref for a manual rollback"
