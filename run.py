"""Launcher: python3 run.py [--port 8765] [--data ./data]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from shiftpatch.server import main  # noqa: E402

if __name__ == "__main__":
    main()
