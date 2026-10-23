from __future__ import annotations

import argparse
import json
from pathlib import Path

from .batch import BatchInterrupted, FixtureBatchRunner
from .fixtures import fixture_manifest_path, load_fixture_manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="隔離 synthetic fixture 預覽；不執行真模型或 ERP 寫入")
    parser.add_argument("--manifest", type=Path, default=fixture_manifest_path())
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--cancel", action="store_true")
    parser.add_argument("--stop-after", type=int)
    args = parser.parse_args(argv)
    manifest = load_fixture_manifest(args.manifest)
    runner = FixtureBatchRunner(args.state_dir)
    if args.cancel:
        print(json.dumps(runner.cancel(manifest), ensure_ascii=False, indent=2))
        return 0
    try:
        output = runner.run(manifest, resume=args.resume, stop_after=args.stop_after)
    except BatchInterrupted as exc:
        print(json.dumps({"status": "INTERRUPTED", "reason": str(exc), "resume": "--resume"}, ensure_ascii=False))
        return 75
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if all(row["status"] == row["expected_status"] for row in output["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
