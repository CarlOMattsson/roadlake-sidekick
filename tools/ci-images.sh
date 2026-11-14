# shellcheck shell=bash disable=SC2034
# Container images that the CI jobs and tools/check-all.sh both run, so that a local run and CI see the same
# tool versions, browsers and fonts. Sourced by tools/playwright-docker.sh, tools/shellcheck-ci.sh and
# tools/gitleaks-ci.sh; pinned by tag and digest (the digest is what the daemon verifies).
#
# PLAYWRIGHT_IMAGE must carry the version of @playwright/test in frontend/package.json (a policy test checks it):
# the browsers in the image are the ones that version drives. Upgrade the package and the image together.
# No other file repeats these values.
PLAYWRIGHT_IMAGE="mcr.microsoft.com/playwright:v1.65.0-noble@sha256:9beb546099e11f52d62e505537914870e01a67e0e6b00ae41da4775324e73dbe"
GITLEAKS_IMAGE="ghcr.io/gitleaks/gitleaks:v8.24.3@sha256:e1b35e12a8c6fa8901f060459cfb6b2fc4c484d3afbe3b029733a3bbfab07055"
SHELLCHECK_IMAGE="koalaman/shellcheck:v0.11.0@sha256:61862eba1fcf09a484ebcc6feea46f1782532571a34ed51fedf90dd25f925a8d"
