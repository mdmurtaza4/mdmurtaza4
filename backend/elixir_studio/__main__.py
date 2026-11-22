"""Command line: python -m elixir_studio <command>."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import pipeline
from .hardware import detect


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="elixir_studio", description="ELiXIR AI Video Studio engine")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("detect", help="Inspect GPU, RAM, FFmpeg encoders and recommend settings")

    pr = sub.add_parser("process", help="Analyse and render a speech video")
    pr.add_argument("video", type=Path)
    pr.add_argument("--project", type=Path, help="Project folder (default: projects/<video name>)")
    pr.add_argument("--preset", action="append", choices=["vertical", "landscape", "square"])
    pr.add_argument("--model", help="Whisper model (default: chosen from hardware)")
    pr.add_argument("--device", choices=["auto", "cuda", "cpu"])
    pr.add_argument("--language", help="Force a language code, e.g. en, ur, hi")
    pr.add_argument("--no-transcribe", action="store_true")

    sv = sub.add_parser("serve", help="Start the local API for the desktop app")
    sv.add_argument("--port", type=int, default=8765)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.cmd == "detect":
        print(json.dumps(detect().to_dict(), indent=2))
        return 0

    if args.cmd == "process":
        project = args.project or Path("projects") / args.video.stem
        pipeline.analyse(project, args.video, args.model, args.device, args.language, not args.no_transcribe)
        ok = True
        for preset in args.preset or ["vertical"]:
            out, report = pipeline.produce(project, preset)
            print(f"\n{out}")
            for c in report.checks:
                mark = "PASS" if c.passed else ("FAIL" if c.blocking else "WARN")
                print(f"  [{mark}] {c.name}: {c.detail}")
            ok = ok and report.passed
        return 0 if ok else 1

    if args.cmd == "serve":
        import uvicorn  # noqa: PLC0415

        uvicorn.run("elixir_studio.api:app", host="127.0.0.1", port=args.port)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
