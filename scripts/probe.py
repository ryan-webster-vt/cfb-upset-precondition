"""Run the live capability probe.

Usage:
    python scripts/probe.py --write
    python scripts/probe.py --write --deep-limits
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow ``python scripts/probe.py`` from a fresh checkout without installing.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cfb_upset.pipelines.capabilities import main  # noqa: E402

if __name__ == "__main__":
    main()
