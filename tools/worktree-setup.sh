#!/usr/bin/env bash
# Dependencies for a fresh git worktree (or any checkout): the parts of tools/check-all.sh that need installed packages
# (the backend tests and static checks, the frontend, the MCP App, the published-tree and the website stages) otherwise
# skip or fail until each package set has been installed by hand.
#
#   bash tools/worktree-setup.sh [--force] [--site-tools] [--skip-backend] [--skip-frontend] [--skip-website]
#
#   backend    uv sync --project backend --frozen --all-groups, as CI does                      (backend/.venv)
#   frontend   npm ci in frontend/                                                              (frontend/node_modules)
#   website    npm ci --ignore-scripts in website/ (how the website stage and CI install it)    (website/node_modules)
#   browsers   the Chromium that the website's Playwright check needs, only when it is not in the Playwright cache
#   android    only checked: the JDK and Android SDK come from an environment file that this script never sources,
#              because its variables would break the other stages. It prints how to run the Android stage in its own shell
#
# Safe to run again: a step is skipped when the lockfile is the one it installed last time (the hash is kept inside the
# installed directory, so it goes when that directory does). --force installs anyway. Nothing is copied from another
# checkout and the npm cache is used (--prefer-offline). --site-tools also installs website/tools/* (diagram and
# Lighthouse authoring tools; the checks do not need them).
#
# The Android environment file is named by SIDEKICK_ANDROID_ENV (a script that puts a JDK 21 and the Android SDK on the
# path). Without it the Android line says so and the Android stage stays unusable here.
#
# Exit status: 0 when every step that ran succeeded (a missing Android environment is reported, not a failure), 1 otherwise.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

FORCE=0
SITE_TOOLS=0
DO_BACKEND=1
DO_FRONTEND=1
DO_WEBSITE=1

usage() {
  sed -n '2,/^[^#]/{/^#/p}' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --force) FORCE=1 ;;
    --site-tools) SITE_TOOLS=1 ;;
    --skip-backend) DO_BACKEND=0 ;;
    --skip-frontend) DO_FRONTEND=0 ;;
    --skip-website) DO_WEBSITE=0 ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "worktree-setup: unknown argument: $1 (see --help)" >&2
      exit 2
      ;;
  esac
  shift
done

SUMMARY=()
FAILED=0

note() {
  SUMMARY+=("$(printf '%-9s %s' "$1" "$2")")
}

# fingerprint FILE...: one hash of the contents of the files.
fingerprint() {
  cat -- "$@" | sha256sum | cut -d' ' -f1
}

# install_step LABEL TARGET_DIR FINGERPRINT_FILES COMMAND...: runs COMMAND from the repository root unless TARGET_DIR already
# holds an install of these exact lockfiles. FINGERPRINT_FILES is a comma-separated list.
install_step() {
  local label="$1" target="$2" files="$3"
  shift 3
  local -a lockfiles
  IFS=, read -ra lockfiles <<<"$files"
  local want stamp="$target/.worktree-setup.sha256"
  want="$(fingerprint "${lockfiles[@]}")"
  if [ "$FORCE" -eq 0 ] && [ -d "$target" ] && [ -f "$stamp" ] && [ "$(cat "$stamp")" = "$want" ]; then
    note "$label" "ready (lockfile unchanged since the last install)"
    return 0
  fi
  echo "+ $*"
  if "$@"; then
    printf '%s\n' "$want" >"$stamp"
    note "$label" "installed"
  else
    note "$label" "FAILED: $*"
    FAILED=1
  fi
}

npm_ci() {
  local dir="$1"
  shift
  npm --prefix "$dir" ci --prefer-offline --no-audit --no-fund "$@"
}

need_tool() {
  if ! command -v "$1" >/dev/null 2>&1; then
    note "$2" "MISSING tool: $1"
    FAILED=1
    return 1
  fi
}

if [ "$DO_BACKEND" -eq 1 ] && need_tool uv backend; then
  install_step backend backend/.venv backend/uv.lock,backend/pyproject.toml \
    uv sync --project backend --frozen --all-groups
fi

if [ "$DO_FRONTEND" -eq 1 ] && need_tool npm frontend; then
  install_step frontend frontend/node_modules frontend/package-lock.json npm_ci frontend
fi

if [ "$DO_WEBSITE" -eq 1 ] && need_tool npm website; then
  install_step website website/node_modules website/package-lock.json npm_ci website --ignore-scripts
  if [ "$SITE_TOOLS" -eq 1 ]; then
    for tool_dir in website/tools/*/; do
      tool_dir="${tool_dir%/}"
      [ -f "$tool_dir/package-lock.json" ] || continue
      install_step "$(basename "$tool_dir")" "$tool_dir/node_modules" "$tool_dir/package-lock.json" \
        npm_ci "$tool_dir" --ignore-scripts
    done
  fi
  # The Playwright Chromium of the website check: `install --dry-run` lists where each browser belongs; install only when
  # one of those places is missing.
  if [ -d website/node_modules/playwright ]; then
    missing_browser=0
    while IFS= read -r location; do
      [ -d "$location" ] || missing_browser=1
    done < <(npm --prefix website exec -- playwright install --dry-run chromium 2>/dev/null |
      sed -n 's/^ *Install location: *//p')
    if [ "$missing_browser" -eq 1 ]; then
      echo "+ npm --prefix website exec -- playwright install chromium"
      if npm --prefix website exec -- playwright install chromium; then
        note browsers "installed (Chromium for the website check)"
      else
        note browsers "FAILED: playwright install chromium"
        FAILED=1
      fi
    else
      note browsers "ready (Chromium for the website check)"
    fi
  fi
fi

android_env="${SIDEKICK_ANDROID_ENV:-}"
if [ -z "$android_env" ]; then
  note android "not configured: set SIDEKICK_ANDROID_ENV to the environment file that provides JDK 21 and the Android SDK"
elif [ ! -f "$android_env" ]; then
  note android "MISSING: $android_env does not exist, so the Android stage cannot run here"
else
  note android "environment found. Run the Android stage in its own shell, never in this one:"
  note "" "  bash -c '. \"$android_env\" && bash tools/check-all.sh --slot K --skip-backend-tests --skip-backend-static \\"
  note "" "    --skip-policy --skip-shellcheck --skip-actionlint --skip-gitleaks --skip-frontend --skip-mcp-app \\"
  note "" "    --skip-published-tree --skip-website'"
fi

echo
echo "===== worktree-setup ====="
printf '%s\n' "${SUMMARY[@]}"
exit "$FAILED"
