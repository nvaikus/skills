#!/usr/bin/env python3
"""Entry point: model-cli (see `model-cli --help`)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from model_cli.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
