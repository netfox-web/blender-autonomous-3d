"""Start the local product recipe workbench alongside the existing admin UI."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--data-root", type=Path, default=ROOT / ".fox3d-data")
    args = parser.parse_args(argv)
    import uvicorn
    from fox3d.api import create_app
    from fox3d.platform import Platform

    uvicorn.run(create_app(Platform(args.data_root.resolve())), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
