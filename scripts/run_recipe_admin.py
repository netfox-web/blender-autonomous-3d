"""Start the local product recipe workbench alongside the existing admin UI."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("FOX3D_HOST") or "127.0.0.1", help="用 0.0.0.0 才能讓 GPU 艦隊節點抓到參考圖（地端 AI 實景）")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--data-root", type=Path, default=ROOT / ".fox3d-data")
    args = parser.parse_args(argv)
    import uvicorn
    from fox3d.api import create_app
    from fox3d.platform import Platform

    os.environ["FOX3D_BIND_HOST"] = str(args.host)
    os.environ["FOX3D_BIND_PORT"] = str(args.port)
    uvicorn.run(create_app(Platform(args.data_root.resolve())), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
