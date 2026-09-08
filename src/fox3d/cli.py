from __future__ import annotations

import argparse
import json
import sys

from fox3d.blender import detect_node
from fox3d.platform import Platform


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fox3d")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("detect")
    sub.add_parser("api")
    run = sub.add_parser("job")
    run.add_argument("json_path")
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
        payload = json.loads(open(args.json_path, encoding="utf-8").read())
        platform = Platform()
        platform.register_node(target_key="cli", name="cli", detected={**detect_node(), "blender": True, "blenderVersion": "mock-4.2", "gpus": [{"gpuIndex": 0, "name": "NVIDIA GeForce RTX 5080", "vramGb": 16}], "gpuName": "NVIDIA GeForce RTX 5080", "vramGb": 16, "gpuCount": 1, "cuda": True, "optix": True})
        job = platform.submit_job(payload)
        result = platform.execute_job(job)
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("status") == "succeeded" else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
