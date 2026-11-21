#!/usr/bin/env python3
"""Entry point: python3 my_solution.py <ingest|brief|ask|forget> ..."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from assist.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
