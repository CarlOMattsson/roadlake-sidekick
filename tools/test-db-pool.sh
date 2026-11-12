#!/usr/bin/env bash
# Pool of disposable PostgreSQL test databases inside the test container.
#
#   bash tools/test-db-pool.sh create N   create sidekick_test_1..N (idempotent)
#   bash tools/test-db-pool.sh workers K N  create the N xdist worker databases of base K (idempotent)
#                                         K=0 is the base sidekick_test: sidekick_test_w0..w(N-1);
#                                         K>0: sidekick_test_K_w0..w(N-1)
#   bash tools/test-db-pool.sh list       list pool and worker databases
#   bash tools/test-db-pool.sh drop N     drop sidekick_test_N (fails while in use)
#   bash tools/test-db-pool.sh env K      print export lines for slot K (use with eval)
#
# Only the test profile is touched: deploy/compose.test.yaml, service "db", 127.0.0.1:55433.
# sidekick_test itself is never created, altered or dropped by this script.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/deploy/compose.test.yaml"
INIT_SQL="$REPO_ROOT/deploy/postgres-init.sql"
SERVICE="db"
DB_HOST="127.0.0.1"
DB_PORT="55433"
EXPECTED_BIND="$DB_HOST:$DB_PORT"
MAX_SLOTS=20

die() {
  echo "test-db-pool: $*" >&2
  exit 1
}

# The compose project of the running test container. deploy/compose.test.yaml names it sidekick-test;
# a container started earlier may still run under a previous project name until it is recreated
# (docker compose -f deploy/compose.test.yaml up -d db). Both are found read-only via docker ps.
PROJECT_CURRENT="sidekick-test"
PROJECT_LEGACY="char""lie-test"

test_project() {
  local project
  for project in "$PROJECT_CURRENT" "$PROJECT_LEGACY"; do
    if [[ -n "$(docker ps -q --filter "label=com.docker.compose.project=$project" \
        --filter "label=com.docker.compose.service=$SERVICE" 2>/dev/null)" ]]; then
      printf '%s' "$project"
      return 0
    fi
  done
  printf '%s' "$PROJECT_CURRENT"
}

compose() {
  docker compose -p "$(test_project)" -f "$COMPOSE_FILE" "$@"
}

# psql_admin DATABASE [psql args...]: runs as the cluster superuser inside the test container only.
psql_admin() {
  local database="$1"
  shift
  compose exec -T "$SERVICE" psql -X -v ON_ERROR_STOP=1 -U postgres -d "$database" -Atq "$@"
}

# Refuses anything but the test profile: an overridden bind, or a db service not published on 55433.
guard_profile() {
  [[ -f "$COMPOSE_FILE" ]] || die "missing $COMPOSE_FILE"
  if [[ -n "${SIDEKICK_TEST_DB_BIND:-}" && "$SIDEKICK_TEST_DB_BIND" != "$EXPECTED_BIND" ]]; then
    die "SIDEKICK_TEST_DB_BIND=$SIDEKICK_TEST_DB_BIND is not the test profile's $EXPECTED_BIND; refusing."
  fi
  local published
  published="$(compose port "$SERVICE" 5432 2>/dev/null || true)"
  if [[ "$published" != "$EXPECTED_BIND" ]]; then
    die "service '$SERVICE' publishes '${published:-nothing}', expected $EXPECTED_BIND. Is the test container running? (docker compose -f deploy/compose.test.yaml up -d db)"
  fi
}

# slot_name K: validates K as 1..MAX_SLOTS and prints sidekick_test_K. Always has a numeric suffix.
slot_name() {
  local slot="${1:-}"
  [[ "$slot" =~ ^[1-9][0-9]?$ ]] || die "slot must be an integer 1..$MAX_SLOTS, got '$slot'"
  (( slot <= MAX_SLOTS )) || die "slot $slot is above the maximum $MAX_SLOTS"
  printf 'sidekick_test_%s' "$slot"
}

database_exists() {
  local name="$1"
  [[ "$(psql_admin postgres -c "SELECT 1 FROM pg_database WHERE datname = '$name'")" == "1" ]]
}

cmd_create() {
  local count="${1:-}"
  slot_name "$count" >/dev/null
  guard_profile
  local i name
  for ((i = 1; i <= count; i++)); do
    name="sidekick_test_$i"
    if database_exists "$name"; then
      echo "already exists: $name"
    else
      psql_admin postgres -c "CREATE DATABASE $name" >/dev/null
      echo "created: $name"
    fi
    # Same per-database grants as CI and the compose init: roles are cluster-wide, grants are not.
    compose exec -T "$SERVICE" psql -X -v ON_ERROR_STOP=1 -q -U postgres -d "$name" -f - \
      < "$INIT_SQL" >/dev/null
    echo "roles and grants done: $name"
  done
}

# worker_name K N: the xdist worker database N of base K. K=0 is the base sidekick_test.
worker_name() {
  local slot="$1" worker="$2"
  if (( slot == 0 )); then
    printf 'sidekick_test_w%s' "$worker"
  else
    printf 'sidekick_test_%s_w%s' "$slot" "$worker"
  fi
}

cmd_workers() {
  local slot="${1:-}" count="${2:-}"
  [[ "$slot" =~ ^(0|[1-9][0-9]?)$ ]] || die "K must be 0 (sidekick_test) or 1..$MAX_SLOTS, got '$slot'"
  (( slot <= MAX_SLOTS )) || die "K $slot is above the maximum $MAX_SLOTS"
  [[ "$count" =~ ^[0-9]{1,3}$ ]] && (( count >= 1 && count <= 100 )) \
    || die "N must be an integer 1..100, got '$count'"
  guard_profile
  local base="sidekick_test"
  if (( slot > 0 )); then
    base="sidekick_test_$slot"
  fi
  database_exists "$base" || die "$base does not exist; for K>0 run: bash tools/test-db-pool.sh create $slot"
  local i name
  for ((i = 0; i < count; i++)); do
    name="$(worker_name "$slot" "$i")"
    if database_exists "$name"; then
      echo "already exists: $name"
    else
      psql_admin postgres -c "CREATE DATABASE $name" >/dev/null
      echo "created: $name"
    fi
    # Same owner and per-database grants as the slots and CI; migrations are not applied here.
    compose exec -T "$SERVICE" psql -X -v ON_ERROR_STOP=1 -q -U postgres -d "$name" -f - \
      < "$INIT_SQL" >/dev/null
    echo "roles and grants done: $name"
  done
}

cmd_list() {
  guard_profile
  local out
  out="$(psql_admin postgres -c "SELECT datname || '  owner=' || pg_get_userbyid(datdba) FROM pg_database WHERE datname ~ '^sidekick_test_([0-9]+(_w[0-9]+)?|w[0-9]+)$' ORDER BY length(datname), datname")"
  echo "Pool in the test container ($EXPECTED_BIND):"
  if [[ -z "$out" ]]; then
    echo "  (no slots, run: bash tools/test-db-pool.sh create 4)"
  else
    echo "$out" | sed 's/^/  /'
  fi
}

cmd_drop() {
  local name
  name="$(slot_name "${1:-}")"
  guard_profile
  psql_admin postgres -c "DROP DATABASE IF EXISTS $name" >/dev/null
  echo "borttagen: $name"
}

cmd_env() {
  local name
  name="$(slot_name "${1:-}")"
  guard_profile
  database_exists "$name" || die "$name does not exist; run: bash tools/test-db-pool.sh create ${1}"
  cat <<EOF
export SIDEKICK_ENVIRONMENT=test
export SIDEKICK_TEST_DATABASE_URL=postgresql+psycopg://sidekick_app:sidekick_app@${DB_HOST}:${DB_PORT}/${name}
export SIDEKICK_TEST_MIGRATION_DATABASE_URL=postgresql+psycopg://sidekick_migrator:sidekick_migrator@${DB_HOST}:${DB_PORT}/${name}
export SIDEKICK_TEST_ADMIN_DATABASE_URL=postgresql+psycopg://postgres:postgres@${DB_HOST}:${DB_PORT}/${name}
EOF
}

case "${1:-}" in
  create) cmd_create "${2:-}" ;;
  workers) cmd_workers "${2:-}" "${3:-}" ;;
  list) cmd_list ;;
  drop) cmd_drop "${2:-}" ;;
  env) cmd_env "${2:-}" ;;
  *)
    echo "Usage: bash tools/test-db-pool.sh {create N|workers K N|list|drop N|env K}" >&2
    exit 2
    ;;
esac
