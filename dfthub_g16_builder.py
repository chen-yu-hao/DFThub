#!/usr/bin/env python3
"""Deprecated: use ``dfthub g16 build``.

Kept for one release so existing instructions keep working.  Paths stay
relative to this script, as before:

    ./Parameters, ./g16/ (or ./g16.tar.gz, ./CF22Dg16.tar.gz) -> ./g16-opt/

    python3 dfthub_g16_builder.py [--parameters PATH] [--dry-run]

is equivalent to

    dfthub g16 build --source ./g16 --parameters ./Parameters --output ./g16-opt [--dry-run]
"""
import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if (BASE_DIR / "src" / "dfthub").is_dir():
    sys.path.insert(0, str(BASE_DIR / "src"))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Deprecated wrapper for `dfthub g16 build`.")
    parser.add_argument("--parameters", type=Path, default=BASE_DIR / "Parameters", metavar="PATH")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    print("dfthub_g16_builder.py is deprecated; use `dfthub g16 build`.", file=sys.stderr)

    from dfthub.cli import main as dfthub_main

    command = [
        "g16", "build",
        "--source", str(BASE_DIR / "g16"),
        "--parameters", str(args.parameters),
        "--output", str(BASE_DIR / "g16-opt"),
        "--archive", str(BASE_DIR / "g16.tar.gz"),
        "--archive", str(BASE_DIR / "CF22Dg16.tar.gz"),
    ]
    if args.dry_run:
        command.append("--dry-run")
    return dfthub_main(command)


if __name__ == "__main__":
    raise SystemExit(main())
