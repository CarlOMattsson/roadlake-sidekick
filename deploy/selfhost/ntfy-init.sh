#!/bin/sh
# One-time setup of the own ntfy server's accounts. Run it from anywhere:
#   sh deploy/selfhost/ntfy-init.sh            # create what is missing, change nothing that exists
#   sh deploy/selfhost/ntfy-init.sh --rotate   # replace every secret (then restart ntfy and the push worker)
#   sh deploy/selfhost/ntfy-init.sh --secrets-dir DIR --env-file FILE   # write elsewhere (e.g. the shared dev ntfy)
#
# It creates two accounts for ntfy/server.yml: `sidekick` (publishes with a token, may only write "up*") and
# `phone` (logs in with a password, may only read "up*"). It writes, all with mode 600 (the directory 700):
#   ntfy.env                    NTFY_AUTH_USERS / NTFY_AUTH_TOKENS, read by the ntfy service (bcrypt hashes)
#   ntfy-secrets/sidekick-token  goes into selfhost.env as SIDEKICK_PUSH_AUTH_TOKEN
#   ntfy-secrets/phone-password goes into the ntfy app on the phone (user "phone")
# --secrets-dir DIR holds the two secret files instead of ntfy-secrets/, --env-file FILE is the ntfy.env instead
# of ntfy.env next to this script. The defaults are the self-hosted layout. The image is always read from the
# compose.yaml next to this script.
# No token or password is ever printed or passed on a command line. The script prints only where the files are.
# It also makes ntfy/server.yml world-readable (it holds no secret), because the unprivileged ntfy container
# must be able to read it even when the checkout was made under umask 077.
# Needs docker (the bcrypt hash comes from the pinned ntfy image itself) and openssl.
set -eu
umask 077

here="$(cd "$(dirname "$0")" && pwd)"
env_file="$here/ntfy.env"
secrets_dir="$here/ntfy-secrets"
rotate=false
custom_layout=false
usage() { echo "usage: sh ntfy-init.sh [--rotate] [--secrets-dir DIR] [--env-file FILE]" >&2; exit 2; }
while [ $# -gt 0 ]; do
  case "$1" in
    --rotate) rotate=true ;;
    --secrets-dir) [ $# -ge 2 ] || usage; secrets_dir="$2"; custom_layout=true; shift ;;
    --env-file) [ $# -ge 2 ] || usage; env_file="$2"; custom_layout=true; shift ;;
    *) usage ;;
  esac
  shift
done
token_file="$secrets_dir/sidekick-token"
password_file="$secrets_dir/phone-password"

# The ntfy container runs as an unprivileged user and mounts ntfy/server.yml directly. A checkout made under
# umask 077 leaves it at mode 600, which that user cannot read. The file holds no secret, so make it readable.
# Done first, so it also repairs an installation whose accounts already exist.
[ ! -f "$here/ntfy/server.yml" ] || chmod 644 "$here/ntfy/server.yml"

present=0
for f in "$env_file" "$token_file" "$password_file"; do
  [ -e "$f" ] && present=$((present + 1))
done
if [ "$rotate" = false ]; then
  if [ "$present" -eq 3 ]; then
    echo "ntfy accounts already exist; nothing changed (use --rotate to replace every secret):"
    echo "  $env_file"
    echo "  $token_file"
    echo "  $password_file"
    exit 0
  fi
  if [ "$present" -ne 0 ]; then
    echo "ntfy-init: only some of the files exist; remove them or use --rotate" >&2
    exit 1
  fi
fi

command -v docker >/dev/null 2>&1 || { echo "ntfy-init: docker is required (bcrypt hash)" >&2; exit 1; }
command -v openssl >/dev/null 2>&1 || { echo "ntfy-init: openssl is required" >&2; exit 1; }

# The image is read from compose.yaml so that the hash is made by the exact server that will check it.
image="$(sed -n 's/^[[:space:]]*image:[[:space:]]*\(binwiederhier\/ntfy[^[:space:]]*\)[[:space:]]*$/\1/p' "$here/compose.yaml" | head -n 1)"
[ -n "$image" ] || { echo "ntfy-init: no ntfy image in compose.yaml" >&2; exit 1; }

random_alnum() { openssl rand -base64 96 | tr -dc 'A-Za-z0-9' | cut -c1-"$1"; }

# bcrypt through the ntfy image. The password goes in on stdin (printf is a shell builtin, so it never
# appears in a process list); the prompts are discarded and only the hash is kept.
hash_password() {
  printf '%s\n%s\n' "$1" "$1" \
    | docker run --rm -i --network none --entrypoint ntfy "$image" user hash 2>/dev/null \
    | tr '\r' '\n' | grep -o '\$2[aby]\$[^[:space:]]*' | tail -n 1
}

sidekick_password="$(random_alnum 40)"   # nobody needs it: Sidekick publishes with the token
phone_password="$(random_alnum 24)"
token="tk_$(random_alnum 29)"
sidekick_hash="$(hash_password "$sidekick_password")"
phone_hash="$(hash_password "$phone_password")"
[ -n "$sidekick_hash" ] && [ -n "$phone_hash" ] || { echo "ntfy-init: could not create the password hashes" >&2; exit 1; }
unset sidekick_password

mkdir -p "$secrets_dir" "$(dirname "$env_file")"
chmod 700 "$secrets_dir"

# Written to a temporary name and moved into place, so an interrupted run leaves no half file.
write_file() { # path, content (one line)
  tmp="$1.tmp.$$"
  printf '%s\n' "$2" > "$tmp"
  chmod 600 "$tmp"
  mv -f "$tmp" "$1"
}
write_file "$token_file" "$token"
write_file "$password_file" "$phone_password"
tmp="$env_file.tmp.$$"
{
  echo "# Written by ntfy-init.sh. Contains secrets: keep mode 600 and out of git."
  printf "NTFY_AUTH_USERS='sidekick:%s:user,phone:%s:user'\n" "$sidekick_hash" "$phone_hash"
  printf "NTFY_AUTH_TOKENS='sidekick:%s:sidekick'\n" "$token"
} > "$tmp"
chmod 600 "$tmp"
mv -f "$tmp" "$env_file"
unset token phone_password sidekick_hash phone_hash

# One path per call: `git check-ignore -q` accepts only a single path. Exit 1 means "not ignored"; other codes
# (not a repository, path outside it) say nothing about it and give no warning.
if command -v git >/dev/null 2>&1; then
  for f in "$env_file" "$token_file" "$password_file"; do
    rc=0
    git -C "$(dirname "$f")" check-ignore -q "$f" 2>/dev/null || rc=$?
    [ "$rc" -ne 1 ] || echo "ntfy-init: WARNING: $f is not gitignored; never commit it" >&2
  done
fi

echo "ntfy accounts written (nothing secret is shown here):"
echo "  $env_file                (read by the ntfy service)"
echo "  $token_file              (for SIDEKICK_PUSH_AUTH_TOKEN in selfhost.env)"
echo "  $password_file           (for the ntfy app on the phone, user: phone)"
[ "$custom_layout" = true ] || echo "Next: docker compose --env-file selfhost.env --profile push up -d  (restart ntfy and push after --rotate)"
