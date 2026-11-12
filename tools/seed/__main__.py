"""Entry point: `uv run --project backend python -m tools.seed --confirm`."""

import sys

from tools.seed.local import main

if __name__ == "__main__":
    sys.exit(main())
