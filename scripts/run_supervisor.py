"""Start the Autonomous Supervisor service locally."""

from __future__ import annotations

import sys
from pathlib import Path
import uvicorn

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.supervisor.config import load_config
from services.supervisor.main import create_app

if __name__ == "__main__":
    cfg = load_config()
    print(f"Starting Fox3D Autonomous Supervisor on {cfg.host}:{cfg.port}...")
    app = create_app(cfg)
    uvicorn.run(app, host=cfg.host, port=cfg.port)
