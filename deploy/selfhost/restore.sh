#!/usr/bin/env bash
# Restore one owner from an encrypted Sidekick backup or a plain owner export.
#
# A thin wrapper around `sidekick-backup import` in a one-off api container. The input is an owner
# export (sidekick.encrypted-owner-backup, or an unencrypted .json export), not a database dump.
# Restore is therefore owner-scoped: the target owner must already exist and must have no product data.
# Without --apply the script decrypts, verifies and prints the restore plan, and writes nothing.
# With --apply it applies that same reviewed plan (matched by its checksum) and verifies the row
# counts. The decrypted export stays in the memory of a one-off api container (--rm).
#
# Journal photos: the backup lists their rows; their files are kept encrypted in the `media/` folder that sits beside the
# backup files (copy it off the machine together with them). The folder next to --backup is used when it exists, or give
# it with --media-dir. A plain export folder (export.json and media/) is restored the same way. The files are written
# into the instance's media volume under the target owner. A copy of the folder is staged for the one-off container and
# removed again, because the container's user cannot read files that only you may read.
#
# Requires: postgres running (docker compose --env-file selfhost.env up -d postgres) and
# SIDEKICK_BACKUP_ENCRYPTION_KEY in selfhost.env (or as a secret file, see secrets-to-files.sh). The key is never printed or put on a command line.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/compose.yaml"
# -f/--compose-file (repeatable) replaces the default compose.yaml, exactly like docker compose -f.
# -p/--project-name is passed to docker compose; without it compose derives the name as usual
# (COMPOSE_PROJECT_NAME in the environment is honoured too).
COMPOSE_FILES=()
PROJECT_NAME=""
ENV_FILE="$SCRIPT_DIR/selfhost.env"
# Written by update.sh: SIDEKICK_API_IMAGE=<repo>@sha256:<digest>. When present, restore runs with the
# same pinned image as the installation instead of the local roadlake-sidekick:selfhost default.
RELEASE_FILE="$SCRIPT_DIR/release.env"
UUID_RE='^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'

die() {
  echo "restore.sh: $*" >&2
  exit 1
}

usage() {
  cat >&2 <<'EOF'
usage: restore.sh [-p NAME] [-f FILE]... --backup FILE --target-owner UUID [--source-owner UUID] [--media-dir DIR] [--apply]

  -p, --project-name NAME  compose project name (default: compose's own, or COMPOSE_PROJECT_NAME)
  -f, --compose-file FILE  compose file, repeatable, used instead of the default compose.yaml
                         (give compose.yaml first when adding an override file)
  --backup FILE          an encrypted .skbackup file (for example copied from the backups directory),
                         a plain owner export .json, or an export folder (export.json and media/)
  --media-dir DIR        the photo files: the media/ folder of the backups directory, or of an export
                         (default: media/ next to the backup file or inside the export folder, if it exists)
  --target-owner UUID    existing, empty owner (create it first with sidekick-admin create-user)
  --source-owner UUID    required if the backup holds more than one owner (a .skbackup holds every owner)
  --apply                write the restore after showing the plan; without it nothing is written
EOF
  exit 2
}

backup=""
target_owner=""
source_owner=""
media_dir=""
apply=0
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
    --backup)
      [ $# -ge 2 ] || usage
      backup="$2"
      shift 2
      ;;
    --target-owner)
      [ $# -ge 2 ] || usage
      target_owner="$2"
      shift 2
      ;;
    --source-owner)
      [ $# -ge 2 ] || usage
      source_owner="$2"
      shift 2
      ;;
    --media-dir)
      [ $# -ge 2 ] || usage
      media_dir="$2"
      shift 2
      ;;
    --apply)
      apply=1
      shift
      ;;
    -h | --help)
      usage
      ;;
    *)
      echo "restore.sh: unknown argument" >&2
      usage
      ;;
  esac
done

[ -n "$backup" ] || usage
[ -n "$target_owner" ] || usage
input_file="$backup"
if [ -d "$backup" ]; then
  input_file="$backup/export.json"
  [ -f "$input_file" ] || die "export folder has no export.json"
  [ -n "$media_dir" ] || { [ ! -d "$backup/media" ] || media_dir="$backup/media"; }
else
  [ -f "$backup" ] || die "backup file not found"
  [ -n "$media_dir" ] || { [ ! -d "$(dirname -- "$backup")/media" ] || media_dir="$(dirname -- "$backup")/media"; }
fi
[ -z "$media_dir" ] || [ -d "$media_dir" ] || die "media folder not found"
[ -f "$ENV_FILE" ] || die "selfhost.env not found next to this script"
if [ "${#COMPOSE_FILES[@]}" -eq 0 ]; then
  COMPOSE_FILES=("$COMPOSE_FILE")
fi
for compose_file in "${COMPOSE_FILES[@]}"; do
  [ -f "$compose_file" ] || die "compose file not found: $compose_file"
done
[[ "$target_owner" =~ $UUID_RE ]] || die "--target-owner must be a UUID"
if [ -n "$source_owner" ]; then
  [[ "$source_owner" =~ $UUID_RE ]] || die "--source-owner must be a UUID"
fi

backup_abs="$(cd -- "$(dirname -- "$input_file")" && pwd)/$(basename -- "$input_file")"

# The photo files are staged in a private temporary folder, readable by the container user, and mounted read-only.
media_args=()
media_stage=""
if [ -n "$media_dir" ]; then
  media_stage="$(mktemp -d)"
  trap 'rm -rf "$media_stage"' EXIT
  cp -R -- "$media_dir" "$media_stage/media"
  chmod -R a+rX "$media_stage/media"
  media_args=(-v "$media_stage/media:/restore-media:ro")
fi

# Only the api service is used: same image, env_file, network (data) and read-only root as at runtime.
# --no-deps: postgres must already be running, and migrate must not run as a side effect.
# The file is streamed on stdin (FILE "-"), so the container never gets a host path or file permissions.
run_import() {
  local compose_args=()
  if [ -n "$PROJECT_NAME" ]; then
    compose_args+=(-p "$PROJECT_NAME")
  fi
  for compose_file in "${COMPOSE_FILES[@]}"; do
    compose_args+=(-f "$compose_file")
  done
  compose_args+=(--env-file "$ENV_FILE")
  if [ -f "$RELEASE_FILE" ]; then
    compose_args+=(--env-file "$RELEASE_FILE")
  fi
  local import_args=()
  if [ -n "$media_dir" ]; then
    import_args+=(--media-directory /restore-media)
  fi
  docker compose "${compose_args[@]}" run --rm -T --no-deps ${media_args[@]+"${media_args[@]}"} \
    api sidekick-backup import - ${import_args[@]+"${import_args[@]}"} "$@" <"$backup_abs"
}

owner_args=(--target-owner "$target_owner")
if [ -n "$source_owner" ]; then
  owner_args+=(--source-owner "$source_owner")
fi

echo "restore.sh: decrypting and verifying the backup, then building the plan (nothing is written)" >&2
plan_output="$(run_import "${owner_args[@]}")"
printf '%s\n' "$plan_output"

plan_checksum="$(printf '%s\n' "$plan_output" | sed -n 's/.*"plan_checksum": "\([0-9a-f]\{64\}\)".*/\1/p')"
[[ "$plan_checksum" =~ ^[0-9a-f]{64}$ ]] || die "could not read the plan checksum from the plan"

if [ "$apply" -ne 1 ]; then
  echo "restore.sh: dry run complete. Re-run with --apply to write this plan." >&2
  exit 0
fi

echo "restore.sh: applying the reviewed plan $plan_checksum" >&2
run_import "${owner_args[@]}" --apply --plan-checksum "$plan_checksum"
