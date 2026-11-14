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

now() { date +%Y-%m-%dT%H:%M:%S; }

# The logic that works on the running stack (compose, docker, the files compose mounts) is workctl's too; it is given the
# checkout, the project, the language and whether the memory is on.
stackctl() { workctl "$1" --repo "$REPO" --project "$PROJECT" --lang "$L" --memory "$MEMORY" "${@:2}"; }

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
render_generated() { stackctl render-generated --allow "$ALLOW_PARSED"; }

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
    key="$(workctl ask --lang "$L" --key model_key_ask --secret)" || exit 1
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
  stackctl build-info --if-missing
  say init_next
}

# This is deliberately separate from setup/start: Claude's settings are changed only after an explicit answer.
# The answer is read from the caller's stdin by workctl.
cmd_claude_config() {
  [ "$#" = 0 ] || { errf usage; exit 2; }
  # The path is decided by workctl: SIDEKICK_WORK_CLAUDE_CONFIG when set (also used by tests so that the real Claude
  # configuration is never touched), else the platform's own place.
  workctl claude-config --lang "$L" --source "$SECRETS/claude_desktop_config.json" --platform "$(uname -s)"
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
    stackctl build-info
  fi
  log_start="$(wc -l <"$LOG")"
  # Memory switched off after it ran: stop Hindsight and the memory worker (the volume is kept).
  if [ "$MEMORY" = 0 ]; then compose stop hindsight memory-worker >>"$LOG" 2>&1 || true; fi
  if ! compose up -d --wait --wait-timeout 420 >>"$LOG" 2>&1; then
    errf up_fail "$LOG"
    tail -n 20 "$LOG" >&2 || true
    stackctl diagnose-first-start --log-start "$log_start" || true
    exit 1
  fi
  # The gateway configuration is a mounted file that compose does not watch: restart the gateway when it changed.
  if ! cmp -s "$GEN/gateway.haproxy.cfg" "$GEN/.gateway.applied" 2>/dev/null; then
    compose restart gateway >>"$LOG" 2>&1 || { errf gw_fail "$LOG"; exit 1; }
    cp "$GEN/gateway.haproxy.cfg" "$GEN/.gateway.applied"
  fi
  say started
  stackctl desktop-setup
}

cmd_stop() {
  need_docker
  [ -f "$WORK_ENV" ] || cp "$WORK/work.env.example" "$WORK_ENV"
  derive lenient
  FORCE_MEMORY_PROFILE=1
  echo "=== $(now) stop ===" >>"$LOG"
  if [ "${1:-}" = "--purge" ]; then
    local answer
    answer="$(workctl ask --lang "$L" --key purge_q --only-on-terminal)" || exit 1
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

# The lock is released on every way out (an interrupt, a closed terminal, kill, an error). INT, TERM and HUP become exits
# so that the EXIT trap runs.
release_lock_on_exit() {
  trap release_lock EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  trap 'exit 129' HUP
}

# ---------------------------------------------------------------------------------------------------------
# backup, update and restore --apply are sequences of docker calls with a cleanup for every way out (the writers and
# Hindsight start again, half-made files go): tools/workctl/backupflow.py, updateflow.py and restoreflow.py. The shell
# keeps the lock, which its process holds until it ends, and starts them in the foreground, so an interrupt or a closed
# terminal reaches both and the flow does its cleanup before it ends.
cmd_backup() {
  need_docker
  ensure_work_env || exit 1
  ensure_secrets
  derive
  echo "=== $(now) backup ===" >>"$LOG"
  stackctl backup
}

# Update (tools/workctl/updateflow.py): the checkout and the stack to the newest version; the checks that decide what is
# asked of the person come first, in the order a refusal needs.
cmd_update() {
  local OPT_ALLOW_BREAKING flags=()
  parse_options update "$@"
  need_docker; need_tool git
  git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1 || { errf up_no_git; exit 1; }
  ensure_work_env || exit 1
  ensure_secrets
  derive
  echo "=== $(now) update ===" >>"$LOG"
  if [ "$OPT_ALLOW_BREAKING" = 1 ]; then flags+=(--allow-breaking-migration); fi
  stackctl update --allow "$ALLOW_PARSED" ${flags[@]+"${flags[@]}"}
}

# Restore (tools/workctl/restoreflow.py): the database and Hindsight's memory from one backup set. Without --apply it
# only checks the set and prints the plan.
cmd_restore() {
  local OPT_APPLY OPT_REFERENCE flags=()
  parse_options restore "$@"
  need_docker
  ensure_work_env || exit 1
  ensure_secrets
  derive
  if [ "$OPT_APPLY" = 1 ]; then flags+=(--apply); fi
  stackctl restore --reference "$OPT_REFERENCE" ${flags[@]+"${flags[@]}"}
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
  LOCK_COMMAND="$(workctl lock-command -- "$command" "$@")"
  if [ -n "$LOCK_COMMAND" ]; then
    take_lock "$LOCK_COMMAND"
    release_lock_on_exit
    export SIDEKICK_WORK_LOCK_HELD=1  # workctl's flows then do not take the same lock a second time
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
