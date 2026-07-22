from __future__ import annotations

import argparse
from pathlib import Path

from .manifest import load_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline Heartbeat distillation replay")
    parser.add_argument("--seed", required=True, help="Seed JSONL path")
    parser.add_argument("--manifest-root", required=True, help="Root containing replay audio manifests/assets")
    parser.add_argument("--manifest", help="Explicit manifest JSONL path")
    parser.add_argument("--config", required=True, help="Replay config YAML path")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate inputs without running server replay",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    seed = Path(args.seed)
    manifest_root = Path(args.manifest_root)
    config = Path(args.config)
    out = Path(args.out)

    missing = [str(path) for path in (seed, manifest_root, config) if not path.exists()]
    if missing:
        raise SystemExit(f"missing required path(s): {', '.join(missing)}")

    if args.manifest:
        manifest = load_manifest(args.manifest)
        missing_audio = manifest.validate_audio_paths(manifest_root)
        if missing_audio:
            raise SystemExit(f"manifest references missing audio: {missing_audio[:5]}")

    out.mkdir(parents=True, exist_ok=True)
    if args.validate_only:
        return 0
    raise SystemExit("server replay runner is not implemented yet")


if __name__ == "__main__":
    raise SystemExit(main())
