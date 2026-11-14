#!/usr/bin/env bash
# One local run of the checks that should be green before a push. It mirrors the CI jobs for the backend,
# the frontend, the migrations, the website and the Android shell, in that order.
#
#   bash tools/check-all.sh --slot K [options]
#
# Stages (each can be skipped):
#   backend-tests   pytest --full in parallel on the disposable test database, slot K (tools/test-db-pool.sh),
#                   with the CI coverage gate (--cov=sidekick --cov-fail-under=90), in the CI time zone (TZ=UTC)
#   backend-static  ruff format --check, ruff check, pyright
#   policy          tools/check-version-sync.py, tools/third_party_notices.py --check and
#                   tools/check-migration-policy.py --all
#   ShellCheck      tools/shellcheck-ci.sh: the CI image of shellcheck (tools/ci-images.sh), severity warning, over every
#                   tracked shell script. Needs Docker
#   gitleaks        tools/gitleaks-ci.sh: the CI image of gitleaks (v8.24.3) over the full history, with the repo
#                   configuration and .gitleaksignore. Needs Docker. In the working repository the history is not what
#                   CI scans (the public repository starts from an export), so the published-tree stage scans the
#                   export instead and this stage says so; the published repository scans its own history here
#   frontend        build:mobile first (mobile-csp.test.ts reads the built page), prettier --check,
#                   eslint + tsc -b + vitest on React and the MCP App views on Preact (npm run check) with TZ=UTC,
#                   then the unit tests once more with TZ=America/Los_Angeles, as CI does
#   mcp-app         npm run build:mcp-app, the checked-in resource must equal the build, then the Playwright tests
#                   (test:mcp-app) in the pinned Playwright image of CI (tools/playwright-docker.sh). Needs Docker
#   published-tree  tools/check-extra.sh: the public export (tools/export/export-repo.sh) built in a temporary directory
#                   and checked there as the published CI would: links and docs parity, lint, prettier, tsc, vitest in two
#                   time zones, the MCP App view tests, the policy tests, shellcheck and gitleaks. Not applicable (and
#                   skipped) in a checkout without the export tooling, i.e. the published repository itself
#   website         npm --prefix website test, then run build, then run check (the page, link, accessibility and
#                   price checks; the check script is skipped while website/package.json has none).
#                   Needs website/node_modules: npm --prefix website ci --ignore-scripts
#   android         build:mobile, cap sync android, gradlew ktlintCheck testDebugUnitTest lintDebug assembleRelease
#
# Release gate (only with --release; the rest of the release CI, in the order of .github/workflows/ci.yml):
#   contracts       the generated references and the tool types must equal the code: mcp.export_tool_reference --check,
#                   export_reference --check, frontend generate:tool-types --check, and the contract snapshots under
#                   contracts/ re-exported to a temporary file and compared (nothing in the working tree is rewritten).
#                   Runs after backend-static
#   coverage        the frontend coverage threshold (vitest --coverage, lines >= 91), after the frontend stage
#   mobile-audit    the Playwright mobile audit on the simulated MCP host, in the same Playwright image, after mcp-app
#   drill           tools/drill.sh selfhost --local-images: install, update, backup, destroy and restore of the
#                   self-hosted stack from two images built from this checkout, in a throw-away Compose project on random
#                   ports (about 3 minutes; it never touches a running instance). Needs Docker. Runs last
#   dependency-audit  what .github/workflows/audit.yml runs: pip-audit, npm audit (frontend and website, runtime
#                   dependencies, high and above) and OSV-Scanner on the Gradle lockfiles. Every part needs the
#                   network; one that cannot reach its host (or lacks its tool) prints a "SKIPPED: ..." line and the
#                   stage is reported as SKIPPED, never as ok, and with --strict as FAILED. Runs after gitleaks
#
# Options:
#   --slot K              test database slot 1..20 for backend-tests (required unless that stage is skipped)
#   --workers N           pytest-xdist workers for backend-tests (default 10)
#   --skip-backend-tests  --skip-backend-static  --skip-policy  --skip-frontend  --skip-mcp-app
#   --skip-shellcheck     --skip-gitleaks   --skip-published-tree   --skip-website   --skip-android
#   --release             also run the release-gate stages above (contracts, coverage, mobile-audit, dependency-audit,
#                         drill); each has its own --skip-contracts, --skip-coverage, --skip-mobile-audit, --skip-audit,
#                         --skip-drill
#   --strict              a missing Docker, website/node_modules or other tool fails the run (default: that stage prints
#                         a "SKIPPED: ..." line and is reported as SKIPPED, never as ok)
#   --keep-going          run the remaining stages after a failure (default: stop at the first failure)
#   --dry-run             print the commands in order without running anything
#   -h, --help            show this text
#
# Safety: the only database this touches is the disposable test container on 127.0.0.1:55433, and only through
# tools/test-db-pool.sh, which refuses any other port and any other database name. It does not start, stop,
# deploy or read a running instance, and it never reads .env files.
#
# Not covered here, even with --release: the emulator test, the API image build and the Compose smoke test (they need
# an emulator or a container runtime that this script does not drive). CI runs those; see docs/maintainers/release.md.
# Before a release: run this with --release, then start ci.yml by hand in the public repository.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

SLOT=""
WORKERS=10
DRY_RUN=0
KEEP_GOING=0
SKIP_BACKEND_TESTS=0
SKIP_BACKEND_STATIC=0
SKIP_POLICY=0
SKIP_FRONTEND=0
SKIP_MCP_APP=0
SKIP_WEBSITE=0
SKIP_SHELLCHECK=0
SKIP_GITLEAKS=0
SKIP_PUBLISHED_TREE=0
SKIP_ANDROID=0
SKIP_CONTRACTS=0
SKIP_COVERAGE=0
SKIP_MOBILE_AUDIT=0
SKIP_AUDIT=0
SKIP_DRILL=0
RELEASE=0
STRICT=0

usage() {
  sed -n '2,/^[^#]/{/^#/p}' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

die() {
  echo "check-all: $*" >&2
  exit 2
}

while [ $# -gt 0 ]; do
  case "$1" in
    --slot)
      [ $# -ge 2 ] || die "--slot needs a value"
      SLOT="$2"
      shift 2
      ;;
    --workers)
      [ $# -ge 2 ] || die "--workers needs a value"
      WORKERS="$2"
      shift 2
      ;;
    --skip-backend-tests) SKIP_BACKEND_TESTS=1; shift ;;
    --skip-backend-static) SKIP_BACKEND_STATIC=1; shift ;;
    --skip-policy) SKIP_POLICY=1; shift ;;
    --skip-frontend) SKIP_FRONTEND=1; shift ;;
    --skip-mcp-app) SKIP_MCP_APP=1; shift ;;
    --skip-website) SKIP_WEBSITE=1; shift ;;
    --skip-shellcheck) SKIP_SHELLCHECK=1; shift ;;
    --skip-gitleaks) SKIP_GITLEAKS=1; shift ;;
    --skip-published-tree) SKIP_PUBLISHED_TREE=1; shift ;;
    --strict) STRICT=1; shift ;;
    --skip-android) SKIP_ANDROID=1; shift ;;
    --skip-contracts) SKIP_CONTRACTS=1; shift ;;
    --skip-coverage) SKIP_COVERAGE=1; shift ;;
    --skip-mobile-audit) SKIP_MOBILE_AUDIT=1; shift ;;
    --skip-audit) SKIP_AUDIT=1; shift ;;
    --skip-drill) SKIP_DRILL=1; shift ;;
    --release) RELEASE=1; shift ;;
    --keep-going) KEEP_GOING=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h | --help)
      usage
      exit 0
      ;;
    *) die "unknown argument: $1 (see --help)" ;;
  esac
done

[[ "$WORKERS" =~ ^[1-9][0-9]?$ ]] || die "--workers must be a number from 1 to 99"
if [ "$SKIP_BACKEND_TESTS" -eq 0 ]; then
  [ -n "$SLOT" ] || die "--slot K is required for backend-tests (or pass --skip-backend-tests)"
  [[ "$SLOT" =~ ^([1-9]|1[0-9]|20)$ ]] || die "--slot must be a number from 1 to 20 (the base database is never used)"
fi

# The release-gate stages only run with --release.
if [ "$RELEASE" -eq 0 ]; then
  SKIP_CONTRACTS=1
  SKIP_COVERAGE=1
  SKIP_MOBILE_AUDIT=1
  SKIP_AUDIT=1
  SKIP_DRILL=1
fi

need() {
  if [ "$DRY_RUN" -eq 0 ] && ! command -v "$1" >/dev/null 2>&1; then
    die "missing tool: $1"
  fi
}

# Exit code a stage uses when an optional tool or the network is missing; run_stage turns it into SKIPPED (or FAILED with --strict).
RC_TOOL_MISSING=77

# optional_tool TOOL INSTALL_HINT: ends the stage with RC_TOOL_MISSING when TOOL is not installed (not in --dry-run).
optional_tool() {
  if [ "$DRY_RUN" -eq 0 ] && ! command -v "$1" >/dev/null 2>&1; then
    echo "SKIPPED: $1 missing (install: $2)"
    exit "$RC_TOOL_MISSING"
  fi
}

# optional_deps DIR INSTALL_HINT: ends the stage with RC_TOOL_MISSING when DIR (installed dependencies) is absent.
optional_deps() {
  if [ "$DRY_RUN" -eq 0 ] && [ ! -d "$1" ]; then
    echo "SKIPPED: ${1%/node_modules} deps missing (install: $2)"
    exit "$RC_TOOL_MISSING"
  fi
}

# Every stage runs in its own subshell under `||`, where errexit is off. run therefore ends the stage itself
# when a command fails. run CMD...: prints the command and runs it unless --dry-run.
run() {
  printf '+ %s\n' "$*"
  if [ "$DRY_RUN" -eq 0 ]; then
    "$@" || exit $?
  fi
}

stage_backend_tests() {
  need uv
  need docker
  run bash tools/test-db-pool.sh create "$SLOT"
  run bash tools/test-db-pool.sh workers "$SLOT" "$WORKERS"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "+ pool_env=\$(bash tools/test-db-pool.sh env $SLOT) && eval \"\$pool_env\""
    echo "+ env TZ=UTC uv run --project backend python -m pytest backend/tests --full -n $WORKERS --dist loadgroup" \
      "--no-header -p no:cacheprovider -rfE -W ignore --cov=sidekick --cov-fail-under=90"
    return 0
  fi
  # Assign first so that a failed `env` stops the run instead of falling back to another database.
  local pool_env
  pool_env="$(bash tools/test-db-pool.sh env "$SLOT")" || exit $?
  eval "$pool_env"
  # The CI runner's zone is UTC; the owner's machine is not, and date handling that depends on the zone must show here.
  run env TZ=UTC uv run --project backend python -m pytest backend/tests --full -n "$WORKERS" --dist loadgroup \
    --no-header -p no:cacheprovider -rfE -W ignore --cov=sidekick --cov-fail-under=90
}

stage_backend_static() {
  need uv
  cd backend || exit 1
  run uv run ruff format --check . ../tools/workctl
  run uv run ruff check --no-cache . ../tools/workctl
  run uv run pyright
}

# check_snapshot MODULE FILE: re-exports the contract snapshot to a temporary file and compares it with the committed one,
# the same check as the CI step that regenerates the files and runs `git diff --exit-code -- contracts`, without
# rewriting anything in the working tree.
check_snapshot() {
  local module="$1" committed="$2" fresh
  printf '+ uv run --project backend python -m %s --output <temporary file>, then compare with %s\n' "$module" "$committed"
  if [ "$DRY_RUN" -eq 1 ]; then
    return 0
  fi
  fresh="$(mktemp)"
  if ! uv run --project backend python -m "$module" --output "$fresh"; then
    rm -f "$fresh"
    exit 1
  fi
  if ! cmp -s "$fresh" "$committed"; then
    rm -f "$fresh"
    echo "check-all: $committed is out of date; regenerate it with: uv run --project backend python -m $module --output $committed" >&2
    exit 1
  fi
  rm -f "$fresh"
}

stage_contracts() {
  need uv
  need npm
  check_snapshot sidekick.api.export_openapi contracts/openapi.generated.json
  check_snapshot sidekick.mcp.export_contract contracts/mcp-tools.generated.json
  check_snapshot sidekick.api.export_companion_contract contracts/companion-api.generated.json
  run uv run --project backend python -m sidekick.mcp.export_tool_reference --check
  run uv run --project backend python -m sidekick.export_reference --check
  run npm --prefix frontend run generate:tool-types -- --check
}

stage_policy() {
  need python3
  run python3 tools/check-version-sync.py
  run python3 tools/third_party_notices.py --check
  run python3 tools/check-migration-policy.py --all
}

# The CI shellcheck and secrets jobs run these same scripts (tools/ci-images.sh pins the images). Without Docker they
# exit with RC_TOOL_MISSING after a SKIPPED line.
stage_shellcheck() {
  run bash tools/shellcheck-ci.sh
}

stage_gitleaks() {
  if [ "$DRY_RUN" -eq 0 ] && [ -d tools/export ]; then
    echo "not applicable: CI scans the published repository, so the published-tree stage scans the export"
    return 0
  fi
  run bash tools/gitleaks-ci.sh
}

stage_frontend() {
  need npm
  # mobile-csp.test.ts checks the built mobile page, so it is built first (as in CI), never read stale or missing.
  run npm --prefix frontend run build:mobile
  run npm --prefix frontend run format:check
  # The runner's zone is UTC; the same tests run again in a zone that differs from both UTC and the owner's.
  run env TZ=UTC npm --prefix frontend run check
  run env TZ=America/Los_Angeles npm --prefix frontend test
}

# The CI frontend job runs the unit tests with the coverage threshold after the mobile bundle is built.
stage_coverage() {
  need npm
  run npm --prefix frontend run build:mobile
  run env TZ=UTC npm --prefix frontend run test:coverage
}

stage_mcp_app() {
  need npm
  local resource="backend/src/sidekick/mcp/apps/sidekick.html" before="" after=""
  if [ "$DRY_RUN" -eq 0 ]; then
    before="$(sha256sum <"$resource")"
  fi
  run npm --prefix frontend run build:mcp-app
  echo "+ the checked-in $resource must equal the build"
  if [ "$DRY_RUN" -eq 0 ]; then
    after="$(sha256sum <"$resource")"
    if [ "$before" != "$after" ]; then
      echo "check-all: $resource was out of date; the rebuilt file is in the working tree, commit it" >&2
      exit 1
    fi
  fi
  run bash tools/playwright-docker.sh npx playwright test --config playwright.mcp-app.config.ts
}

# The mobile audit drives the checked-in MCP App resource in Chromium (the pinned Playwright image); CI writes its output
# under the runner temp directory.
stage_mobile_audit() {
  echo "+ MOBILE_AUDIT_OUT=<temporary directory>"
  if [ "$DRY_RUN" -eq 0 ]; then
    MOBILE_AUDIT_OUT="$(mktemp -d)"
    export MOBILE_AUDIT_OUT
  fi
  run bash tools/playwright-docker.sh npx playwright test --config playwright.mobile-audit.config.ts
}

# The public export, checked as its own CI would check it. Only the working repository has the export tooling.
stage_published_tree() {
  if [ "$DRY_RUN" -eq 0 ] && [ ! -f tools/check-extra.sh ]; then
    echo "not applicable: this checkout has no export tooling (it is the published tree)"
    return 0
  fi
  run bash tools/check-extra.sh
}

# The website check script belongs to a separate piece of work; run it as soon as website/package.json declares it.
website_has_check_script() {
  [ "$DRY_RUN" -eq 1 ] && return 0
  node -e 'process.exit(JSON.parse(require("node:fs").readFileSync("website/package.json", "utf8")).scripts?.check ? 0 : 1)'
}

stage_website() {
  need npm
  optional_deps website/node_modules "npm --prefix website ci --ignore-scripts"
  run npm --prefix website test
  run npm --prefix website run build
  if website_has_check_script; then
    run npm --prefix website run check
  else
    echo "website: no check script in website/package.json yet, skipped"
  fi
}

# True (status 0) when a TCP connection to HOST:443 opens within a few seconds.
host_reachable() {
  python3 -c 'import socket, sys; socket.create_connection((sys.argv[1], 443), 4).close()' "$1" 2>/dev/null
}

AUDIT_SKIPPED=0
AUDIT_FAILED=0

# audit_step LABEL "TOOLS" "HOSTS" CMD...: runs one dependency audit. A missing tool or an unreachable host prints a
# SKIPPED line and marks the stage as only partly checked; a failing audit marks it failed, and the next one still runs.
audit_step() {
  local label="$1" tool host
  local -a tools hosts
  read -ra tools <<<"$2"
  read -ra hosts <<<"$3"
  shift 3
  echo "-- $label"
  if [ "$DRY_RUN" -eq 0 ]; then
    for tool in "${tools[@]}"; do
      if ! command -v "$tool" >/dev/null 2>&1; then
        echo "SKIPPED: $label: $tool missing"
        AUDIT_SKIPPED=1
        return 0
      fi
    done
    for host in "${hosts[@]}"; do
      if ! host_reachable "$host"; then
        echo "SKIPPED: $label needs the network: $host is unreachable"
        AUDIT_SKIPPED=1
        return 0
      fi
    done
  fi
  (run "$@") || AUDIT_FAILED=1
}

# The steps of .github/workflows/audit.yml. All of them need the network, so none can fail silently offline.
stage_dependency_audit() {
  need python3
  audit_step "pip-audit (backend, all locked dependency groups)" "uv uvx" "pypi.org files.pythonhosted.org" \
    bash .github/audit/pip-audit.sh
  audit_step "npm audit (frontend, runtime dependencies, high and above)" "npm" "registry.npmjs.org" \
    npm --prefix frontend audit --audit-level=high --omit=dev
  audit_step "npm audit (website, runtime dependencies, high and above)" "npm" "registry.npmjs.org" \
    npm --prefix website audit --audit-level=high --omit=dev
  audit_step "OSV-Scanner (Android Gradle lockfiles)" "docker" "ghcr.io api.osv.dev" \
    bash .github/audit/osv-gradle.sh
  if [ "$AUDIT_FAILED" -eq 1 ]; then
    exit 1
  fi
  if [ "$AUDIT_SKIPPED" -eq 1 ]; then
    exit "$RC_TOOL_MISSING"
  fi
}

# Install, update, backup, destroy and restore from two images built from this checkout. The drill picks random free
# ports (never a reserved one) and removes what it created.
stage_drill() {
  optional_tool docker "https://docs.docker.com/engine/install/"
  run bash tools/drill.sh selfhost --local-images
}

stage_android() {
  need npm
  need java
  run npm --prefix frontend run build:mobile
  cd frontend || exit 1
  run npx cap sync android
  cd android || exit 1
  run ./gradlew :app:ktlintCheck :app:testDebugUnitTest :app:lintDebug :app:assembleRelease
}

RESULTS=()
FAILED=0

# run_stage NAME SKIP_FLAG FUNCTION
run_stage() {
  local name="$1" skip="$2" func="$3"
  if [ "$skip" -eq 1 ]; then
    RESULTS+=("skipped  $name")
    return 0
  fi
  if [ "$FAILED" -eq 1 ] && [ "$KEEP_GOING" -eq 0 ]; then
    RESULTS+=("not run  $name")
    return 0
  fi
  echo
  echo "===== $name ====="
  local rc=0
  # The subshell keeps `eval` of the pool environment from leaking into the next stage.
  ("$func") || rc=$?
  if [ "$rc" -eq 0 ]; then
    RESULTS+=("ok       $name")
  elif [ "$rc" -eq "$RC_TOOL_MISSING" ] && [ "$STRICT" -eq 0 ]; then
    RESULTS+=("SKIPPED  $name (a tool or the network was missing, so not fully checked; --strict makes this a failure)")
  elif [ "$rc" -eq "$RC_TOOL_MISSING" ]; then
    RESULTS+=("FAILED   $name (tool or network missing, --strict)")
    FAILED=1
  else
    RESULTS+=("FAILED   $name (exit $rc)")
    FAILED=1
  fi
}

run_stage backend-tests "$SKIP_BACKEND_TESTS" stage_backend_tests
run_stage backend-static "$SKIP_BACKEND_STATIC" stage_backend_static
run_stage contracts "$SKIP_CONTRACTS" stage_contracts
run_stage policy "$SKIP_POLICY" stage_policy
run_stage shellcheck "$SKIP_SHELLCHECK" stage_shellcheck
run_stage gitleaks "$SKIP_GITLEAKS" stage_gitleaks
run_stage dependency-audit "$SKIP_AUDIT" stage_dependency_audit
run_stage frontend "$SKIP_FRONTEND" stage_frontend
run_stage coverage "$SKIP_COVERAGE" stage_coverage
run_stage mcp-app "$SKIP_MCP_APP" stage_mcp_app
run_stage mobile-audit "$SKIP_MOBILE_AUDIT" stage_mobile_audit
run_stage published-tree "$SKIP_PUBLISHED_TREE" stage_published_tree
run_stage website "$SKIP_WEBSITE" stage_website
run_stage android "$SKIP_ANDROID" stage_android
run_stage drill "$SKIP_DRILL" stage_drill

echo
if [ "$DRY_RUN" -eq 1 ]; then
  echo "===== summary (dry run, nothing was executed) ====="
else
  echo "===== summary ====="
fi
printf '%s\n' "${RESULTS[@]}"
exit "$FAILED"
