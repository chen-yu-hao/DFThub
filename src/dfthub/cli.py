import argparse
import fcntl
import json
import os
import sys
from .paths import data_dir, initialize_data, load_environment


def main():
    parser = argparse.ArgumentParser(prog="dfthub")
    parser.add_argument("--version", action="version", version="DFThub 0.1.0")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="Check engine provenance and packaged resources")
    doctor.add_argument("--strict", action="store_true")
    doctor.add_argument("--json", action="store_true")
    serve = commands.add_parser("serve", help="Serve the web application and API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8188)
    serve.add_argument("--data-dir")
    serve.add_argument("--python", help="Compute Python with DFThub and its DFT engine installed")
    args = parser.parse_args()
    try:
        load_environment()
        if getattr(args, "data_dir", None):
            os.environ["DFTHUB_DATA_DIR"] = args.data_dir
        if getattr(args, "python", None):
            os.environ["DFTHUB_PYTHON"] = args.python
        from .doctor import check
        result = check()
        if args.command == "doctor":
            print(json.dumps(result, indent=2) if args.json else "\n".join(
                ["DFThub 0.1.0", f"Data: {data_dir()}", f"Engine: {result['engine']}"] + result["errors"]))
            return int(args.strict and bool(result["errors"]))
        if result["errors"]:
            raise RuntimeError("Environment verification failed: " + "; ".join(result["errors"]))
        root = initialize_data()
        with (root / "server.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("A DFThub service already owns this data directory")
            os.environ.setdefault("DFTHUB_SCHEDULER_DIR", str(root / "scheduler"))
            os.environ.setdefault("DFTHUB_MAIL_SUPPRESS", "1")
            from .server import create_app
            from waitress import serve as run
            print(f"DFThub: http://{args.host}:{args.port} · data {root}", flush=True)
            run(create_app(), host=args.host, port=args.port, threads=8)
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"dfthub: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
