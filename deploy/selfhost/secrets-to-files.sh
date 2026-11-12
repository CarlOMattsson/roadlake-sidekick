#!/bin/sh
# Moves the secrets of selfhost.env into files, so that they are not environment variables of the containers.
#   sh deploy/selfhost/secrets-to-files.sh --dry-run   # list what would move; changes nothing
#   sh deploy/selfhost/secrets-to-files.sh             # move them
#   sh deploy/selfhost/secrets-to-files.sh --env-file FILE --secrets-dir DIR   # another layout
#
# For each of the nine secret settings that selfhost.env sets with a real value it
#   1. writes the value to secrets/<name> (the directory mode 700, the file mode 644, see below),
#   2. reads the file back and compares it with the value,
#   3. only then removes the SIDEKICK_<NAME>= line from selfhost.env and adds SELFHOST_<NAME>_FILE=./secrets/<name>,
#      which compose.yaml mounts at /run/secrets/<name> and the backend reads through SIDEKICK_<NAME>_FILE.
# A value is never printed and never passed on a command line (it lives in a shell variable and is written with the
# printf builtin). selfhost.env is replaced in one rename (mode 600), so an interrupted run leaves either the old file
# or the new one. A secret is left in selfhost.env, with a note, when moving it could change its meaning: it is a
# placeholder, is assigned twice, or holds a character that Compose treats specially in an env file (quotes, spaces, `$`,
# `#`, a backslash). Run again after fixing: nothing that is already moved is touched.
# Why mode 644: Compose bind-mounts a file secret as it is on the host and ignores uid, gid and mode, and the container
# user is not you, so a mode 600 file could not be read there. The directory (mode 700) is what keeps other users of
# the host out. Recreate the services afterwards: docker compose --env-file selfhost.env up -d
set -eu
umask 077

here="$(cd "$(dirname "$0")" && pwd)"
env_file="$here/selfhost.env"
secrets_dir="$here/secrets"
dry_run=false
usage() { echo "usage: sh secrets-to-files.sh [--dry-run] [--env-file FILE] [--secrets-dir DIR]" >&2; exit 2; }
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) dry_run=true ;;
    --env-file) [ $# -ge 2 ] || usage; env_file="$2"; shift ;;
    --secrets-dir) [ $# -ge 2 ] || usage; secrets_dir="$2"; shift ;;
    *) usage ;;
  esac
  shift
done
[ -f "$env_file" ] || { echo "secrets-to-files: $env_file not found" >&2; exit 1; }
# mv would replace a symbolic link with a regular file and leave its target as it was.
[ ! -L "$env_file" ] || { echo "secrets-to-files: $env_file is a symbolic link; run this on the file it points to (--env-file)" >&2; exit 1; }

# The directory as compose.yaml must name it in SELFHOST_<NAME>_FILE: relative to this directory when it is below it
# (compose resolves a relative path from there), absolute otherwise.
case "$secrets_dir" in /*) ;; *) secrets_dir="$PWD/$secrets_dir" ;; esac
secrets_dir="${secrets_dir%/}"
case "$secrets_dir" in "$here"/*) secrets_ref="./${secrets_dir#"$here"/}" ;; *) secrets_ref="$secrets_dir" ;; esac

# An interrupted run leaves no half-written file behind.
secret_tmp=""
env_tmp=""
cleanup() { rm -f ${secret_tmp:+"$secret_tmp"} ${env_tmp:+"$env_tmp"}; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Flushes one file (coreutils `sync PATH`); an implementation that ignores the argument flushes everything.
fsync_path() { sync "$1" 2>/dev/null || sync; }

# SIDEKICK_ name and file name of every secret setting; keep in step with compose.yaml (a test checks it).
secrets="
SIDEKICK_DATABASE_URL:database_url
SIDEKICK_CURSOR_SIGNING_SECRET:cursor_signing_secret
SIDEKICK_TOKEN_PEPPER:token_pepper
SIDEKICK_MCP_OAUTH_GITHUB_CLIENT_SECRET:mcp_oauth_github_client_secret
SIDEKICK_MCP_OAUTH_SIGNING_KEY:mcp_oauth_signing_key
SIDEKICK_MEMORY_HINDSIGHT_API_TOKEN:memory_hindsight_api_token
SIDEKICK_MEMORY_ID_DERIVATION_KEY:memory_id_derivation_key
SIDEKICK_BACKUP_ENCRYPTION_KEY:backup_encryption_key
SIDEKICK_PUSH_AUTH_TOKEN:push_auth_token
"
# Characters whose meaning is the same in Compose's env-file syntax as written: nothing is quoted, expanded or cut off.
plain_value='^[A-Za-z0-9+/=_.:@%~,-]+$'

moved=""     # SIDEKICK_ names whose file is written and verified
sed_script="" # one delete command per moved name
append=""
left=0

for entry in $secrets; do
  name="${entry%%:*}"
  file="${entry#*:}"
  compose_var="SELFHOST_${name#SIDEKICK_}_FILE"
  if grep -q "^$compose_var=." "$env_file"; then
    if grep -q "^$name=." "$env_file"; then
      echo "  $name: LEFT: $name and $compose_var are both set, and the backend refuses that; remove the $name line"
      left=$((left + 1))
    else
      echo "  $name: already a file (see $compose_var)"
    fi
    continue
  fi
  assignments="$(grep -c "^$name=" "$env_file" || true)"
  if [ "$assignments" -eq 0 ]; then
    echo "  $name: not set in selfhost.env, nothing to move"
    continue
  fi
  if [ "$assignments" -gt 1 ]; then
    echo "  $name: LEFT: assigned $assignments times; keep one line and run again"
    left=$((left + 1))
    continue
  fi
  value="$(sed -n "s/^$name=//p" "$env_file")"
  if [ -z "$value" ]; then
    echo "  $name: empty, nothing to move"
    continue
  fi
  case "$value" in
    *replace-with-* | development-*)
      echo "  $name: LEFT: still a placeholder; set a real value first"
      left=$((left + 1))
      value=""
      continue
      ;;
  esac
  if ! printf '%s' "$value" | grep -Eq "$plain_value"; then
    echo "  $name: LEFT: the value has a character that needs care (quote, space, \$, #, backslash)."
    echo "      Move it by hand: write the exact value to $secrets_dir/$file, then replace the line by $compose_var=$secrets_ref/$file"
    left=$((left + 1))
    value=""
    continue
  fi
  if [ "$dry_run" = true ]; then
    echo "  $name: would move to $secrets_dir/$file"
    value=""
    continue
  fi
  mkdir -p "$secrets_dir"
  chmod 700 "$secrets_dir"
  secret_tmp="$secrets_dir/$file.tmp.$$"
  printf '%s\n' "$value" > "$secret_tmp"
  chmod 644 "$secret_tmp"
  if [ "$(cat "$secret_tmp")" != "$value" ]; then
    echo "secrets-to-files: could not verify $secrets_dir/$file; nothing changed in selfhost.env" >&2
    exit 1
  fi
  fsync_path "$secret_tmp"
  mv -f "$secret_tmp" "$secrets_dir/$file"
  secret_tmp=""
  value=""
  moved="$moved $name"
  sed_script="$sed_script
/^$name=/d"
  append="$append
$compose_var=$secrets_ref/$file"
  echo "  $name: moved to $secrets_dir/$file"
done

if [ -n "$moved" ]; then
  env_tmp="$env_file.tmp.$$"
  {
    sed -e "$sed_script" "$env_file"
    printf '\n# Secrets read from files (secrets-to-files.sh); compose.yaml mounts them at /run/secrets/<name>.%s\n' "$append"
  } > "$env_tmp"
  chmod 600 "$env_tmp"
  for name in $moved; do
    if grep -q "^$name=" "$env_tmp"; then
      echo "secrets-to-files: could not remove $name from selfhost.env; the files are written, selfhost.env is unchanged" >&2
      exit 1
    fi
  done
  fsync_path "$env_tmp"
  mv -f "$env_tmp" "$env_file"
  env_tmp=""
  fsync_path "$(dirname "$env_file")"
fi

if [ "$dry_run" = true ]; then
  echo "dry run: nothing was changed"
elif [ -n "$moved" ]; then
  echo "done: recreate the services so they use the files: docker compose --env-file selfhost.env up -d"
fi
[ "$left" -eq 0 ] || echo "$left secret(s) left in selfhost.env: see the notes above"
