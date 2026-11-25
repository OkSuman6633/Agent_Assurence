"""Top-level runner for Agent Assurance Laboratory.
Can be executed from anywhere (workspace root, frontend/, or backend/).
"""
import os
import sys
from pathlib import Path

# Locate directories
_this_file = Path(__file__).resolve()
_root_dir = _this_file.parent
_backend_dir = _root_dir / "backend"

# Ensure both backend and root are in sys.path
sys.path.insert(0, str(_backend_dir))
sys.path.insert(0, str(_root_dir))

# Change working directory to backend so relative paths work predictably
os.chdir(str(_backend_dir))

# Default environment variables for dev
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("AUTH_DISABLED", "true")
os.environ.setdefault("AGENT_ASSURANCE_DEV_ALLOW_PRIVATE_HOSTS", "true")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    print(f"\n=======================================================")
    print(f"  Agent Assurance Laboratory Studio")
    print(f"  Listening on: http://127.0.0.1:{port} (host: {host})")
    print(f"  Swagger Docs: http://127.0.0.1:{port}/docs")
    print(f"=======================================================\n")
    uvicorn.run("app.main:app", host=host, port=port, reload=True)
