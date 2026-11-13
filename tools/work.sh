#!/usr/bin/env bash
# "Sidekick Work": Sidekick isolated on a work laptop, used from Claude Desktop through a local MCP server, with every
# model call going to the company's own OpenAI-compatible server (vLLM) and nowhere else.
# Platforms: written for Ubuntu (Linux with Docker Engine) and for macOS (Docker Desktop). Linux has been drilled on
# real containers (see docs/maintainers/verification.md); macOS has never been run.
# Compose overlay: deploy/work/compose.yaml on top of deploy/selfhost/compose.yaml, project sidekick-work.
# Docs: docs/start/work-laptop.sv.md and docs/start/work-laptop.md. Touches only the compose project sidekick-work.
# Portable bash: runs on bash 3.2 (macOS) and on Ubuntu; no associative arrays, no mapfile, no GNU-only flags.
#
#   bash tools/work.sh setup               interactive guide: language, model server, models, allowed addresses,
#                                          rooms, autostart; writes work.env; safe to run again
#   bash tools/work.sh init [--model-key]  copy work.env, generate secrets into deploy/work/secrets/ (700/600);
#                                          --model-key asks for the model server's API key again
#   bash tools/work.sh start [--build [--no-cache]]
#                                          build the image if missing (or with --build), start the stack, create the
#                                          owner user and write the Claude Desktop configuration (stdio, no token)
#   bash tools/work.sh claude-config       preview and confirm merging the entry into Claude Desktop; backs up first
#   bash tools/work.sh stop [--purge]      stop and remove containers; --purge also deletes data and secrets (asks)
#   bash tools/work.sh status              health, proof that the egress is closed, the model ids the server offers
#   bash tools/work.sh backup              dump the database and copy Hindsight's memory into deploy/work/backups/, both
#                                          encrypted with a key kept apart (deploy/work/secrets/backup.key); a backup counts
#                                          only after it was decrypted and checked again
#   bash tools/work.sh autostart on|off    start at login: systemd user unit (Linux) or launchd agent (macOS)
#   bash tools/work.sh update [--allow-breaking-migration]
#                                          backup (database and memory), git pull --ff-only, check the migration class,
#                                          build/pull, migrate, restart
#   bash tools/work.sh restore [SET] [--apply]
#                                          put the database and Hindsight's memory back from one backup set (a time
#                                          stamp or a path to either file; needs the same key); without --apply it only checks the set
#                                          and shows the plan; --apply asks for the project name, backs up first and
#                                          puts the previous data back if a step fails
#
# Texts are in Swedish or English: SIDEKICK_WORK_LANG, else SIDEKICK_WORK_LOCALE in work.env, else the system LANG.
# Compose output goes to deploy/work/work.log (a file, never a pipe); the last lines are shown on failure.
# No command prints a secret. The database passwords and the model key live only in files with mode 600.
# The whole script is one function call, so `update` can replace this very file without breaking the running copy.
set -euo pipefail
CALLER_UMASK="$(umask)"
umask 077

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY="$REPO/deploy"
SELFHOST="$DEPLOY/selfhost"
WORK="$DEPLOY/work"
WORK_ENV="$WORK/work.env"
SECRETS="$WORK/secrets"
GEN="$WORK/generated"
BACKUPS="$WORK/backups"
LOG="$WORK/work.log"
PROJECT="${SIDEKICK_WORK_PROJECT:-sidekick-work}"
GATEWAY_NAME=model.work.internal
KEEP_BACKUPS="${SIDEKICK_WORK_KEEP_BACKUPS:-7}"
# The exact form of a finished backup file: only such names are measured and pruned.
DB_ERE='sidekick-[0-9]{8}-[0-9]{6}\.sql\.enc'
MEM_ERE='hindsight-[0-9]{8}-[0-9]{6}\.tar\.gz\.enc'
ALLOW_PARSED=""
L=sv
DEFAULT_ROOMS="work,journal,contacts,control"

# The logic that moved to Python (tools/workctl, standard library only, see its docstring). No bytecode is written into
# the checkout; the secrets travel on stdin, never on a command line.
workctl() { PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$REPO/tools${PYTHONPATH:+:$PYTHONPATH}" python3 -m workctl "$@"; }

# The options of start, update and restore: workctl prints NAME=value lines, which become OPT_<NAME>. A call it refuses
# prints the usage text and ends the script with 2.
parse_options() {
  local out line
  out="$(workctl parse-args --lang "$L" -- "$@")" || exit 2
  while IFS= read -r line; do
    if [ -n "$line" ]; then printf -v "OPT_${line%%=*}" '%s' "${line#*=}"; fi
  done <<<"$out"
}

# The decision about a container's state is the self-hosted updater's, one copy (deploy/selfhost/update_policy.py).
policy() { python3 -I "$SELFHOST/update_policy.py" "$@"; }

now() { date +%Y-%m-%dT%H:%M:%S; }
now_utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }

compose() {
  local args
  args=(-p "$PROJECT" --project-directory "$SELFHOST" -f "$SELFHOST/compose.yaml" -f "$WORK/compose.yaml")
  if [ -f "$GEN/allow.compose.yaml" ]; then args+=(-f "$GEN/allow.compose.yaml"); fi
  # The self-hosted file demands a domain for its Caddy service (profile vps, never used here), even to parse.
  # The memory profile (Hindsight, memory worker) only when memory is on; `stop` forces it so `down` also removes
  # containers started while it was on.
  if [ "$MEMORY" = 1 ] || [ "$FORCE_MEMORY_PROFILE" = 1 ]; then args+=(--profile memory); fi
  SELFHOST_DOMAIN=work.invalid docker compose "${args[@]}" --env-file "$WORK_ENV" "$@"
}

# ---------------------------------------------------------------------------------------------------------
# Texts, one table (tools/workctl/messages.json). Language in $L (sv or en); a key without a text is printed as itself.
# %s are filled by sayf/errf.
msg() { workctl text --lang "$L" -- "$1"; }

say() { printf '%s\n' "$(msg "$1")"; }
# sayf KEY args...: the text as a printf format on stdout; errf: the same on stderr.
sayf() { local f; f="$(msg "$1")"; shift; printf "$f\n" "$@"; }
errf() { local f; f="$(msg "$1")"; shift; printf "$f\n" "$@" >&2; }

# Language of the texts: SIDEKICK_WORK_LANG, else SIDEKICK_WORK_LOCALE in work.env, else the system language.
init_lang() {
  local v="${SIDEKICK_WORK_LANG:-}"
  if [ -z "$v" ]; then v="$(envval SIDEKICK_WORK_LOCALE)"; fi
  if [ -z "$v" ]; then v="${LANG:-}"; fi
  case "$v" in sv*|SV*) L=sv ;; *) L=en ;; esac
}

need_docker() { command -v docker >/dev/null 2>&1 || { errf no_docker; exit 1; }; }
need_tool() { command -v "$1" >/dev/null 2>&1 || { errf no_tool "$1"; exit 1; }; }

warn_strict_umask() {
  if [ "$((8#$CALLER_UMASK & 0755))" -ne 0 ]; then errf strict_umask "$CALLER_UMASK"; fi
}

# One plain value from work.env (last assignment wins, quotes stripped). Never sourced: values hold spaces.
envval() {
  workctl env-value --env-file "$WORK_ENV" -- "$1"
}

# MEMORY is 1 when the Hindsight memory is on (SIDEKICK_WORK_MEMORY=on|off in work.env, see `derive`).
MEMORY=0
FORCE_MEMORY_PROFILE=0

# Derive everything compose needs from work.env and export it (workctl derive prints MEMORY=0|1, NAME=value lines
# and "allow host port" lines). Strict: refuses a placeholder or a bad address. With "lenient" (stop) an unusable
# work.env is not an error, because compose only needs the names to parse.
derive() {
  local lenient="${1:-}" out line
  out="$(workctl derive --env-file "$WORK_ENV" --gen-dir "$GEN" --lang "$L" ${lenient:+--lenient})" || exit 1
  ALLOW_PARSED=""
  while IFS= read -r line; do
    case "$line" in
      MEMORY=*) MEMORY="${line#MEMORY=}" ;;
      "allow "*) ALLOW_PARSED="${ALLOW_PARSED:+$ALLOW_PARSED$'\n'}${line#allow }" ;;
      *) export "${line%%=*}=${line#*=}" ;;
    esac
  done <<<"$out"
}

# Files compose mounts that depend on settings: the gateway configuration with one passthrough listener per
# allowed address, the matching network aliases, and the build information file (created if missing).
render_generated() {
  # The shared selfhost entrypoint also copies this file with mode 755 before dropping privileges.
  chmod 755 "$SELFHOST/postgres-init.sh"
  # The gateway container runs as an unprivileged user, so what it mounts must be world-readable despite umask 077.
  mkdir -p "$GEN"
  chmod 755 "$GEN"
  workctl render-gateway --template "$WORK/gateway.haproxy.cfg" --out-dir "$GEN" --allow "$ALLOW_PARSED"
  chmod 644 "$GEN/gateway.haproxy.cfg"
  if [ -f "$GEN/allow.compose.yaml" ]; then chmod 644 "$GEN/allow.compose.yaml"; fi
  ensure_build_info
}

# The build information file must exist before compose mounts it (a missing file would become a directory), and
# from the first day on, so the update reminder has a date to count from.
ensure_build_info() {
  mkdir -p "$GEN"
  chmod 755 "$GEN"
  if [ ! -f "$GEN/build-info.json" ]; then write_build_info; fi
}

# build-info.json: which commit this checkout is on, when the image was built and when it was last updated.
# Mounted read-only into the api at /etc/sidekick/build-info.json (SIDEKICK_BUILD_INFO_FILE) for the interface to read.
write_build_info() {
  local commit date
  commit="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || echo unknown)"
  date="$(git -C "$REPO" log -1 --format=%cI 2>/dev/null || echo unknown)"
  mkdir -p "$GEN"
  workctl build-info --path "$GEN/build-info.json" --commit "$commit" --commit-date "$date" --now "$(now_utc)" \
    --previous "${1:-}" --updated "${2:-}"
  chmod 644 "$GEN/build-info.json"
}

ensure_work_env() {
  if [ ! -f "$WORK_ENV" ]; then
    cp "$WORK/work.env.example" "$WORK_ENV"
    chmod 600 "$WORK_ENV"
    say env_created
    return 1
  fi
}

secrets_exist() { [ -f "$SECRETS/sidekick.env" ] && [ -f "$SECRETS/db.env" ] && [ -f "$SECRETS/hindsight.env" ]; }

ensure_secrets() {
  secrets_exist && return 0
  errf no_secrets
  exit 1
}

# Write the model server's API key into the two 600 files; an empty key means "the server checks nothing".
# The api container only gets it for the status probe, under a name without the SIDEKICK_ prefix (Settings refuses
# unknown SIDEKICK_ names).
apply_model_key() {
  printf '%s' "$1" | workctl model-key-apply --secrets-dir "$SECRETS"
}

# SIDEKICK_WORK_MODEL_API_KEY in the environment, else asked for on a terminal (no echo), else none.
store_model_key() {
  local key="${SIDEKICK_WORK_MODEL_API_KEY:-}"
  if [ -z "$key" ] && [ -t 0 ]; then
    key="$(workctl ask --lang "$L" --key model_key_ask --raw --secret)" || exit 1
  fi
  apply_model_key "$key"
  if [ -n "$key" ]; then
    sayf model_key_saved "$SECRETS"
  else
    say model_key_none
  fi
}

generate_secrets() {
  local f legacy_env
  legacy_env="char""lie.env"
  # Never overwrite: a secrets file left by an older version (see legacy_env) or an interrupted init would otherwise lose
  # the database passwords of a database that already exists. -e, not -f: a symlink or odd file counts too.
  for f in sidekick.env db.env hindsight.env "$legacy_env"; do
    if [ -e "$SECRETS/$f" ] || [ -L "$SECRETS/$f" ]; then errf init_existing "$SECRETS"; exit 1; fi
  done
  # The passwords and keys are generated in Python (tools/workctl) and the files are created with mode 600. Hindsight's own
  # settings are reused from the self-hosted example, so there is one copy of them.
  workctl generate-secrets --secrets-dir "$SECRETS" --hindsight-example "$SELFHOST/hindsight.env.example" \
    --gateway "$GATEWAY_NAME"
}

# SIDEKICK_ENABLED_ROOMS goes into the api container environment only when set in work.env, so a release without
# that setting still starts. The stdio process Claude Desktop starts runs inside the api container (docker exec)
# and so sees the same value.
write_rooms_env() { workctl rooms-env --env-file "$WORK_ENV" --secrets-dir "$SECRETS"; }

container_id() { compose ps -q "$1" 2>/dev/null || true; }

# yes/no with a default (y or n); j/y/ja/yes are yes.
confirm() { workctl confirm --lang "$L" --key "$1" --default "$2"; }

# ---------------------------------------------------------------------------------------------------------

cmd_init() {
  need_docker
  mkdir -p "$SECRETS"
  chmod 700 "$SECRETS"
  ensure_work_env || true
  if ! secrets_exist; then
    generate_secrets
    sayf init_created "$SECRETS"
    store_model_key
  elif [ "${1:-}" = "--model-key" ]; then
    store_model_key
  else
    sayf init_kept "$SECRETS"
    say init_key_hint
  fi
  ensure_build_info
  say init_next
}

# The stdio entry point is part of the image only from the release that added it: an image built earlier must be rebuilt.
check_stdio_entry() {
  compose exec -T api python -c "import sidekick.mcp.stdio" >>"$LOG" 2>&1 || { errf old_image; exit 1; }
}

is_uuid() { workctl is-uuid -- "$1"; }

# One value from the database, whitespace removed. Fails (never "empty") when the database cannot be asked.
db_scalar() {
  local out
  out="$(pg_admin -d sidekick -tAc "$1" 2>>"$LOG")" || return 1
  printf '%s' "$out" | tr -d '[:space:]'
}

# The user Claude Desktop acts as. The database is the truth, secrets/user-id only remembers its UUID: the file counts
# only while that user exists in the database. A user-id left from another database (a new, empty data volume) is
# replaced by the user jobb of this database if it has one, else by a new one. Needs the running api (the database is
# migrated by then). create-user asks for no password and prints the UUID.
ensure_owner() {
  local tmp stored="" found id
  if [ -s "$SECRETS/user-id" ]; then stored="$(tr -d '[:space:]' <"$SECRETS/user-id")"; fi
  if is_uuid "$stored"; then
    found="$(db_scalar "select 1 from sidekick.users where id = '$stored'")" || { errf user_fail "$LOG"; exit 1; }
    if [ "$found" = 1 ]; then return 0; fi
    say owner_stale
  fi
  id="$(db_scalar "select id from sidekick.users where username = 'jobb'")" || { errf user_fail "$LOG"; exit 1; }
  tmp="$(mktemp "$SECRETS/.tmp.XXXXXX")"
  if is_uuid "$id"; then
    printf '%s\n' "$id" >"$tmp"
  elif ! compose exec -T api sidekick-admin create-user --login jobb --display-name "Sidekick Work" \
      </dev/null >"$tmp" 2>>"$LOG" \
      || ! is_uuid "$(tr -d '[:space:]' <"$tmp")"; then
    rm -f "$tmp"
    errf user_fail "$LOG"
    exit 1
  fi
  chmod 600 "$tmp"
  mv "$tmp" "$SECRETS/user-id"
}

# Claude Desktop starts local programs only, with a minimal PATH. The entry runs Sidekick's stdio server inside the
# running api container: `docker exec -i` (not `docker compose exec`, which would need the compose files and every
# derived variable), the docker binary and the container by absolute path/name. The owner is passed with -e; the
# rest of the settings (rooms, database, model routes) are the container's own. No token: the process is trusted
# because the OS user that can run docker already holds the database credentials. The file holds no secret
# but is written 600 like the others.
write_desktop_config() {
  local docker_bin cid name owner out
  docker_bin="$(command -v docker)"
  case "$docker_bin" in /*) ;; *) errf desktop_nodocker; exit 1 ;; esac
  cid="$(container_id api)"
  name="$(docker inspect --format '{{.Name}}' "$cid")"
  name="${name#/}"
  owner="$(tr -d '[:space:]' <"$SECRETS/user-id")"
  out="$SECRETS/claude_desktop_config.json"
  workctl desktop-config --out "$out" --docker "$docker_bin" --container "$name" --owner "$owner"
  sayf desktop_written "$out"
  say desktop_hint
}

desktop_setup() {
  check_stdio_entry
  ensure_owner
  write_desktop_config
}

# This is deliberately separate from setup/start: Claude's settings are changed only after an explicit answer.
# The answer is read from the caller's stdin by workctl.
cmd_claude_config() {
  [ "$#" = 0 ] || { errf usage; exit 2; }
  # The path is decided by workctl: SIDEKICK_WORK_CLAUDE_CONFIG when set (also used by tests so that the real Claude
  # configuration is never touched), else the platform's own place.
  workctl claude-config --lang "$L" --source "$SECRETS/claude_desktop_config.json" --platform "$(uname -s)"
}

# Read-only diagnosis after a failed start: the shell gathers the evidence, workctl (diagnose) decides what it means.
# Logs are inspected in memory, never echoed (they may contain URLs). An absent/empty yoyo table must be confirmed over
# the local superuser socket; an unknown state is never empty.
diagnose_first_start() {
  local start_line="$1" migration_log postgres_log table count="" volume rc=0
  migration_log="$(compose logs --no-color --tail 80 migrate 2>/dev/null || true)"
  postgres_log="$(compose logs --no-color --tail 120 postgres 2>/dev/null || true)"
  # stdin of the check: the evidence, a NUL byte, the postgres log (the check reads all of it).
  { printf '%s\n' "$migration_log"; sed -n "$((start_line + 1)),\$p" "$LOG"; printf '\0%s' "$postgres_log"; } \
    | workctl first-start-evidence || return 0
  table="$(db_scalar "select coalesce(to_regclass('public._yoyo_migration')::text, 'absent')")" || return 0
  workctl first-start-table --table "$table" || rc=$?
  case "$rc" in
    0) ;;
    10) count="$(db_scalar 'select count(*) from public._yoyo_migration')" || return 0 ;;
    *) return 0 ;;
  esac
  volume="$(docker volume ls -q --filter "label=com.docker.compose.project=$PROJECT" \
    --filter 'label=com.docker.compose.volume=pgdata' 2>/dev/null)" || return 0
  workctl first-start-hint --lang "$L" --project "$PROJECT" --volume "$volume" --table "$table" --count "$count" || true
}

cmd_start() {
  warn_strict_umask
  local OPT_BUILD OPT_NO_CACHE OPT_WAIT_DOCKER image i log_start
  local build_args=()
  parse_options start "$@"
  if [ "$OPT_NO_CACHE" = 1 ]; then build_args+=(--no-cache); fi
  need_docker
  ensure_work_env || exit 1
  ensure_secrets
  derive
  write_rooms_env
  if [ "$OPT_WAIT_DOCKER" = 1 ]; then
    # Used by autostart: Docker may still be starting at login. Bounded wait, then give up.
    i=0
    until docker info >/dev/null 2>&1; do
      i=$((i + 1))
      if [ "$i" -gt 60 ]; then errf docker_wait; exit 1; fi
      sleep 5
    done
  fi
  render_generated
  echo "=== $(now) start ===" >>"$LOG"
  image="$(workctl api-image --env-file "$WORK_ENV")"
  if [ "$OPT_BUILD" = 1 ] || ! docker image inspect "$image" >/dev/null 2>&1; then
    sayf building "$image"
    if ! compose build ${build_args[@]+"${build_args[@]}"} api >>"$LOG" 2>&1; then
      errf build_fail "$LOG"
      tail -n 20 "$LOG" >&2 || true
      exit 1
    fi
    write_build_info
  fi
  log_start="$(wc -l <"$LOG")"
  # Memory switched off after it ran: stop Hindsight and the memory worker (the volume is kept).
  if [ "$MEMORY" = 0 ]; then compose stop hindsight memory-worker >>"$LOG" 2>&1 || true; fi
  if ! compose up -d --wait --wait-timeout 420 >>"$LOG" 2>&1; then
    errf up_fail "$LOG"
    tail -n 20 "$LOG" >&2 || true
    diagnose_first_start "$log_start"
    exit 1
  fi
  # The gateway configuration is a mounted file that compose does not watch: restart the gateway when it changed.
  if ! cmp -s "$GEN/gateway.haproxy.cfg" "$GEN/.gateway.applied" 2>/dev/null; then
    compose restart gateway >>"$LOG" 2>&1 || { errf gw_fail "$LOG"; exit 1; }
    cp "$GEN/gateway.haproxy.cfg" "$GEN/.gateway.applied"
  fi
  say started
  desktop_setup
}

cmd_stop() {
  need_docker
  [ -f "$WORK_ENV" ] || cp "$WORK/work.env.example" "$WORK_ENV"
  derive lenient
  FORCE_MEMORY_PROFILE=1
  echo "=== $(now) stop ===" >>"$LOG"
  if [ "${1:-}" = "--purge" ]; then
    local answer
    answer="$(workctl ask --lang "$L" --key purge_q --raw --only-on-terminal)" || exit 1
    [ "$answer" = "$(msg purge_yes)" ] || { say aborted; exit 1; }
    compose down -v >>"$LOG" 2>&1 || { errf down_fail "$LOG"; exit 1; }
    rm -rf "$SECRETS" "$BACKUPS" "$GEN"
    cmd_autostart off >/dev/null
    say purged
  else
    compose down >>"$LOG" 2>&1 || { errf down_fail "$LOG"; exit 1; }
    say stopped
  fi
}

# Runs a probe of tools/workctl inside a container: `python -c` with the file's text (standard library only), then
# the probe's own arguments.
run_probe() {
  local service="$1" python="$2" file="$3"
  shift 3
  compose exec -T "$service" "$python" -c "$(<"$REPO/tools/workctl/$file")" "$@"
}

cmd_status() {
  need_docker
  [ -f "$WORK_ENV" ] || { errf no_work_env; exit 1; }
  derive
  local svc id state port api_id direct_host out hs_id reached blocked direct
  for svc in postgres hindsight memory-worker automation-worker api gateway; do
    if [ "$MEMORY" = 0 ]; then case "$svc" in hindsight|memory-worker) continue ;; esac; fi
    id="$(container_id "$svc")"
    if [ -z "$id" ]; then
      sayf st_not_running "$svc"
      continue
    fi
    state="$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}-{{end}}' "$id" 2>/dev/null || msg st_unknown)"
    echo "$svc: $state"
  done
  if [ "$MEMORY" = 0 ]; then say st_memory_off; fi
  workctl status-version --lang "$L" --build-info "$GEN/build-info.json"
  port="$(envval SIDEKICK_WORK_PORT)"; port="${port:-8765}"
  sayf st_noauth "$(curl -s -o /dev/null -m 10 -w '%{http_code}' -X POST -H 'Content-Type: application/json' -d '{}' "http://127.0.0.1:$port/mcp/" || true)"
  if [ -s "$SECRETS/claude_desktop_config.json" ]; then sayf st_desktop_ok "$SECRETS/claude_desktop_config.json"; else say st_desktop_missing; fi
  api_id="$(container_id api)"
  [ -n "$api_id" ] || { say st_api_down; exit 0; }
  # Egress proof, from inside the containers. Each probe must be refused: the public internet by name and by
  # address, a lookup of a name that certainly exists (an answer means DNS is a way out), and the model server
  # directly (only the gateway may talk to it).
  reached="$(msg st_reached)"; blocked="$(msg st_blocked)"; direct="$(msg st_direct)"
  direct_host="${SIDEKICK_WORK_UPSTREAM_ADDR%:*}"
  if [ "$MEMORY" = 0 ]; then direct_host=""; fi
  say st_probe_api
  run_probe api python probe_egress.py "$direct_host" "$SIDEKICK_WORK_MODEL_PORT" "$reached" "$blocked" "$direct" | sed 's/^/  /' || echo "  $(msg st_probe_fail)"
  hs_id=""
  if [ "$MEMORY" = 1 ]; then hs_id="$(container_id hindsight)"; fi
  if [ -n "$hs_id" ]; then
    say st_probe_hs
    run_probe hindsight /app/api/.venv/bin/python probe_egress.py "$direct_host" "$SIDEKICK_WORK_MODEL_PORT" "$reached" "$blocked" "$direct" | sed 's/^/  /' || echo "  $(msg st_probe_fail)"
  fi
  # Through the gateway: the model list (needs the key from the container's own environment, never printed), and a
  # path outside the base path, which the gateway must refuse.
  if [ "$MEMORY" = 0 ]; then return 0; fi
  say st_via
  out="$(run_probe api python probe_gateway.py "http://$GATEWAY_NAME:$SIDEKICK_WORK_MODEL_PORT$SIDEKICK_WORK_MODEL_PATH" || true)"
  workctl status-via --lang "$L" --wanted-model "$(envval SIDEKICK_WORK_MEMORY_MODEL)" <<<"$out"
}

# ---------------------------------------------------------------------------------------------------------
# Autostart: a systemd user unit (Linux) or a launchd LaunchAgent (macOS), see tools/workctl/autostart.py.
# SIDEKICK_WORK_AUTOSTART_DIR redirects the unit file (tests) and skips systemctl/launchctl.
cmd_autostart() {
  case "${1:-}" in
    on|off|status) workctl autostart --lang "$L" --platform "$(uname -s)" --script "$REPO/tools/work.sh" \
      --log "$WORK/autostart.log" "$1" ;;
    *) errf as_usage; exit 2 ;;
  esac
}

# ---------------------------------------------------------------------------------------------------------
# Backup: the database (pg_dump) and Hindsight's memory. Hindsight keeps its data in an embedded Postgres in the
# volume hindsight_pg0 (deploy/selfhost/compose.yaml); a copy of live database files is not consistent, so
# Hindsight is stopped for the few seconds the volume is archived (tar, run from the pinned Hindsight image
# itself, offline) and started again. Both files get the same timestamp. If either fails, nothing is kept and
# the caller stops.

# Encryption of the backups: the mechanism of the encrypted database snapshots in deploy/selfhost/update.sh (Fernet,
# run in a one-off api container from the image that is already here; the code is deploy/selfhost/snapshot_crypto.py).
# The key is a file of its own, generated on the first backup, mode 600, and kept OUT of the backup directory
# (default deploy/work/secrets/backup.key; SIDEKICK_WORK_BACKUP_KEY_FILE moves it, for example to a mounted key store).
# It is a different key from SIDEKICK_BACKUP_ENCRYPTION_KEY of a self-hosted installation. Its content is read into a
# variable for one command and reaches the container through the environment (docker compose run -e NAME takes the
# value from this process), never through a command line, the log or the terminal. No plain dump or archive is
# written to disk: pg_dump and tar are piped straight into the encryption.
BACKUP_KEY_FILE="${SIDEKICK_WORK_BACKUP_KEY_FILE:-$SECRETS/backup.key}"
CRYPTO_SCRIPT="$SELFHOST/snapshot_crypto.py"

# stdin to stdout through the api image: $1 = encrypt|decrypt. Non-zero on any failure (no key, wrong key, damaged data).
backup_crypto() {
  local key
  key="$(tr -d '[:space:]' <"$BACKUP_KEY_FILE" 2>/dev/null)" || return 1
  [ -n "$key" ] || return 1
  SIDEKICK_BACKUP_ENCRYPTION_KEY="$key" compose run --rm -T --no-deps -e SIDEKICK_BACKUP_ENCRYPTION_KEY api \
    python -I -c "$(cat "$CRYPTO_SCRIPT")" "$1" 2>>"$LOG"
}

# Makes a file, or a directory entry, durable: `sync PATH` (coreutils) flushes that one file or directory to disk,
# older or other implementations ignore the argument and flush everything. Used on a finished backup file before it is
# renamed into place and on the directory after the rename (and after pruning), so a power loss cannot leave a name
# that points at data that was never written, and cannot bring a pruned old backup back or lose the new name.
fsync_path() { sync "$1" 2>/dev/null || sync; }

# Fails closed (exit 1, nothing changed) unless a usable key file exists. A missing key is never replaced silently while
# encrypted backups exist: a new key would make them unreadable. $1 = generate: create the key when there is no backup.
require_backup_key() {
  workctl backup-key --lang "$L" --key-file "$BACKUP_KEY_FILE" --backups-dir "$BACKUPS" ${1:+--generate} || exit 1
}

# The proof that a backup is usable: decrypt it again (Fernet authenticates the whole file, so a damaged or wrongly
# keyed file fails) and look at what is inside. Nothing is written to disk. pipefail makes a failing decryption fail the check.
verify_dump() { backup_crypto decrypt <"$1" | grep 'PostgreSQL database dump complete' >/dev/null; }
verify_archive() { backup_crypto decrypt <"$1" | tar -tz 2>>"$LOG" | grep . >/dev/null; }

# The volume compose created for hindsight_pg0 in this project, or nothing.
# ---------------------------------------------------------------------------------------------------------
# One lock for the commands that change the stack (setup, init, start, stop, backup, update, restore --apply), so that
# none of them can start Hindsight or the writers in the middle of another. status, autostart and the dry run of
# restore take no lock. flock on $LOCK_FILE where it exists (released by the kernel on any exit); otherwise (macOS
# has no flock by default) a mkdir lock in $LOCK_DIR holding "PID command", taken over only when that PID is gone.
LOCK_FILE="$WORK/.work.lock"
LOCK_DIR="$WORK/.work.lock.d"
LOCK_HELD=""     # flock or dir while this process holds the lock
LOCK_COMMAND=""  # the command that takes it, written next to the PID

lock_busy() { errf busy "${1:-?}" "$2"; exit 1; }

take_lock() { # $1 = the command; exits 1 with a message when another changing command holds the lock
  local holder pid stale_id moved
  if [ -z "${SIDEKICK_WORK_NO_FLOCK:-}" ] && command -v flock >/dev/null 2>&1; then
    exec 9>>"$LOCK_FILE"
    flock -n 9 || lock_busy "$(head -n 1 "$LOCK_FILE" 2>/dev/null || true)" "$LOCK_FILE"
    printf 'PID %s: %s\n' "$$" "$1" >"$LOCK_FILE"
    LOCK_HELD=flock
    return 0
  fi
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    stale_id="$(ls -di "$LOCK_DIR" 2>/dev/null | cut -d' ' -f1)"  # read before the owner line, see the takeover below
    holder="$(head -n 1 "$LOCK_DIR/owner" 2>/dev/null || true)"
    # The holder writes its line right after mkdir; give a holder that has just started a moment to do so.
    if [ -z "$holder" ]; then sleep 1; holder="$(head -n 1 "$LOCK_DIR/owner" 2>/dev/null || true)"; fi
    pid="${holder#PID }"; pid="${pid%%:*}"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then lock_busy "$holder" "$LOCK_DIR"; fi
    # The holder is gone (stale lock). Take it over so that a lock somebody else has just taken is never deleted:
    # rename is atomic and succeeds for one taker only; the renamed directory must still be the stale one we read
    # (same owner line and inode), otherwise it is another process's live lock and goes straight back.
    moved="$LOCK_DIR.stale.$$"
    rm -rf "$moved"
    mv "$LOCK_DIR" "$moved" 2>/dev/null || lock_busy "" "$LOCK_DIR"
    if [ "$(head -n 1 "$moved/owner" 2>/dev/null || true)" = "$holder" ] \
      && [ "$(ls -di "$moved" 2>/dev/null | cut -d' ' -f1)" = "$stale_id" ]; then
      rm -rf "$moved"
    else
      [ -e "$LOCK_DIR" ] || mv "$moved" "$LOCK_DIR" 2>/dev/null || true
      lock_busy "$(head -n 1 "$LOCK_DIR/owner" 2>/dev/null || true)" "$LOCK_DIR"
    fi
    mkdir "$LOCK_DIR" 2>/dev/null || lock_busy "" "$LOCK_DIR"
  fi
  printf 'PID %s: %s\n' "$$" "$1" >"$LOCK_DIR/owner"
  LOCK_HELD=dir
}

release_lock() { # the mkdir lock only, and only while it is still ours; flock is released when the process ends
  if [ "$LOCK_HELD" = dir ] && [ "$(head -n 1 "$LOCK_DIR/owner" 2>/dev/null || true)" = "PID $$: ${LOCK_COMMAND:-}" ]; then
    rm -rf "$LOCK_DIR"
  fi
  LOCK_HELD=""
}

# arm_traps HANDLER: HANDLER runs on every way out (an interrupt, a closed terminal, kill, an error), then the lock is
# released. disarm_traps goes back to releasing the lock only. INT, TERM and HUP become exits so the EXIT trap runs.
# The handler writes to the terminal (fds 7 and 8, saved by main): a signal can arrive inside a function whose
# output goes to the log, and the trap would otherwise inherit that redirection.
arm_traps() {
  # The handler name is read now, when the trap is armed: that is the point of arm_traps.
  # shellcheck disable=SC2064
  trap "$1 >&7 2>&8; release_lock" EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  trap 'exit 129' HUP
}
disarm_traps() { arm_traps :; }

hindsight_volume() {
  docker volume ls -q --filter "label=com.docker.compose.project=$PROJECT" \
    --filter "label=com.docker.compose.volume=hindsight_pg0" 2>/dev/null | head -n 1
}

# The pinned Hindsight image of this stack (its tar and sh are used offline on the volume), or nothing.
hindsight_image() {
  compose config --images 2>>"$LOG" | grep 'vectorize-io/hindsight' | head -n 1 || true
}

backup_database() {
  local out="$1"
  ( umask 077; : >"$out.part" ) && chmod 600 "$out.part" || return 1
  if ! compose exec -T postgres pg_dump -U postgres -d sidekick --no-owner 2>>"$LOG" | backup_crypto encrypt >"$out.part" \
      || [ ! -s "$out.part" ]; then
    rm -f "$out.part"
    return 1
  fi
  if ! verify_dump "$out.part"; then
    errf bk_verify_fail "$out" "$LOG"
    rm -f "$out.part"
    return 1
  fi
  # Verified, so now durable: flush the file, rename it into place, flush the directory entry.
  chmod 600 "$out.part"
  fsync_path "$out.part"
  mv "$out.part" "$out"
  fsync_path "$BACKUPS"
}

# Services that write to Postgres or feed Hindsight. They are paused for the whole backup (both copies), so the
# database dump and the Hindsight archive describe the same moment. Postgres and Hindsight stay up until their copy.
WRITERS=(api memory-worker automation-worker)
PAUSED_WRITERS=()      # the WRITERS that were running when the backup began; started again on every way out
HINDSIGHT_PAUSED=0
PARTIAL_BACKUP_FILES=""

# Ids of the containers of service $1 that are, or may become, active. Every status counts, not only "running": a
# writer in a restart loop is "restarting" between two attempts and Docker starts it again during the copies; a
# paused one is still alive; a created one starts by itself when it has a restart policy. Non-zero when compose or
# docker cannot tell (the caller fails closed). Same rule as live_containers() in deploy/selfhost/update.sh.
live_writer_containers() {
  local cids cid line answer
  cids="$(compose ps -a -q "$1" 2>>"$LOG")" || return 1
  for cid in $cids; do
    line="$(docker inspect -f '{{.State.Status}} {{.HostConfig.RestartPolicy.Name}}' "$cid" 2>>"$LOG")" || return 1
    # Only the word "inactive" means not active; a crash or no output is no answer, never "not active".
    answer="$(policy container-active --inspect-line="$line")" || return 1
    case "$answer" in
      active) echo "$cid" ;;
      inactive) ;;
      *) return 1 ;;
    esac
  done
}

# [message key]; stops every writer that is or may become active, then checks that none is and none can start again
# by itself. Fails closed: non-zero (the caller aborts before changing anything, the trap starts the paused ones
# again) if compose or docker cannot tell which writers are active, if the stop fails, or if any writer is still
# active afterwards. Used by backup, update and restore.
pause_writers() {
  local svc listed
  PAUSED_WRITERS=()
  for svc in "${WRITERS[@]}"; do
    listed="$(live_writer_containers "$svc")" || { errf writers_unknown "${WRITERS[*]}" "$LOG"; return 1; }
    if [ -n "$listed" ]; then PAUSED_WRITERS+=("$svc"); fi
  done
  if [ "${#PAUSED_WRITERS[@]}" -gt 0 ]; then
    sayf "${1:-bk_writers_pause}" "${PAUSED_WRITERS[*]}"
    compose stop "${PAUSED_WRITERS[@]}" >>"$LOG" 2>&1 || return 1
  fi
  for svc in "${WRITERS[@]}"; do
    listed="$(live_writer_containers "$svc")" || { errf writers_unknown "${WRITERS[*]}" "$LOG"; return 1; }
    [ -z "$listed" ] || { errf writers_still "${WRITERS[*]}"; return 1; }
  done
}

resume_writers() { # starts the paused writers again (waits until healthy); idempotent, the list is emptied only on success
  [ "${#PAUSED_WRITERS[@]}" -gt 0 ] || return 0
  compose up -d --wait --wait-timeout 300 "${PAUSED_WRITERS[@]}" >>"$LOG" 2>&1 && PAUSED_WRITERS=()
}

# Starts Hindsight again (also the way out of a pause, see backup_memory).
resume_hindsight() {
  [ "$HINDSIGHT_PAUSED" = 1 ] || return 0
  # The gateway now depends on api: do not restart paused writers through Hindsight's dependencies.
  compose up -d --wait --wait-timeout 300 --no-deps hindsight >>"$LOG" 2>&1 && HINDSIGHT_PAUSED=0
}

# EXIT trap for the whole backup: an interrupt (Ctrl-C, a closed terminal, kill) or an unexpected error cannot
# leave the memory or the writers stopped, and no half-made backup files are kept.
abort_paused_backup() {
  local f
  trap - EXIT INT TERM HUP
  for f in $PARTIAL_BACKUP_FILES; do rm -f "$f"; done
  resume_hindsight || true
  resume_writers || true
}

# Archive the volume into $1 (a .tar.gz). Prints nothing when there is no volume yet; returns 1 on any failure,
# after Hindsight has been started again. The trap set by do_backup guarantees the restart on every other way out.
backup_memory() {
  local out="$1" vol image ok=1
  if [ "$MEMORY" = 0 ]; then say bk_mem_off; return 0; fi
  vol="$(hindsight_volume)"
  if [ -z "$vol" ]; then say bk_mem_none; return 0; fi
  image="$(hindsight_image)"
  [ -n "$image" ] || return 1
  say bk_mem_pause
  PARTIAL_BACKUP_FILES="$out.part $PARTIAL_BACKUP_FILES"
  # The encrypted archive is created private (0600) before a byte is written, whatever the umask.
  ( umask 077; : >"$out.part" ) && chmod 600 "$out.part" || { rm -f "$out.part"; return 1; }
  HINDSIGHT_PAUSED=1
  if ! compose stop hindsight >>"$LOG" 2>&1 \
      || ! docker run --rm --network none -v "$vol:/src:ro" --entrypoint tar "$image" -C /src -czf - . 2>>"$LOG" \
        | backup_crypto encrypt >"$out.part" \
      || [ ! -s "$out.part" ]; then
    rm -f "$out.part"
    ok=0
  fi
  resume_hindsight || ok=0
  # Hindsight is up again; only now the (slower) read-back of the encrypted archive.
  if [ "$ok" = 1 ] && ! verify_archive "$out.part"; then
    errf bk_verify_fail "$out" "$LOG"
    rm -f "$out.part"
    ok=0
  fi
  PARTIAL_BACKUP_FILES="${PARTIAL_BACKUP_FILES#"$out.part "}"
  [ "$ok" = 1 ] || return 1
  chmod 600 "$out.part"
  fsync_path "$out.part"
  mv "$out.part" "$out"
  fsync_path "$BACKUPS"
  sayf bk_mem_ok "$out"
}

# Keeps the newest $KEEP_BACKUPS of each kind (the time stamp in the name sorts by time, so the order does not depend on
# file times that a copy or a restore can change). Called only after a backup set was written, read back and
# renamed into place, and never deletes the files of that set (LAST_BACKUP_DB and LAST_BACKUP_MEM), whatever
# KEEP_BACKUPS is. Does nothing when the newest set is not there, so a failed backup never prunes older ones.
prune_backups() {
  [ -s "$LAST_BACKUP_DB" ] || return 0
  workctl backup-prune --dir "$BACKUPS" --keep "$KEEP_BACKUPS" --pattern "$DB_ERE" --protected "$(basename "$LAST_BACKUP_DB")" >/dev/null || true
  workctl backup-prune --dir "$BACKUPS" --keep "$KEEP_BACKUPS" --pattern "$MEM_ERE" --protected "$(basename "$LAST_BACKUP_MEM")" >/dev/null || true
  fsync_path "$BACKUPS"
}

# Used by `backup`, `update` and `restore`. Prints where the files went; exits 1 (the caller must not go on) on any
# failure. Order: pause the writers, dump the database, archive Hindsight (paused inside), start both again. The trap
# starts everything again and removes half-made files on every way out. With --keep-paused (restore) nothing is
# pruned, the writers stay paused and the trap stays set: the caller takes both over. The files are in LAST_BACKUP_*.
LAST_BACKUP_TS=""
LAST_BACKUP_DB=""
LAST_BACKUP_MEM=""
BACKUP_TRAP=abort_paused_backup  # the EXIT handler of the backup; `update` sets its own, which also knows the image and the code
do_backup() {
  local ts db mem keep_paused=0
  if [ "${1:-}" = --keep-paused ]; then keep_paused=1; fi
  mkdir -p "$BACKUPS"
  chmod 700 "$BACKUPS"
  # Fails closed before anything is paused or started: a bad number of sets to keep, too little room.
  workctl backup-preflight --lang "$L" --dir "$BACKUPS" --keep "$KEEP_BACKUPS" \
    --pattern "$DB_ERE" --pattern "$MEM_ERE" || exit 1
  require_backup_key generate  # fails closed before anything is paused or started
  if [ -z "$(container_id postgres)" ]; then
    compose up -d --wait postgres >>"$LOG" 2>&1 || { errf bk_db_start "$LOG"; exit 1; }
  fi
  ts="$(workctl backup-stamp --dir "$BACKUPS")"
  db="$BACKUPS/sidekick-$ts.sql.enc"
  mem="$BACKUPS/hindsight-$ts.tar.gz.enc"
  if [ "$MEMORY" = 0 ]; then mem=""; fi
  arm_traps "$BACKUP_TRAP"
  pause_writers || { errf bk_fail "$LOG"; exit 1; }
  PARTIAL_BACKUP_FILES="$db.part"
  if ! backup_database "$db"; then errf bk_fail "$LOG"; exit 1; fi
  sayf bk_db_ok "$db"
  PARTIAL_BACKUP_FILES="$db"
  if ! backup_memory "$mem"; then
    errf bk_fail "$LOG"
    exit 1
  fi
  PARTIAL_BACKUP_FILES=""
  LAST_BACKUP_TS="$ts"; LAST_BACKUP_DB="$db"; LAST_BACKUP_MEM="$mem"
  if [ "$keep_paused" = 1 ]; then return 0; fi
  # The trap stays active until the writers are up: a TERM during the restart still ends in a second, harmless attempt.
  if ! resume_writers; then
    errf bk_writers_fail "${WRITERS[*]}" "$LOG"
    exit 1
  fi
  disarm_traps
  prune_backups
  sayf bk_keep "$KEEP_BACKUPS" "$BACKUPS"
}

cmd_backup() {
  need_docker
  ensure_work_env || exit 1
  ensure_secrets
  derive
  echo "=== $(now) backup ===" >>"$LOG"
  do_backup
}

# Run inside the api container; exit 0 = ready. The same code as READINESS_PY in deploy/selfhost/update.sh and as the
# selfhost api healthcheck (a test keeps them equal). 1) The running api process must answer HTTP within 3 s: 2xx, or
# the intended 404 (the public surface hides /health/* in github_oauth mode); any other status or a hung process fails.
# 2) If the image has the readiness module, the database must answer with the runtime role and the schema must be at
# the image's revision. The container merely being up is not enough.
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

wait_ready() { # 0 once the api passes the readiness check, 1 after the timeout
  local timeout="${SIDEKICK_WORK_READY_TIMEOUT:-180}" deadline
  deadline=$((SECONDS + timeout))
  sayf up_ready_wait "$timeout"
  while :; do
    if compose exec -T api python -c "$READINESS_PY" >>"$LOG" 2>&1; then return 0; fi
    [ "$SECONDS" -lt "$deadline" ] || return 1
    sleep "${SIDEKICK_WORK_READY_POLL:-3}"
  done
}

# The migration class of an update, as deploy/selfhost/update.sh decides it from the image label: the new code may only
# bring migrations the old code can still run against (expand-only) unless --allow-breaking-migration is given.
# This package builds its image from the checkout and has no label, so tools/check-release-migration-class.py
# compares the migrations since the commit that was installed ($1). Output goes to the log; returns the script's code.
check_migration_class() {
  local class=expand rc=0
  [ "$2" = 1 ] && class=breaking
  python3 "$REPO/tools/check-release-migration-class.py" --release-class "$class" --installed "$1" >>"$LOG" 2>&1 || rc=$?
  [ "$rc" -eq 0 ] && return 0
  tail -n 20 "$LOG" >&2 || true
  if [ "$rc" -eq 1 ]; then errf up_contract "$LOG"; else errf up_class_fail "$LOG"; fi
  return "$rc"
}

# State of a running `update`, read by its EXIT trap. UPDATE_PHASE: pre = nothing has been migrated (every way out puts the
# previous version back), migrating = the migration has begun or may have (every way out leaves the writers stopped).
UPDATE_PHASE=pre
PREV_IMAGE=""        # the image that ran before the update (its id); empty when there was none
PREV_IMAGE_TAG=""    # the tag that keeps it: repository:previous
CUR_IMAGE=""         # the tag the stack runs from, which `compose build` moves to the new image
UPDATE_BUILT=0       # the build ran, so CUR_IMAGE may point at the new image
RETAG_FAILED=0       # putting the previous image back under CUR_IMAGE failed, so a restart runs the new build
UPDATE_BEFORE=""     # the commit the checkout was on; the code goes back to it on every failure before the migration

# The image name the stack runs from and a tag that keeps what runs now, before the build moves the name on.
save_previous_image() {
  CUR_IMAGE="$(workctl api-image --env-file "$WORK_ENV")"
  PREV_IMAGE="$(docker image inspect -f '{{.Id}}' "$CUR_IMAGE" 2>/dev/null)" || PREV_IMAGE=""
  [ -n "$PREV_IMAGE" ] || return 0
  PREV_IMAGE_TAG="$(workctl previous-image-tag -- "$CUR_IMAGE")"
  if docker tag "$PREV_IMAGE" "$PREV_IMAGE_TAG" >>"$LOG" 2>&1; then
    sayf up_prev_saved "$PREV_IMAGE_TAG"
  else
    PREV_IMAGE=""; PREV_IMAGE_TAG=""
  fi
}

# EXIT trap of `update`. Before the migration: the code goes back to the commit it came from, the previous image is put
# back under its name (a build may have moved it) and the writers, if the backup had stopped them, start again from it.
# From the migration on, the writers stay stopped and nothing is restored: the person decides, with the backup, from the
# messages already printed.
abort_update() {
  local f stopped
  if [ "$UPDATE_PHASE" = pre ]; then
    if [ -n "$UPDATE_BEFORE" ] && [ "$(git -C "$REPO" rev-parse HEAD 2>/dev/null)" != "$UPDATE_BEFORE" ]; then
      # --keep fails rather than touch local changes; the message says how to move the code.
      git -C "$REPO" reset --keep "$UPDATE_BEFORE" >>"$LOG" 2>&1 || errf up_class_stuck "$REPO" "$UPDATE_BEFORE"
    fi
    if [ "$UPDATE_BUILT" = 1 ] && [ -n "$PREV_IMAGE" ]; then
      if ! docker tag "$PREV_IMAGE" "$CUR_IMAGE" >>"$LOG" 2>&1; then
        RETAG_FAILED=1
        errf up_retag_failed "$CUR_IMAGE" "$LOG" "$PREV_IMAGE_TAG"
      fi
    fi
    stopped="${#PAUSED_WRITERS[@]}"
    abort_paused_backup
    if [ "${#PAUSED_WRITERS[@]}" -gt 0 ]; then
      errf up_old_failed "$LOG"
    elif [ "$RETAG_FAILED" = 1 ]; then
      errf up_old_not_running "$CUR_IMAGE" "$PREV_IMAGE_TAG" "$PREV_IMAGE_TAG" "$CUR_IMAGE"
    elif [ "$stopped" -gt 0 ]; then
      sayf up_old_running "${PREV_IMAGE_TAG:-$CUR_IMAGE}"
    fi
    return 0
  fi
  trap - EXIT INT TERM HUP
  for f in $PARTIAL_BACKUP_FILES; do rm -f "$f"; done
  resume_hindsight || true
  compose stop "${WRITERS[@]}" >>"$LOG" 2>&1 || true
  PAUSED_WRITERS=()
}

# The messages after a failure from the migration on: the writers stay stopped (the trap does it), the backup is named,
# the way back for the code is given, and nothing is restored.
update_stays_stopped() { # before, after, branch
  errf up_stay_stopped "${WRITERS[*]}" "$LAST_BACKUP_DB" "$LAST_BACKUP_MEM" "$BACKUPS" "$LAST_BACKUP_TS" "${PREV_IMAGE_TAG:-none}"
  errf up_rollback "$1" "$2" "$REPO" "$1" "$BACKUPS" "$REPO" "$3"
}

# Update. Order: tag the previous image, git pull --ff-only, the migration class check (a refusal puts the code back on the
# commit it came from), pull/build. None of that touches data or stops anything, so a failure there only puts the code and
# the image name back. Then stop every writer and take the backup (they start again from the previous image if it fails),
# keep them stopped, migrate, start the api alone and wait until it is ready, then start the rest and check again.
# From the migration on a failure leaves the writers stopped, restores nothing automatically and prints where the backup
# is and how to go back (docs/operate/work-laptop/backup-and-update.md). Compare deploy/selfhost/update.sh: the same rule, written there for a
# pinned image.
cmd_update() {
  local OPT_ALLOW_BREAKING
  parse_options update "$@"
  need_docker; need_tool git
  git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1 || { errf up_no_git; exit 1; }
  ensure_work_env || exit 1
  ensure_secrets
  derive
  local before after branch
  echo "=== $(now) update ===" >>"$LOG"
  UPDATE_PHASE=pre
  BACKUP_TRAP=abort_update
  save_previous_image
  arm_traps abort_update
  before="$(git -C "$REPO" rev-parse HEAD)"
  UPDATE_BEFORE="$before"
  branch="$(git -C "$REPO" rev-parse --abbrev-ref HEAD 2>/dev/null || echo HEAD)"
  if ! git -C "$REPO" pull --ff-only >>"$LOG" 2>&1; then
    errf up_pull_fail "$LOG"
    exit 1
  fi
  after="$(git -C "$REPO" rev-parse HEAD)"
  # A refusal exits; the trap puts the code back on $before.
  if [ "$before" != "$after" ] && ! check_migration_class "$before" "$OPT_ALLOW_BREAKING"; then exit 1; fi
  if [ "$before" = "$after" ]; then sayf up_same "${after:0:10}"; else sayf up_changed "${before:0:10}" "${after:0:10}"; fi
  write_rooms_env
  render_generated
  say up_building
  compose pull --ignore-buildable --quiet >>"$LOG" 2>&1 || errf up_offline
  UPDATE_BUILT=1
  if ! compose build api >>"$LOG" 2>&1; then
    errf up_build_fail "$LOG"
    tail -n 20 "$LOG" >&2 || true
    exit 1
  fi
  # Only now are the writers stopped, and they stay stopped until the new version is up and ready: nothing writes between
  # the backup and the migration. The running containers keep the previous image until they are recreated.
  do_backup --keep-paused
  arm_traps abort_update
  # The image built above migrates while nothing writes. yoyo is idempotent, so the start below, which reruns the
  # one-shot migrate service before the api starts, finds nothing left to do.
  UPDATE_PHASE=migrating
  if ! compose run --rm -T --no-deps migrate >>"$LOG" 2>&1; then
    errf up_migrate_fail "$LOG" "$BACKUPS"
    tail -n 20 "$LOG" >&2 || true
    update_stays_stopped "$before" "$after" "$branch"
    exit 1
  fi
  # The api alone first, because the readiness check runs in it; the memory worker and the automation worker start only
  # after it has passed (they are recreated by this, their image is new), and then the whole stack is checked again.
  if ! compose up -d --wait --wait-timeout 420 --force-recreate api >>"$LOG" 2>&1; then
    errf up_restart_fail "$LOG" "$BACKUPS"
    tail -n 20 "$LOG" >&2 || true
    update_stays_stopped "$before" "$after" "$branch"
    exit 1
  fi
  if ! wait_ready; then
    errf up_ready_fail "$LOG" "$BACKUPS"
    update_stays_stopped "$before" "$after" "$branch"
    exit 1
  fi
  if ! compose up -d --wait --wait-timeout 420 >>"$LOG" 2>&1; then
    errf up_restart_fail "$LOG" "$BACKUPS"
    tail -n 20 "$LOG" >&2 || true
    update_stays_stopped "$before" "$after" "$branch"
    exit 1
  fi
  # The gateway configuration is a mounted file that compose does not watch: restart the gateway when it changed.
  if ! cmp -s "$GEN/gateway.haproxy.cfg" "$GEN/.gateway.applied" 2>/dev/null; then
    compose restart gateway >>"$LOG" 2>&1 || { errf gw_fail "$LOG"; update_stays_stopped "$before" "$after" "$branch"; exit 1; }
  fi
  if ! wait_ready; then
    errf up_ready_fail "$LOG" "$BACKUPS"
    update_stays_stopped "$before" "$after" "$branch"
    exit 1
  fi
  PAUSED_WRITERS=()
  disarm_traps
  prune_backups
  cp "$GEN/gateway.haproxy.cfg" "$GEN/.gateway.applied"
  write_build_info "$before" updated
  desktop_setup
  sayf up_done "$GEN/build-info.json"
}

# ---------------------------------------------------------------------------------------------------------
# Restore: the database and Hindsight's memory from ONE backup set (the same time stamp), never one without the other,
# because Sidekick's database records which sources were sent to Hindsight and Hindsight holds the memories.
# Without --apply: checks the set and the target and prints the plan; reads only. With --apply, after the project
# name is typed: do_backup --keep-paused (the way back; the writers stay paused), the database sidekick is renamed (kept,
# not dropped) and the dump read into a fresh one with the grants postgres-init.sh gives, ownership repaired, Hindsight
# stopped and its volume replaced, the migration run. Until that point every failure or interrupt puts the previous
# database and memory back (abort_restore). Then Hindsight and the writers start and the api must become ready; from
# there nothing is rolled back automatically, because the services have run against the restored data.

# psql as the superuser inside the postgres container, stopping at the first error.
pg_admin() { compose exec -T postgres psql -U postgres -v ON_ERROR_STOP=1 -q "$@"; }

NO_OTHER_SESSIONS="SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'sidekick' AND pid <> pg_backend_pid()"
RESTORE_OLD_DB=""      # the name the previous database gets (set just before the rename); empty = nothing to undo
RESTORE_OLD_NAME=""    # the same name, kept for the messages
RESTORE_MEM_TOUCHED=0  # 1 while the memory volume may hold something other than what was there before
RESTORE_COMMITTED=0    # 1 once the restored data is final: from then on the trap only starts services again
RESTORE_SAFETY_DB=""
RESTORE_SAFETY_MEM=""

# Prints the time stamps that have both files in $BACKUPS, oldest first (the names sort by time).
list_backup_sets() {
  workctl backup-sets --lang "$L" --dir "$BACKUPS" --memory "$([ "$MEMORY" = 0 ] && echo off || echo on)"
}

# Both files present and whole, read with the key: decrypted again, the dump ends with pg_dump's end marker and the
# archive lists and holds at least one entry. A missing key stops here (fail closed), before anything is changed.
check_backup_set() {
  local db="$1" mem="$2"
  [ -s "$db" ] || { errf rs_missing "$db"; return 1; }
  [ "$MEMORY" = 0 ] || [ -s "$mem" ] || { errf rs_missing "$mem"; return 1; }
  require_backup_key
  verify_dump "$db" || { errf rs_bad_dump "$db" "$BACKUP_KEY_FILE"; return 1; }
  [ "$MEMORY" = 0 ] || verify_archive "$mem" || { errf rs_bad_archive "$mem" "$BACKUP_KEY_FILE"; return 1; }
}

# Renames sidekick to $2 and reads the encrypted dump $1 into a fresh sidekick (decrypted on the way, never to disk). Returns 1 on any failure (the trap undoes it).
restore_database() {
  local dump="$1" old="$2"
  pg_admin -d postgres -c "$NO_OTHER_SESSIONS" >>"$LOG" 2>&1 || return 1
  # Recorded before the rename: a signal between the rename and the next line must still find the way back.
  # rollback_database asks Postgres which of the two names exist, so it is right whether the rename ran or not.
  RESTORE_OLD_DB="$old"
  pg_admin -d postgres -c "ALTER DATABASE sidekick RENAME TO $old" >>"$LOG" 2>&1 || return 1
  pg_admin -d postgres -c "CREATE DATABASE sidekick" \
    -c "GRANT CONNECT ON DATABASE sidekick TO sidekick_migrator, sidekick_app" \
    -c "GRANT CREATE ON DATABASE sidekick TO sidekick_owner" >>"$LOG" 2>&1 || return 1
  pg_admin -d sidekick -c "GRANT CREATE, USAGE ON SCHEMA public TO sidekick_migrator" >>"$LOG" 2>&1 || return 1
  # VERBOSITY=sqlstate: psql prints only the error code. Its normal messages quote the failing row ("Failing row
  # contains", COPY context lines, the rejected value), and the last lines of the log are shown on failure.
  backup_crypto decrypt <"$dump" | pg_admin -v VERBOSITY=sqlstate -d sidekick --single-transaction >>"$LOG" 2>&1 || return 1
  # The dump leaves out owners; without this the migrator could not change the tables in a later update.
  pg_admin -d sidekick <"$SELFHOST/restore-ownership.sql" >>"$LOG" 2>&1 || return 1
}

# Empties the Hindsight volume and unpacks the encrypted archive $1 into it (decrypted on the way, never to disk), offline,
# with the pinned image. Hindsight must be stopped.
unpack_memory() {
  local archive="$1" vol image
  vol="$(hindsight_volume)"
  image="$(hindsight_image)"
  [ -n "$vol" ] && [ -n "$image" ] || return 1
  backup_crypto decrypt <"$archive" \
    | docker run --rm -i --network none -v "$vol:/dst" --entrypoint sh "$image" \
      -c 'find /dst -mindepth 1 -delete && tar -C /dst -xzf -' >>"$LOG" 2>&1
}

# Idempotent, decided by what exists: the old name present means the rename ran (drop the new sidekick, rename back);
# only sidekick present means the rename never ran or was undone already (nothing to do); neither, or no answer from
# Postgres, is a failure (the trap then starts nothing).
rollback_database() {
  [ -n "$RESTORE_OLD_DB" ] || return 0
  local names
  names="$(pg_admin -d postgres -tAc "SELECT datname FROM pg_database WHERE datname IN ('sidekick', '$RESTORE_OLD_DB')" 2>>"$LOG")" || return 1
  case "$(workctl rollback-action --old "$RESTORE_OLD_DB" <<<"$names")" in
    rename-back)
      pg_admin -d postgres -c "$NO_OTHER_SESSIONS" -c "DROP DATABASE IF EXISTS sidekick" \
        -c "ALTER DATABASE $RESTORE_OLD_DB RENAME TO sidekick" >>"$LOG" 2>&1 || return 1
      ;;
    keep) ;;
    *) return 1 ;;
  esac
  RESTORE_OLD_DB=""
}

rollback_memory() {
  [ "$RESTORE_MEM_TOUCHED" = 1 ] || return 0
  unpack_memory "$RESTORE_SAFETY_MEM" && RESTORE_MEM_TOUCHED=0
}

# EXIT trap of restore --apply. Before the commit point: put the previous memory and database back (Hindsight is still
# stopped), then start Hindsight and the writers again. After it: only start them again. If putting back fails, nothing
# is started (the memory-worker would start Hindsight on a volume in an unknown state); the message says what is where.
abort_restore() {
  local f undo=0 ok=1
  trap - EXIT INT TERM HUP
  for f in $PARTIAL_BACKUP_FILES; do rm -f "$f"; done
  if [ "$RESTORE_COMMITTED" = 0 ]; then
    if [ -n "$RESTORE_OLD_DB" ] || [ "$RESTORE_MEM_TOUCHED" = 1 ]; then undo=1; fi
    rollback_memory || ok=0
    rollback_database || ok=0
    if [ "$ok" = 0 ]; then
      errf rs_rollback_fail "$LOG" "$RESTORE_OLD_NAME" "$RESTORE_SAFETY_DB" "$RESTORE_SAFETY_MEM"
      return
    fi
    if [ "$undo" = 1 ]; then errf rs_rolled_back "$RESTORE_OLD_NAME" "$RESTORE_SAFETY_MEM"; fi
  fi
  resume_hindsight || true
  resume_writers || true
}

# The restored database has its own owner user jobb (on another machine a different UUID): point Claude Desktop at it.
sync_owner_id() {
  local id tmp
  id="$(pg_admin -d sidekick -tAc "select id from sidekick.users where username = 'jobb'" 2>>"$LOG" | tr -d '[:space:]' || true)"
  if is_uuid "$id"; then
    tmp="$(mktemp "$SECRETS/.tmp.XXXXXX")"
    printf '%s\n' "$id" >"$tmp"
    chmod 600 "$tmp"
    mv "$tmp" "$SECRETS/user-id"
  else
    say rs_owner_none
    rm -f "$SECRETS/user-id"
  fi
}

cmd_restore() {
  local OPT_APPLY OPT_REFERENCE ref dir ts db mem answer
  parse_options restore "$@"
  need_docker
  ensure_work_env || exit 1
  ensure_secrets
  derive
  if [ -z "$OPT_REFERENCE" ]; then errf rs_usage; list_backup_sets >&2; exit 2; fi
  ref="$(workctl restore-ref --lang "$L" --backups "$BACKUPS" -- "$OPT_REFERENCE")" || exit 2
  dir="${ref%%$'\n'*}"
  ts="${ref#*$'\n'}"
  db="$dir/sidekick-$ts.sql.enc"
  mem="$dir/hindsight-$ts.tar.gz.enc"
  check_backup_set "$db" "$mem" || exit 1
  [ -f "$SELFHOST/restore-ownership.sql" ] || { errf rs_no_ownership "$SELFHOST/restore-ownership.sql"; exit 1; }
  if [ "$MEMORY" = 1 ]; then
    [ -n "$(hindsight_volume)" ] || { errf rs_no_volume "$PROJECT"; exit 1; }
  fi
  sayf rs_plan "$db" "$([ "$MEMORY" = 1 ] && echo "$mem" || msg mem_off_word)" "$PROJECT" "$BACKUPS"
  if [ "$OPT_APPLY" = 0 ]; then say rs_dry; return 0; fi

  answer="$(workctl ask --lang "$L" --key rs_confirm_q --raw -- "$PROJECT")" || exit 1
  [ "$answer" = "$PROJECT" ] || { say aborted; exit 1; }
  echo "=== $(now) restore $ts ===" >>"$LOG"

  # 1-2. The way back, taken while the writers are paused; they stay paused and the backup trap stays set.
  do_backup --keep-paused
  RESTORE_SAFETY_DB="$LAST_BACKUP_DB"
  RESTORE_SAFETY_MEM="$LAST_BACKUP_MEM"
  RESTORE_OLD_NAME="$(workctl restore-old-name -- "$LAST_BACKUP_TS")"
  arm_traps abort_restore
  [ "$MEMORY" = 0 ] || [ -s "$RESTORE_SAFETY_MEM" ] || { errf bk_fail "$LOG"; exit 1; }
  sayf rs_safety "$RESTORE_SAFETY_DB" "${RESTORE_SAFETY_MEM:-$(msg mem_off_word)}"

  # 3. The database.
  sayf rs_db "$RESTORE_OLD_NAME"
  restore_database "$db" "$RESTORE_OLD_NAME" || { errf rs_fail "$(msg rs_step_db)" "$LOG"; exit 1; }
  # 4. The memory.
  if [ "$MEMORY" = 1 ]; then
    say rs_mem
    HINDSIGHT_PAUSED=1
    compose stop hindsight >>"$LOG" 2>&1 || { errf rs_fail "$(msg rs_step_mem)" "$LOG"; exit 1; }
    RESTORE_MEM_TOUCHED=1
    unpack_memory "$mem" || { errf rs_fail "$(msg rs_step_mem)" "$LOG"; exit 1; }
  fi
  # 5. A set from older code is brought up to the schema of this image (yoyo is idempotent).
  say rs_migrating
  compose run --rm -T --no-deps migrate >>"$LOG" 2>&1 || { errf rs_fail "$(msg rs_step_migrate)" "$LOG"; exit 1; }

  # 6. Commit point: the restored data is final; the trap now only starts the services again.
  RESTORE_COMMITTED=1
  if ! resume_hindsight || ! resume_writers; then
    errf rs_start_fail "$LOG" "$RESTORE_OLD_NAME" "$RESTORE_SAFETY_DB" "$RESTORE_SAFETY_MEM"
    exit 1
  fi
  if ! wait_ready; then
    errf rs_ready_fail "$LOG" "$RESTORE_OLD_NAME" "$RESTORE_SAFETY_DB" "$RESTORE_SAFETY_MEM"
    exit 1
  fi
  disarm_traps
  sync_owner_id
  desktop_setup
  sayf rs_done "$ts" "$RESTORE_OLD_NAME" "$PROJECT" "$RESTORE_OLD_NAME"
}

# ---------------------------------------------------------------------------------------------------------
cmd_setup() {
  local missing t
  L="$(workctl setup-language --lang "$L")" || exit 1
  warn_strict_umask
  echo
  say title
  say intro
  echo
  missing=""
  for t in docker curl; do command -v "$t" >/dev/null 2>&1 || missing="$missing $t"; done
  if [ -n "$missing" ]; then errf need "${missing# }"; exit 1; fi
  if ! docker compose version >/dev/null 2>&1; then errf compose_old; exit 1; fi

  mkdir -p "$SECRETS"; chmod 700 "$SECRETS"
  if [ ! -f "$WORK_ENV" ]; then cp "$WORK/work.env.example" "$WORK_ENV"; chmod 600 "$WORK_ENV"; fi
  if ! secrets_exist; then generate_secrets; apply_model_key ""; fi

  # The questions (memory, model server and key, memory model, allowlist, rooms, app language) and their answers in
  # work.env: tools/workctl/setupguide.py. A failing guide stops the script.
  workctl setup-guide --lang "$L" --env-file "$WORK_ENV" --secrets-dir "$SECRETS" --default-rooms "$DEFAULT_ROOMS" \
    || exit 1

  # Autostart, then start (which also creates the owner and writes the Claude Desktop configuration).
  if confirm auto_q n; then
    cmd_autostart on
  else
    cmd_autostart off >/dev/null
  fi
  if confirm start_q y; then cmd_start; fi
  echo
  say "done"
  say mobile
}

main() {
  local command="${1:-}"
  if [ "$#" -gt 0 ]; then shift; fi
  # The texts and the logic come from workctl, so python3 comes first; this one message cannot come from the table.
  command -v python3 >/dev/null 2>&1 || { echo "python3 (3.9 or newer) is required / python3 (3.9 eller nyare) behövs." >&2; exit 1; }
  init_lang
  exec 7>&1 8>&2
  LOCK_COMMAND="$(workctl lock-command -- "$command" "$@")"
  if [ -n "$LOCK_COMMAND" ]; then
    take_lock "$LOCK_COMMAND"
    disarm_traps
  fi
  case "$command" in
    setup) cmd_setup "$@" ;;
    init) cmd_init "$@" ;;
    start) cmd_start "$@" ;;
    claude-config) cmd_claude_config "$@" ;;
    stop) cmd_stop "$@" ;;
    status) cmd_status "$@" ;;
    backup) cmd_backup "$@" ;;
    autostart) cmd_autostart "$@" ;;
    update) cmd_update "$@" ;;
    restore) cmd_restore "$@" ;;
    *)
      errf usage
      exit 2
      ;;
  esac
}

main "$@"
exit $?
