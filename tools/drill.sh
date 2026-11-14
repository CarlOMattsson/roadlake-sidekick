#!/usr/bin/env bash
# Disposable-container drill: install -> update -> backup -> destroy -> restore, for the self-hosted stack and for the
# work package, each in its own throw-away compose project (docs/maintainers/release-drill.md).
#
#   bash tools/drill.sh selfhost|work|all [--from-image REF] [--to-image REF] [--cert-identity ID]
#                                          [--local-images] [--allow-same-schema] [--log FILE] [--dry-run]
#
# The options, the safety rules and the exit status (0 all steps passed, 1 a step failed, 2 usage error or refused
# input) are described by tools/workctl/drillrun.py, which holds the whole sequence; run this script without
# arguments to print the options. This file only starts it (standard library only, like tools/work.sh).
set -euo pipefail
umask 077

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
command -v python3 >/dev/null 2>&1 || { echo "drill: python3 is required" >&2; exit 2; }
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$REPO/tools${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m workctl.drillrun "$@"
