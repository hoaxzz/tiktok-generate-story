import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
VENV_PYTHON = BASE_DIR / ".venv" / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")

# If .venv exists and current interpreter is not .venv python, auto-delegate to .venv python
if VENV_PYTHON.exists() and Path(sys.executable).resolve() != VENV_PYTHON.resolve():
    print(f"[*] Menggunakan virtual environment: {VENV_PYTHON}")
    try:
        proc = subprocess.run([str(VENV_PYTHON)] + sys.argv)
        sys.exit(proc.returncode)
    except KeyboardInterrupt:
        sys.exit(0)

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
