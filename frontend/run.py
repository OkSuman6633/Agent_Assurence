import sys
from pathlib import Path

# Load and execute root run.py
root_run = Path(__file__).resolve().parent.parent / "run.py"
with open(root_run, "r", encoding="utf-8") as f:
    code = compile(f.read(), str(root_run), "exec")
    exec(code, {"__name__": "__main__"})
