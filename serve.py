"""Double-click / `python serve.py` entry point. Same as `python -m app`, from any cwd."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from app.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
