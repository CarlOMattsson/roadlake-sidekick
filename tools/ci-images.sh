# shellcheck shell=bash disable=SC2034
# Container images that the CI jobs and tools/check-all.sh both run, so that a local run and CI see the same
# tool versions, browsers and fonts. Sourced by tools/playwright-docker.sh, tools/shellcheck-ci.sh,
# tools/actionlint-ci.sh, tools/gitleaks-ci.sh and tools/image-scan.sh; pinned by tag and digest (the digest is what the daemon verifies).
#
# PLAYWRIGHT_IMAGE must carry the version of @playwright/test in frontend/package.json (a policy test checks it):
# the browsers in the image are the ones that version drives. Upgrade the package and the image together.
# No other file repeats these values.
PLAYWRIGHT_IMAGE="mcr.microsoft.com/playwright:v1.65.1-noble@sha256:1507cbfc550a63a6b7396791ca4f00df17beb56342d2447b3f106c306f525579"
GITLEAKS_IMAGE="ghcr.io/gitleaks/gitleaks:v8.24.3@sha256:e1b35e12a8c6fa8901f060459cfb6b2fc4c484d3afbe3b029733a3bbfab07055"
SHELLCHECK_IMAGE="koalaman/shellcheck:v0.11.0@sha256:61862eba1fcf09a484ebcc6feea46f1782532571a34ed51fedf90dd25f925a8d"
# actionlint, which checks the workflow files. Its image carries its own ShellCheck for the run: blocks, and that one must be
# the version of SHELLCHECK_IMAGE (v0.11.0 in both), so a script is judged the same way inside and outside a workflow.
ACTIONLINT_IMAGE="rhysd/actionlint:1.7.12@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667"
# Trivy, at the version the release workflow's scan runs (.github/workflows/release-image.yml), for tools/image-scan.sh.
TRIVY_IMAGE="ghcr.io/aquasecurity/trivy:0.70.0@sha256:be1190afcb28352bfddc4ddeb71470835d16462af68d310f9f4bca710961a41e"
