#!/usr/bin/env python3
"""Entry point: clockmaster (see `clockmaster help`)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
import cli  # noqa: E402

if __name__ == "__main__":
    sys.exit(cli.main())
