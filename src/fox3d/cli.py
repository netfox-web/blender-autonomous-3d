from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fox3d.blender import BLOCKED_NO_BLENDER, detect_node
from fox3d.platform import Platform


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fox3d")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("detect")
    sub.add_parser("api")
    run = sub.add_parser("job")
    run.add_argument("json_path")
    run.add_argument("--mock", action="store_true")
    run.add_argument("--root", type=Path)
    args = parser.parse_args(argv)
    if args.cmd is None:
        args.cmd = "api"
    if args.cmd == "detect":
        print(json.dumps(detect_node(), indent=2, default=str))
        return 0
    if args.cmd == "api":
        from fox3d.api import main as api_main

        api_main()
        return 0
    if args.cmd == "job":
        payload = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
        platform = Platform(root=args.root, mock_blender=args.mock)
        job = platform.submit_job(payload)
        result = platform.execute_job(job)
        if (not args.mock and platform.probe is not None and not platform.probe.blender
                and result.get("error") == "NO_ELIGIBLE_TARGET"):
            result["status"] = "blocked"
            result["error"] = BLOCKED_NO_BLENDER
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("status") in {"completed", "succeeded"} else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
