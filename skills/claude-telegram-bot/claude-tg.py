#!/usr/bin/env python3
"""Entry point: claude-tg (see `claude-tg --help`)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
