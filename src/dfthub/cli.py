import argparse
import json
import os
from pathlib import Path
import platform
import sys

if sys.platform.startswith("linux") and platform.machine().lower() in ("x86_64", "amd64"):
    os.environ.setdefault("OPENBLAS_CORETYPE", "Haswell")

from .paths import data_dir, initialize_data, load_environment

VERSION = "DFThub 0.1.1"
TOOL_COMMANDS = ("params", "export", "g16", "pyscf", "ps", "kill")


def build_parser():
    parser = argparse.ArgumentParser(prog="dfthub")
    parser.add_argument("--version", action="version", version=VERSION)
    commands = parser.add_subparsers(dest="command", required=True)

    doctor = commands.add_parser("doctor", help="Check engine provenance and packaged resources")
    doctor.add_argument("--strict", action="store_true")
    doctor.add_argument("--json", action="store_true")

    serve = commands.add_parser("serve", help="Serve the web application and API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8188)
    serve.add_argument("--data-dir")
    serve.add_argument("--python", help="Compute Python with DFThub and its DFT engine installed")

    ps = commands.add_parser("ps", help="List running DFThub background calculation processes")
    ps.add_argument("--json", action="store_true", help="machine-readable output")

    kill = commands.add_parser("kill", help="Terminate running DFThub background calculation processes")
    kill.add_argument("targets", nargs="*", metavar="PID_OR_OUTPUT",
                      help="process ID(s) or output directory path(s) to terminate")
    kill.add_argument("-a", "--all", action="store_true", help="terminate all running DFThub calculation processes")
    kill.add_argument("--scope", choices=("optimization", "input", "ame418", "energy", "overlap"),
                      help="filter by calculation scope")
    kill.add_argument("--json", action="store_true", help="machine-readable output")

    params = commands.add_parser("params", help="Read and validate a CF22D Parameters file")
    params_actions = params.add_subparsers(dest="action", required=True)
    for name, text in (("check", "Validate a Parameters file or 59-value coefficient file"),
                       ("show", "Print all coefficients with their LibXC names")):
        action = params_actions.add_parser(name, help=text)
        action.add_argument("parameters", metavar="PARAMS", type=Path)
        action.add_argument("--json", action="store_true", help="machine-readable output")

    export = commands.add_parser("export", help="Write an input that applies CF22D parameters in another program")
    export.add_argument("program", choices=("pyscf", "gaussian", "orca", "psi4"))
    export.add_argument("parameters", metavar="PARAMS", type=Path)
    export.add_argument("-o", "--output", type=Path, help="output file (default: standard output)")
    export.add_argument("--no-d3", action="store_true", help="leave out the CF22D D3(0) dispersion correction")
    export.add_argument("--basis", help="basis set for the example input (default depends on the program)")
    export.add_argument("--keyword", help="Gaussian only: route keyword of the patched functional slot (default: MN15)")

    g16 = commands.add_parser("g16", help="Gaussian 16 source build with CF22D parameters")
    g16_actions = g16.add_subparsers(dest="action", required=True)
    build = g16_actions.add_parser("build", help="Patch utilnz.F/utilam.F of a licensed g16 source tree and build it")
    build.add_argument("--source", type=Path, default=Path("g16"), metavar="DIR",
                       help="Gaussian top-level source directory (default: ./g16)")
    build.add_argument("--parameters", type=Path, default=Path("Parameters"), metavar="PATH",
                       help="DFThub Parameters file (default: ./Parameters)")
    build.add_argument("--archive", type=Path, action="append", metavar="TAR",
                       help="source archive to extract when --source is missing "
                            "(default: g16.tar.gz, then CF22Dg16.tar.gz next to --source)")
    build.add_argument("--output", type=Path, metavar="DIR",
                       help="directory the built tree is moved to (default: g16-opt next to --source)")
    build.add_argument("--dry-run", action="store_true",
                       help="check the parameters and locate the source blocks without writing or building")

    pyscf = commands.add_parser("pyscf", help="Run CF22D in PySCF")
    pyscf_actions = pyscf.add_subparsers(dest="action", required=True)
    demo = pyscf_actions.add_parser("demo", help="RKS H2 demo (def2-QZVP, grid level 6, R = 0.74 Angstrom)")
    source = demo.add_mutually_exclusive_group()
    source.add_argument("--parameters", type=Path, default=Path("Parameters"), metavar="PATH",
                        help="DFThub Parameters file (default: ./Parameters)")
    source.add_argument("--original", action="store_true", help="use the embedded original parameter set")
    demo.add_argument("--no-d3", action="store_true", help="run without D3 dispersion")
    return parser


def _params_command(args):
    from .functional.parameters import (
        LIBXC_CX_PARAMS, LIBXC_CY_PARAMS, LIBXC_CZ_PARAMS, LIBXC_HF_PARAM, load_parameters,
    )

    params = load_parameters(args.parameters)
    if args.action == "check":
        info = {"valid": True, "path": str(args.parameters), "coefficients": 59,
                "hf": params.hf, "sha256": params.sha256()}
        print(json.dumps(info, indent=2) if args.json else
              f"{args.parameters}: OK (40 Cx, 9 Cy, 9 Cz, HF = {params.hf:.10f}; sha256 {params.sha256()})")
        return 0
    names = LIBXC_CX_PARAMS + LIBXC_CY_PARAMS[:9] + LIBXC_CZ_PARAMS[:9] + [LIBXC_HF_PARAM]
    labelled = params.labelled()
    if args.json:
        print(json.dumps({
            "path": str(args.parameters), "sha256": params.sha256(), "hf_percent": params.hf_percent,
            "parameters": labelled, "libxc": {"HYB_MGGA_X_CF22D": params.libxc_x_named(),
                                               "MGGA_C_CF22D": params.libxc_c_named()},
        }, indent=2))
        return 0
    print(f"# {args.parameters}  sha256 {params.sha256()}")
    for (label, value), name in zip(labelled.items(), names):
        print(f"{label:<11} {name:<7} {value: .16e}")
    print(f"{'HF%':<11} {'':<7} {params.hf_percent: .16e}")
    return 0


def _export_command(args):
    from .functional import render
    from .functional.parameters import load_parameters

    params = load_parameters(args.parameters)
    options = {}
    if args.basis:
        options["basis"] = args.basis
    if args.keyword:
        if args.program != "gaussian":
            raise ValueError("--keyword applies only to the gaussian export")
        options["keyword"] = args.keyword
    if args.program == "pyscf" and args.basis:
        raise ValueError("--basis does not apply to the pyscf export; set the basis in your own script")
    text = render(args.program, params, with_d3=not args.no_d3, **options)
    if args.output is None or str(args.output) == "-":
        sys.stdout.write(text)
    else:
        args.output.write_text(text)
        print(f"Wrote {args.output}", file=sys.stderr)
    if args.program == "gaussian":
        print("Note: the Gaussian input needs a g16 built with these parameters (dfthub g16 build); "
              "an unpatched Gaussian runs the original functional of that keyword.", file=sys.stderr)
    elif args.program in ("orca", "psi4"):
        print(f"Note: {args.program} must be linked against LibXC >= 7.0 (CF22D); "
              "this input has not been run by DFThub's tests.", file=sys.stderr)
    return 0


def _g16_command(args):
    from .functional import gaussian
    from .functional.parameters import read_parameters

    params = read_parameters(args.parameters)
    top = args.source
    archives = args.archive or [top.parent / name for name in gaussian.DEFAULT_ARCHIVES]
    output = args.output or top.parent / "g16-opt"
    print(f"Parameters: {args.parameters} (HF = {params.hf:.6f}, sha256 {params.sha256()[:16]})", flush=True)
    top = gaussian.prepare_source(top, archives)
    src = gaussian.detect_source_root(top)
    print(f"Gaussian source: {src}", flush=True)
    report = gaussian.patch_sources(src, params, dry_run=args.dry_run)
    for line in report.summary():
        print("  " + line, flush=True)
    if args.dry_run:
        print("Dry run: parameters and source blocks verified; nothing was written or built")
        return 0
    print("Building Gaussian 16 (bsd/bldg16) ...", flush=True)
    gaussian.build(src)
    final = gaussian.finalize(top, output)
    print(f"Built tree: {final}. Run CF22D with the {gaussian.DEFAULT_KEYWORD} keyword of this build "
          f"(see: dfthub export gaussian {args.parameters})")
    return 0


def _pyscf_command(args):
    from .functional.pyscf import run_demo

    parameters = None if args.original else args.parameters
    if parameters is not None and not parameters.exists():
        raise ValueError(f"{parameters} not found; pass --parameters PATH or --original")
    energy = run_demo(parameters, with_d3=not args.no_d3)
    print(f"Total energy: {energy:.10f} Hartree")
    return 0


def _ps_command(args):
    from .processes import tasks

    running = list(tasks())
    if args.json:
        print(json.dumps(running, indent=2))
        return 0
    if not running:
        print("No running DFThub tasks.")
        return 0
    print(f"{'PID':<10} {'MODE':<8} {'SCOPE':<14} OUTPUT")
    for item in running:
        print(f"{item['pid']:<10} {item['mode']:<8} {item['scope']:<14} {item['output']}")
    return 0


def _kill_command(args):
    import psutil
    from .processes import tasks

    if not args.all and not args.targets:
        raise ValueError("Specify at least one PID or output path, or pass --all")

    running = list(tasks())
    if args.scope:
        running = [item for item in running if item["scope"] == args.scope]

    selected_roots = []
    if args.all:
        selected_roots = [item["pid"] for item in running]
    else:
        want_pids = set()
        want_outputs = set()
        for target in args.targets:
            try:
                want_pids.add(int(target))
            except ValueError:
                want_outputs.add(str(Path(target).resolve()))
        for item in running:
            if item["pid"] in want_pids or item["output"] in want_outputs:
                selected_roots.append(item["pid"])

    stopped = {}
    for root_pid in selected_roots:
        try:
            root_proc = psutil.Process(root_pid)
            tree = [p.pid for p in root_proc.children(recursive=True)] + [root_pid]
        except psutil.Error:
            tree = [root_pid]
        for pid in tree:
            if pid == os.getpid():
                continue
            try:
                proc = psutil.Process(pid)
                proc.terminate()
                stopped[pid] = proc
            except psutil.Error:
                pass

    if stopped:
        _, alive = psutil.wait_procs(list(stopped.values()), timeout=2)
        for proc in alive:
            try:
                proc.kill()
            except psutil.Error:
                pass
        psutil.wait_procs(alive, timeout=2)

    killed_pids = sorted(stopped)
    if args.json:
        print(json.dumps({"stopped": len(killed_pids), "pids": killed_pids}, indent=2))
    elif killed_pids:
        print(f"Terminated {len(killed_pids)} process(es): {', '.join(map(str, killed_pids))}")
    else:
        print("No matching DFThub processes found.")
    return 0


def _format_doctor_report(result):
    lines = [VERSION, f"Data: {data_dir()}"]
    engine = result.get("engine") or {}
    if isinstance(engine, dict) and engine:
        lines.append("Engine:")
        for key, value in engine.items():
            lines.append(f"  {key}: {value}")
    else:
        lines.append("Engine: unavailable")
    errors = result.get("errors") or []
    if errors:
        lines.extend(errors)
        lines.append(f"Status: FAILED ({len(errors)} error(s))")
    else:
        lines.append("Status: OK (all checks passed)")
    return "\n".join(lines)


def _run_tool(args):
    handlers = {
        "params": _params_command,
        "export": _export_command,
        "g16": _g16_command,
        "pyscf": _pyscf_command,
        "ps": _ps_command,
        "kill": _kill_command,
    }
    try:
        return handlers[args.command](args)
    except (OSError, ValueError, RuntimeError) as exc:  # GaussianBuildError is a RuntimeError
        print(f"dfthub: {exc}", file=sys.stderr)
        return 1


def main(argv=None):
    if sys.platform.startswith("linux") and platform.machine().lower() in ("x86_64", "amd64"):
        os.environ.setdefault("OPENBLAS_CORETYPE", "Haswell")
    args = build_parser().parse_args(argv)
    if args.command in TOOL_COMMANDS:
        # Parameter and process tools never need the service environment or the engine check.
        return _run_tool(args)
    try:
        load_environment()
        if getattr(args, "data_dir", None):
            os.environ["DFTHUB_DATA_DIR"] = args.data_dir
        if getattr(args, "python", None):
            os.environ["DFTHUB_PYTHON"] = args.python
        from .doctor import check
        result = check(strict=bool(getattr(args, "strict", False)))
        if args.command == "doctor":
            print(json.dumps(result, indent=2) if args.json else _format_doctor_report(result))
            return int(args.strict and bool(result["errors"]))
        if result["errors"]:
            raise RuntimeError("Environment verification failed: " + "; ".join(result["errors"]))
        import fcntl
        root = initialize_data()
        with (root / "server.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("A DFThub service already owns this data directory")
            os.environ.setdefault("DFTHUB_SCHEDULER_DIR", str(root / "scheduler"))
            from .server import create_app
            from .api.mail import describe_mail
            from waitress import serve as run
            app = create_app()
            print(f"DFThub: http://{args.host}:{args.port} · data {root}", flush=True)
            for line in describe_mail(app.config):
                print(line, flush=True)
            run(app, host=args.host, port=args.port, threads=8)
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"dfthub: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
