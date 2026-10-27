"""
Author: yangxuangui1999@gmail.com
Date: 2022-12-18 13:47:53
LastEditors: yangxuangui1999@gmail.com
LastEditTime: 2023-03-31 23:32:39
"""

# python
import os
import collections
import shlex
import shutil
import threading
import subprocess
import json
import time
import re
import sys
import fcntl
import signal
from pathlib import Path
from apiflask.validators import OneOf

# modules
from apiflask import APIBlueprint,APIFlask, Schema

# from Flask import jsonify, input
from apiflask.fields import String,Dict,Email
from flask import g, request

from werkzeug.serving import run_simple
# from flask_mail import Mail, Message


from dfthub.api.config import DATA_DIR
from dfthub.api.file_api import resolve_owned_path, valid_path_component
from dfthub.api.file_api import app as file_api_app

from dfthub.api.mail import DefaltMailConfig, mail, send_task_notification

from dfthub.api.auth import auth_app, is_valid_email, login_required

from dfthub.paths import PROGRAM_DIR, RESOURCES, pipeline_python
from dfthub.pipeline.refinement import ensure_optimizer_snapshot, file_hash, write_json
from dfthub.pipeline.testset_inheritance import inherit_test_set
from dfthub.pipeline.compute_scheduler import TASK_THREADS
import psutil
PIPELINE_PYTHON = pipeline_python()

DEFAULT_BASIS = "def2-qzvp"
SUPPORTED_BASIS = (
    "sto-3g",
    "6-31g(d)",
    "def2-svp",
    "def2-tzvp",
    "def2-tzvpd",
    "cc-pvtz",
    "def2-qzvppd",
    "def2-qzvp",
    "def2-qzvpp",
    "aug-pc-3",
    "aug-pc-4",
    "aug-cc-pvqz",
    "cc-pvqz",
    "aug-cc-pcv5z",
    "d-aug-cc-pv5z",
    "aug-cc-pwcvqz-pp",
    "lanl2dz-ecp",
    "def2-svp-ecp",
    "def2-tzvp-ecp",
    "def2-qzvppd-ecp",
    "def2-qzvp-ecp",
)
# Keep API validation synchronized with the PySCF resolver used by main.py.
# The UI can expose additional verified presets (including aug-cc-pVTZ and
# Jensen/Pople families); validating against a second stale tuple caused 422.
from dfthub.pipeline.basis_presets import SUPPORTED_BASIS as _PIPELINE_SUPPORTED_BASIS
SUPPORTED_BASIS = tuple(_PIPELINE_SUPPORTED_BASIS)

# Analyze reads a small, stable set of result files for every completed Run.
# Keeping this cache in the API process removes the per-file request fan-out
# from the browser while still invalidating immediately when a calculation
# writes a new result or status file.
_ANALYSIS_CACHE = {}
_ANALYSIS_SUMMARY_CACHE = {}
_ANALYSIS_CACHE_TTL = max(1.0, float(os.environ.get("DFTHUB_ANALYSIS_CACHE_TTL", "5")))
_ANALYSIS_FILE_NAMES = (
    "Mue", "weight.csv", "OriginalMue", "OriginalMue.meta.json",
    "TestMue", "TestOriginalMue", "TestOriginalMue.meta.json", "run.json",
    "InputDescriptors.json", "SinglePointResults.input.json",
    "spe_input.status.json", "SinglePointResults.energy.json", "spe_energy.status.json", "SinglePointResults.json", "OptimizationStatus.json",
    "initial-params.txt", "NEW-params.txt", "process.log",
)

# 先用app构建蓝图
app = APIBlueprint("Base",__name__,
               url_prefix='/api_dft')

# mail = Mail(app)

# start
@app.route("/")
def api_index():
    req = "See <a href='docs'>DOCS</a>"
    return req

class DFT_IN(Schema):
    mode = String(required=True, validate=OneOf(["new", "optim", "spe", "refine"]), metadata={"description": "Operation: new, optim, spe or refine."})
    work_dir = String(required=True, metadata={"description": "Owned path in the form Work/<username>/<job>."})
    weightFile = String(required=True, metadata={"description": "Weight run name, for example weight_0."})
    basis = String(required=False, validate=OneOf(SUPPORTED_BASIS), metadata={"description": "PySCF basis preset used for a new calculation."})
    spe_scope = String(required=False, validate=OneOf(["input", "ame418", "energy", "overlap"]), metadata={"description": "Self-consistent calculation scope."})
    energy_task = String(required=False, metadata={"description": "Named DFT energy task folder for the selected Run."})
    fork = String(required=False, metadata={"description": "Fork directory such as fork-1 for SPE/refinement."})
    descriptor_snapshot_id = String(required=False, metadata={"description": "Grid-6 Input descriptor snapshot identifier for refinement."})
    email = Email(required=False, metadata={"description": "Notification email; defaults to the authenticated user's email."})
    reMark = String(required=False, metadata={"description": "Optional user note stored with the submission."})


class CANCEL_IN(Schema):
    work_dir = String(required=True)
    weightFile = String(required=True)
    fork = String(required=False)
    spe_scope = String(required=False, validate=OneOf(["input", "ame418", "energy", "overlap"]))


class TEST_IN(Schema):
    data = Dict()

@app.post("/test")
@app.doc(summary="Diagnostic submission test", description="Authenticated diagnostic endpoint used to validate request handling.", security=[{"bearerAuth": []}])
@login_required
@app.input(TEST_IN)
def test_submit(json_data):
    init_wegit = json_data['data']['init_weight']
    print("init_wegit",init_wegit)
    print(json_data,file=open(DATA_DIR / "diagnostic.json", "w"))
    return{"msg":"ok"}


# ---- Per-user fair task queue ----
_QUEUE_WORKERS = max(0, int(os.environ.get("DFTHUB_WORKERS", "4")))


class _FairQueue:
    """Per-user round-robin dispatch queue."""

    def __init__(self):
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)
        self._queues = collections.defaultdict(collections.deque)
        self._users = collections.deque()
        self._user_set = set()
        self._running = {}

    def put(self, job):
        user = job.get("user", "")
        with self._lock:
            if job.get("output_dir"):
                _cancel_marker(job["output_dir"], job.get("spe_scope")).unlink(missing_ok=True)
            self._queues[user].append(job)
            if user not in self._user_set:
                self._users.append(user)
                self._user_set.add(user)
            self._not_empty.notify()

    def get(self):
        with self._not_empty:
            while not self._users:
                self._not_empty.wait()
            user = self._users[0]
            job = self._queues[user].popleft()
            if not self._queues[user]:
                self._users.popleft()
                self._user_set.discard(user)
                del self._queues[user]
            else:
                self._users.rotate(-1)
            self._running[threading.get_ident()] = job
            return job

    def task_done(self):
        with self._lock:
            self._running.pop(threading.get_ident(), None)

    def activity(self):
        """Snapshot actual queued/dispatched work, independent of old log text."""
        with self._lock:
            jobs = [(job, "Queued") for queue in self._queues.values() for job in queue]
            jobs += [(job, "Running") for job in self._running.values()]
            return {(str(Path(job["output_dir"]).resolve()), job.get("spe_scope") or "optimization"):
                    {"status": status, "mode": job.get("mode", "")}
                    for job, status in jobs if job.get("output_dir")}

    def discard_pending(self, output, scope=None, recursive=False):
        target = Path(output).resolve()
        removed = []
        with self._lock:
            for user, jobs in list(self._queues.items()):
                keep = collections.deque()
                for job in jobs:
                    path = Path(job["output_dir"]).resolve() if job.get("output_dir") else None
                    matches = path is not None and (path.is_relative_to(target) if recursive else
                                                    path == target and job.get("spe_scope") == scope)
                    (removed if matches else keep).append(job)
                if keep:
                    self._queues[user] = keep
                else:
                    del self._queues[user]
                    self._user_set.discard(user)
            self._users = collections.deque(user for user in self._users if user in self._user_set)
        return removed

    def qsize(self):
        with self._lock:
            return sum(len(q) for q in self._queues.values())


_task_queue = _FairQueue()
_spe_lock = threading.Lock()
_spe_inflight = set()
_CANCEL_MARKER = ".cancel_requested"


def _cancel_marker(output, scope=None):
    suffix = f".{scope}" if scope else ""
    return Path(output) / f"{_CANCEL_MARKER}{suffix}"


def _cancel_requested(job):
    output = job.get("output_dir")
    return bool(output and _cancel_marker(output, job.get("spe_scope")).exists())


def _process_tree(root_pid):
    try:
        return [p.pid for p in psutil.Process(root_pid).children(recursive=True)] + [root_pid]
    except psutil.Error:
        return []


def _task_processes(output, scope=None):
    from dfthub.processes import tasks
    target = str(Path(output).resolve())
    return [p['pid'] for p in tasks() if p['output'] == target and
            (scope is None or p['scope'] == scope)]


def _stop_task_processes(output, scope=None):
    stopped = {}
    for root in _task_processes(output, scope):
        for pid in _process_tree(root):
            if pid == os.getpid():
                continue
            try:
                proc = psutil.Process(pid)
                proc.terminate()
                stopped[pid] = proc
            except psutil.Error:
                pass
    _, alive = psutil.wait_procs(list(stopped.values()), timeout=2)
    for proc in alive:
        try:
            proc.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(alive, timeout=2)
    return len(stopped)


def _mark_cancelled(output, scope=None):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    marker = _cancel_marker(output, scope)
    marker.write_text(json.dumps({"scope": scope, "requested_at": time.time()}) + "\n")
    _discard_pending_tasks(output, scope)
    if scope:
        target = output / f"spe_{scope}.status.json"
        target.write_text(json.dumps({"scope": scope, "status": "Cancelled", "updated_at": time.time()}) + "\n")
        log_path = output / f"spe_{scope}.log"
    else:
        log_path = output / "process.log"
    with log_path.open("a") as handle:
        handle.write("[Interrupted] Task cancelled by the user.\n")


def _discard_pending_tasks(output, scope=None, recursive=False):
    removed = _task_queue.discard_pending(output, scope, recursive)
    with _spe_lock:
        for job in removed:
            if job.get("spe_key"):
                _spe_inflight.discard(job["spe_key"])


def _queued_task(output, scope=None):
    return (str(Path(output).resolve()), scope or "optimization") in _task_queue.activity()


def _write_spe_status(job, status):
    if not job.get("spe_scope"):
        return
    target = Path(job["out_log"]).with_suffix(".status.json")
    payload = {"scope": job["spe_scope"], "status": status, "updated_at": time.time()}
    try:
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload) + "\n")
        temporary.replace(target)
    except OSError as exc:
        print(f"[queue] could not update SPE status: {exc}", flush=True)


def _spe_result_complete(job):
    """Treat a published complete result as authoritative over a stale status."""
    scope = job.get("spe_scope")
    output = job.get("output_dir")
    if not scope or not output:
        return False
    try:
        return json.loads(
            (Path(output) / f"SinglePointResults.{scope}.json").read_text()
        ).get("complete") is True
    except (OSError, ValueError, TypeError):
        return False


def _send_completion_email(job, success: bool):
    try:
        with appx.app_context():
            send_task_notification(
                job["email"],
                job["user"],
                job["mode"],
                job["work_name"] + (f" ({job['spe_scope'].upper()})" if job.get("spe_scope") else ""),
                job["weight_name"],
                "completed",
                success=success,
            )
    except Exception as exc:
        print(f"[mail] completion email error: {exc}", flush=True)


def _send_submission_email(job):
    try:
        send_task_notification(
            job["email"],
            job["user"],
            job["mode"],
            job["work_name"] + (f" ({job['spe_scope'].upper()})" if job.get("spe_scope") else ""),
            job["weight_name"],
            "submitted",
        )
    except Exception as exc:
        print(f"[mail] submission email error: {exc}", flush=True)


def _try_generate_cf22d(job):
    """After optimization, generate CF22D_optimized.py from NEW-params.txt."""
    try:
        info_dir = job.get("info_dir", "")
        if not info_dir:
            return
        output_dir = Path(DATA_DIR) / info_dir
        new_params = output_dir / "NEW-params.txt"
        cf22d_opt = output_dir / "CF22D_optimized.py"
        if new_params.exists() and not cf22d_opt.exists():
            import sys as _sys
            prog_dir = str(PROGRAM_DIR)
            if prog_dir not in _sys.path:
                _sys.path.insert(0, prog_dir)
            from dfthub.pipeline.main import generate_demo_script
            generate_demo_script(str(new_params), str(cf22d_opt))
            print(f"[worker] generated {cf22d_opt}", flush=True)
    except Exception as exc:
        print(f"[worker] CF22D generation failed: {exc}", flush=True)


def _append_task_error(out_log, error):
    if not out_log:
        return
    try:
        with open(out_log, "a") as log_file:
            log_file.write(f"[Error] {error}\n")
    except Exception as log_error:
        print(f"[queue] unable to write task error log: {log_error}", flush=True)


def _task_worker():
    while True:
        job = _task_queue.get()
        success = False
        out_log = None
        try:
            cmd = job["cmd"]
            user = job.get("user", "?")
            out_log = job.get("out_log")
            display_cmd = shlex.join(str(part) for part in cmd)
            if _cancel_requested(job):
                _append_task_error(out_log, "Task cancelled before it started")
                continue
            _write_spe_status(job, "Running")
            print(f"[queue] start ({user}): {display_cmd}", flush=True)
            if out_log:
                with open(out_log, "a") as log_fh:
                    result = subprocess.run(
                        cmd,
                        shell=False,
                        stdout=log_fh,
                        stderr=subprocess.STDOUT,
                    )
                    if result.returncode == 0:
                        log_fh.write("SUCCESS!\n")
                        success = True
                    else:
                        log_fh.write(f"[Error] process exited with code {result.returncode}\n")
            else:
                result = subprocess.run(cmd, shell=False)
                success = (result.returncode == 0)
            cancelled = _cancel_requested(job)
            if cancelled:
                _append_task_error(out_log, "Task interrupted by the user")
            print(f"[queue] done  ({user}): {display_cmd}", flush=True)
            if success:
                _try_generate_cf22d(job)
        except Exception as exc:
            _append_task_error(out_log, exc)
            print(f"[queue] task failed: {exc}", flush=True)
        finally:
            complete = _spe_result_complete(job)
            _write_spe_status(
                job,
                "Success" if success or complete else
                "Cancelled" if _cancel_requested(job) else "Failed",
            )
            if job.get("spe_key"):
                with _spe_lock:
                    _spe_inflight.discard(job["spe_key"])
            _send_completion_email(job, success)
            _task_queue.task_done()


for _wi in range(_QUEUE_WORKERS):
    threading.Thread(target=_task_worker, daemon=True, name=f"dft-worker-{_wi}").start()


def _find_user_archive(input_dir: Path):
    for ext in (".zip", ".tgz", ".tar.gz"):
        for f in sorted(input_dir.glob(f"*{ext}")):
            return f
    return None


def _find_user_ref(input_dir: Path):
    if not input_dir.is_dir():
        return None
    for f in sorted(input_dir.iterdir()):
        if f.is_file() and (f.name.endswith("_ref") or f.suffix == ".ref"):
            return f
    return None


def _error(message, status=400):
    return {"result": "error", "msg": message}, status


def _validated_work_dir(work_dir, username):
    if not isinstance(work_dir, str):
        return None, None
    parts = Path(work_dir).parts
    if (
        len(parts) != 3
        or parts[0] != "Work"
        or parts[1] != username
        or not valid_path_component(parts[2])
    ):
        return None, None
    return resolve_owned_path(work_dir, username, minimum_user_depth=1), parts[2]


def _find_named_archive(input_dir, dataset_name):
    exact_names = (
        f"{dataset_name}.tgz",
        f"{dataset_name}.tar.gz",
        f"{dataset_name}.zip",
    )
    for name in exact_names:
        candidate = input_dir / name
        if candidate.is_file():
            return candidate
    for candidate in sorted(input_dir.iterdir()):
        if (
            candidate.is_file()
            and candidate.name.startswith(dataset_name)
            and candidate.name.endswith((".tgz", ".tar.gz", ".zip"))
        ):
            return candidate
    return None


def _copy_upload_files(upload_dir, input_dir):
    input_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = upload_dir / "test_manifest.json"
    test_names = set()
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text())
            test_names = {manifest["geometry"], manifest["reference"]}
        except (OSError, ValueError, KeyError, TypeError):
            raise ValueError("test_manifest.json is invalid")
        if len(test_names) != 2 or any(not valid_path_component(name) for name in test_names):
            raise ValueError("test_manifest.json contains invalid test filenames")
        test_dir = input_dir / "test_set"
        test_dir.mkdir(parents=True, exist_ok=True)
        for name in test_names:
            source = upload_dir / name
            if not source.is_file():
                raise ValueError(f"Test file not found: {name}")
            shutil.copy2(source, test_dir / name)
        (test_dir / "manifest.json").write_text(json.dumps({
            "geometry": manifest["geometry"], "reference": manifest["reference"],
            "dataset": manifest.get("dataset", Path(manifest["geometry"]).stem),
        }) + "\n")
    for source in upload_dir.iterdir():
        if source.name == "test_manifest.json" or source.name in test_names:
            continue
        if source.is_symlink():
            continue
        destination = input_dir / source.name
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        elif source.is_file():
            shutil.copy2(source, destination)


def _run_output(data, work_name, username):
    suffix = f"/{data['fork']}" if data.get("fork") else ""
    return resolve_owned_path(
        f"Work/{username}/{work_name}/output/{data['weightFile']}{suffix}", username,
        minimum_user_depth=1,
    )


def _run_inputs(output, full_work_dir):
    return output / "input" if (output / "input").is_dir() else full_work_dir / "input"


def _submit_refine(data, full_work_dir, work_name, username, recipient):
    parent = _run_output(data, work_name, username)
    snapshot_id = data.get("descriptor_snapshot_id", "")
    if not re.fullmatch(r"[a-f0-9]{32}", snapshot_id):
        return _error("A valid Input descriptor snapshot is required")
    if not parent.is_dir():
        return _error("Parent run not found", 404)
    weight_root = full_work_dir / "output" / data["weightFile"]
    with _spe_lock, (weight_root / ".refine.lock").open("a") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        if (str(parent), "input") in _spe_inflight:
            return _error("Input is queued or running; wait before refining", 409)
        try:
            status_file = parent / "spe_input.status.json"
            if status_file.exists() and json.loads(status_file.read_text())["status"] != "Success":
                return _error("Complete Calculate Input successfully before refining", 409)
            snapshot = resolve_owned_path(str(parent.relative_to(DATA_DIR) / "input_srp" / snapshot_id), username)
            metadata = json.loads((snapshot / "manifest.json").read_text())
            latest = json.loads((parent / "InputDescriptors.json").read_text())
            result = json.loads((parent / "SinglePointResults.input.json").read_text())
            if (not metadata["complete"] or metadata["grid_level"] != 6 or latest["id"] != snapshot_id
                    or not result["complete"] or result.get("trainingComplete", True) is not True
                    or result.get("descriptor_snapshot_id") != snapshot_id):
                return _error("Recalculate Input at grid 6 to produce current descriptors", 409)
            input_dir = _run_inputs(parent, full_work_dir)
            geometry, reference = _find_user_archive(input_dir), _find_user_ref(input_dir)
            checks = {
                "parameter_sha256": parent / "NEW-params.txt",
                "functional_sha256": parent / "CF22D_optimized.py",
                "weight_sha256": parent / "weight.csv",
                "source_input_sha256": parent / "INPUT",
                "reference_sha256": reference,
                "geometry_sha256": geometry,
                "descriptor_sha256": snapshot / "INPUT",
            }
            if any(path is None or file_hash(path) != metadata[key] for key, path in checks.items()):
                return _error("Input sources changed; recalculate Input before refining", 409)
            if file_hash(parent / "INPUT_ref") != metadata["reference_sha256"]:
                return _error("Input reference changed; recalculate Input before refining", 409)
            saved_basis = (input_dir / "basis.txt").read_text().strip() if (input_dir / "basis.txt").is_file() else DEFAULT_BASIS
            if saved_basis != metadata["basis"]:
                return _error("Input basis changed; recalculate Input before refining", 409)
            for name, key in (("NEW-params.txt", "parameter_sha256"), ("weight.csv", "weight_sha256"),
                              ("input/INPUT_ref", "reference_sha256"), ("input/" + metadata["geometry"], "geometry_sha256")):
                if file_hash(snapshot / name) != metadata[key]:
                    return _error("Input descriptor snapshot is inconsistent", 409)
            forks = [p for p in weight_root.iterdir() if re.fullmatch(r"fork-[1-9]\d*", p.name) and p.is_dir()]
            parent_id = data["weightFile"] + ("/" + data["fork"] if data.get("fork") else "")
            for previous in forks:
                info_file = previous / "run.json"
                if info_file.is_file():
                    info = json.loads(info_file.read_text())
                    if info.get("parent") == parent_id and info.get("descriptor_snapshot_id") == snapshot_id:
                        inherit_test_set(parent, previous, full_work_dir)
                        return {"result": "work submit success", "run_id": f"{data['weightFile']}/{previous.name}", "existing": True}
            frozen = ensure_optimizer_snapshot(parent)
            number = max((int(p.name[5:]) for p in forks), default=0) + 1
            child = weight_root / f"fork-{number}"
            child.mkdir()
            shutil.copytree(frozen, child / "optimizer_snapshot")
            shutil.copytree(snapshot / "input", child / "input")
            for source, destination in (("INPUT", "INPUT"), ("input/INPUT_ref", "INPUT_ref"),
                                        ("weight.csv", "weight.csv"), ("NEW-params.txt", "initial-params.txt")):
                shutil.copy2(snapshot / source, child / destination)
            inherit_test_set(parent, child, full_work_dir)
            write_json(child / "run.json", {
                "parent": parent_id, "descriptor_snapshot_id": snapshot_id,
                "grid_level": 6, "basis": metadata["basis"], "created_at": time.time(),
                "initial_parameter_sha256": metadata["parameter_sha256"],
                "descriptor_sha256": metadata["descriptor_sha256"],
            })
        except (OSError, ValueError, KeyError) as exc:
            return _error(f"Cannot create refinement: {exc}", 409)
        run_id = f"{data['weightFile']}/{child.name}"
        out_log = child / "process.log"
        out_log.write_text("QUEUED\nRefining with self-consistent Input descriptors\n")
        job = {
            "cmd": [PIPELINE_PYTHON, str(PROGRAM_DIR / "opt_demo.py"),
                    "--fit", str(child / "INPUT"), "--ref", str(child / "INPUT_ref"),
                    "--weights-csv", str(child / "weight.csv"), "--output", str(child),
                    "--template-dir", str(child / "optimizer_snapshot"),
                    "--initial-params", str(child / "initial-params.txt")],
            "out_log": str(out_log), "user": username, "mode": "refine",
            "work_name": work_name, "weight_name": run_id, "work_dir": data["work_dir"],
            "info_dir": str(child.relative_to(DATA_DIR)), "email": recipient,
            "output_dir": str(child),
        }
        _task_queue.put(job)
    _send_submission_email(job)
    return {"result": "work submit success", "run_id": run_id, "existing": False}


def _submit_spe(data, full_work_dir, work_name, username, recipient, basis):
    scope = data.get("spe_scope", "input")
    weight_name = data["weightFile"]
    output = _run_output(data, work_name, username)
    if data.get("fork"):
        weight_name += "/" + data["fork"]
    if not output.is_dir():
        return _error("Weight run not found", 404)
    user_archive = user_ref = None
    energy_task = data.get("energy_task", "").strip()
    if scope == "energy":
        if not valid_path_component(energy_task):
            return _error("energy_task must be a named single path component")
        energy_dir = output / "energy_input" / energy_task
    else:
        energy_dir = output / "energy_input"
    if scope == "energy":
        user_archive = _find_user_archive(energy_dir)
        if not user_archive:
            return _error("DFT energy calculation requires an uploaded .tgz archive")
        run_basis = output / "basis.txt"
        if run_basis.is_file():
            basis = run_basis.read_text().strip() or basis

    if scope == "input":
        input_dir = _run_inputs(output, full_work_dir)
        user_archive = _find_user_archive(input_dir)
        user_ref = _find_user_ref(input_dir)
        if (input_dir / "basis.txt").exists():
            basis = (input_dir / "basis.txt").read_text().strip()
        if not user_archive or not user_ref:
            return _error("Input calculation requires both the uploaded geometry archive and reference file")
    test_archive = test_ref = None
    if scope == "input":
        test_dir = input_dir / "test_set"
        manifest_path = test_dir / "manifest.json"
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text())
                test_archive = test_dir / manifest["geometry"]
                test_ref = test_dir / manifest["reference"]
            except (OSError, ValueError, KeyError, TypeError):
                return _error("Test set manifest is invalid")
            if not test_archive.is_file() or not test_ref.is_file():
                return _error("Test set files are incomplete")
    cf22d_opt = output / "CF22D_optimized.py"
    if scope != "overlap" and not cf22d_opt.is_file() and not (output / "NEW-params.txt").is_file():
        return _error("No optimized functional found. Run optimization first.")
    key = (str(output), scope, energy_task if scope == "energy" else "")
    with _spe_lock:
        if key in _spe_inflight:
            return _error(f"A {scope} calculation is already queued or running for this weight", 409)
        _spe_inflight.add(key)
    queued = False
    try:
        if scope != "overlap" and not cf22d_opt.is_file():
            import sys as _sys
            prog_dir = str(PROGRAM_DIR)
            _sys.path.insert(0, prog_dir)
            try:
                from dfthub.pipeline.main import generate_demo_script
                generate_demo_script(str(output / "NEW-params.txt"), str(cf22d_opt))
            finally:
                _sys.path.pop(0)
            if not cf22d_opt.is_file():
                return _error("Optimized parameters could not be loaded")
        if scope == "overlap":
            command = [
                PIPELINE_PYTHON, str(PROGRAM_DIR / "run_ame418_srp.py"),
                "--output", str(output), "--scope", "input", "--overlap-only", "--cores", str(min(8, TASK_THREADS)),
            ]
        elif scope == "energy":
            command = [
                PIPELINE_PYTHON, str(PROGRAM_DIR / "run_user_energy.py"),
                "--cf22d-optimized", str(cf22d_opt), "--output", str(energy_dir),
                "--user-xyz", str(user_archive), "--user-basis", basis,
                "--grid", "6", "--cores", str(TASK_THREADS),
            ]
        else:
            command = [
            PIPELINE_PYTHON, str(PROGRAM_DIR / "run_ame418_srp.py"),
            "--cf22d-optimized", str(cf22d_opt), "--output", str(output),
            "--scope", scope, "--cores", str(TASK_THREADS),
            ]
        if scope == "input":
            command.extend(["--user-xyz", str(user_archive), "--user-ref", str(user_ref), "--user-basis", basis, "--grid", "6"])
            if test_archive and test_ref:
                command.extend(["--test-xyz", str(test_archive), "--test-ref", str(test_ref)])
        task_output = energy_dir if scope == "energy" else output
        task_output.mkdir(parents=True, exist_ok=True)
        out_log = task_output / f"spe_{scope}.log"
        with out_log.open("a") as handle:
            handle.write(f"QUEUED\nSelf-consistent calculation scope: {scope}\n")
        job = {
            "cmd": command, "out_log": str(out_log), "user": username, "mode": "spe",
            "spe_scope": scope, "spe_key": key, "work_name": work_name,
            "weight_name": weight_name, "work_dir": data["work_dir"],
            "info_dir": f"Work/{username}/{work_name}/output/{weight_name}" + (f"/energy_input/{energy_task}" if scope == "energy" else ""), "email": recipient,
            "output_dir": str(energy_dir if scope == "energy" else output),
        }
        _write_spe_status(job, "Queued")
        _task_queue.put(job)
        queued = True
        count_path = Path(DATA_DIR) / "submit_count.txt"
        try:
            count = int(count_path.read_text().strip()) + 1
        except (FileNotFoundError, ValueError):
            count = 1
        count_path.write_text(str(count))
        _send_submission_email(job)
        return {"result": "work submit success", "task_count": count, "spe_scope": scope}
    finally:
        if not queued:
            with _spe_lock:
                _spe_inflight.discard(key)


@app.post("/submit")
@app.doc(summary="Submit a calculation", description="Create, optimize, refine or start a self-consistent calculation for the authenticated user's Job.", security=[{"bearerAuth": []}])
@login_required
@app.input(DFT_IN)
def dft_submit(json_data):
    data = dict(json_data)
    mode = data["mode"]
    work_dir = data["work_dir"]
    weightFile = data["weightFile"]
    username = g.current_user["username"]
    work_parts = Path(work_dir).parts if isinstance(work_dir, str) else ()
    if len(work_parts) >= 2 and work_parts[0] == "Work" and work_parts[1] != username:
        return _error("work_dir does not belong to the authenticated user", 403)
    full_work_dir, work_name = _validated_work_dir(work_dir, username)
    if full_work_dir is None:
        return _error("work_dir must be Work/<authenticated user>/<work id>")
    if not valid_path_component(weightFile):
        return _error("weightFile must be a single valid path component")
    if data.get("fork") and (mode not in ("spe", "refine") or not re.fullmatch(r"fork-[1-9]\d*", data["fork"])):
        return _error("fork must be fork-N and is only accepted for SPE or refinement")
    if not full_work_dir.exists():
        return _error("Work directory not found", 404)

    alternate_email = (data.get("email") or "").strip().lower()
    recipient = alternate_email or (g.current_user.get("email") or "").strip().lower()
    if not is_valid_email(recipient):
        return _error("A valid notification email is required")
    data["email"] = recipient

    weight_path = full_work_dir / "output" / weightFile / "weight.csv"
    basis_file = full_work_dir / "input/basis.txt"

    if mode == "new":
        basis = data.get("basis", DEFAULT_BASIS)
    elif basis_file.exists():
        saved_basis = basis_file.read_text().strip().lower()
        basis = saved_basis if saved_basis in SUPPORTED_BASIS else DEFAULT_BASIS
    else:
        basis = DEFAULT_BASIS
    data["basis"] = basis

    if mode == "spe":
        return _submit_spe(data, full_work_dir, work_name, username, recipient, basis)
    if mode == "refine":
        return _submit_refine(data, full_work_dir, work_name, username, recipient)

    if mode == "new":
        upload_dir = full_work_dir / "upload"
        init_weight_file = upload_dir / "init_weight.csv"
        if not upload_dir.is_dir() or not init_weight_file.is_file():
            return _error("Upload init_weight.csv before submitting the work")
        init_weight_text = init_weight_file.read_text()
        if not init_weight_text.strip():
            return _error("init_weight.csv is empty")
        dataset_name = init_weight_text.splitlines()[-1].split(",", 1)[0].strip()
        if not valid_path_component(dataset_name):
            return _error("init_weight.csv contains an invalid dataset name")
        upload_archive = _find_named_archive(upload_dir, dataset_name)
        if upload_archive is None:
            return _error("Dataset archive not found")
        if _find_user_ref(upload_dir) is None:
            return _error("Reference energy file not found")

        input_dir = full_work_dir / "input"
        try:
            _copy_upload_files(upload_dir, input_dir)
        except ValueError as exc:
            return _error(str(exc))
        basis_file.write_text(basis + "\n")
        weight_path.parent.mkdir(parents=True, exist_ok=True)
        with open(weight_path, "w") as f:
            reads = init_weight_text.replace(",", "\t")
            f.write(reads)
            if reads[-1] != "\n":
                f.write("\n")
            with open(RESOURCES / "default_weights.csv", "r") as ref_f:
                ref_f.readline()
                f.write(ref_f.read())

    info_file = full_work_dir / "process.log"
    with open(info_file, "a+") as ref_f:
        ref_f.write("Work Submit Log\n")
        for k, v in data.items():
            ref_f.write(f"load [{k}] as {v}\n")

        new_output = weight_path.parent
        new_output.mkdir(parents=True, exist_ok=True)

        # A double click, retry, or two browser tabs must never launch two
        # expensive workers against the same Run directory. The old behavior
        # allowed duplicate main.py processes and made both the UI and queue
        # appear frozen.
        if mode in ("new", "optim") and (_task_processes(new_output) or _queued_task(new_output)):
            return _error("This calculation is already queued or running. Refresh the Job to follow it.", 409)

        if mode == "optim":
            base_output = full_work_dir / "output/weight_0"
            required_inputs = [base_output / "INPUT", base_output / "INPUT_ref", weight_path]
            if not all(path.is_file() for path in required_inputs):
                return _error("Optimization inputs are incomplete")
            for fname in ("INPUT", "INPUT_ref"):
                src = base_output / fname
                dst = new_output / fname
                shutil.copy2(src, dst)
            for fname in ("TEST_INPUT", "TEST_INPUT_ref", "TestDescriptors.json"):
                src = base_output / fname
                if src.is_file():
                    shutil.copy2(src, new_output / fname)

            command = [
                PIPELINE_PYTHON,
                str(PROGRAM_DIR / "opt_demo.py"),
                "--fit",
                str(new_output / "INPUT"),
                "--ref",
                str(new_output / "INPUT_ref"),
                "--weights-csv",
                str(weight_path),
                "--output",
                str(new_output),
            ]


        else:
            input_dir = full_work_dir / "input"
            init_weight_file = input_dir / "init_weight.csv"
            if not init_weight_file.is_file():
                return _error("init_weight.csv not found")
            init_weight_lines = init_weight_file.read_text().splitlines()
            if not init_weight_lines:
                return _error("init_weight.csv is empty")
            gfile = init_weight_lines[-1].split(",", 1)[0].strip()
            if not valid_path_component(gfile):
                return _error("init_weight.csv contains an invalid dataset name")
            archive = _find_named_archive(input_dir, gfile)
            if archive is None:
                return _error("Dataset archive not found")

            command = [
                PIPELINE_PYTHON,
                str(PROGRAM_DIR / "main.py"),
                "--input",
                str(archive),
                "--output",
                str(new_output),
                "--weight",
                str(weight_path),
                "--basis",
                basis,
            ]

        print(shlex.join(command))
        out_log = new_output / "process.log"
        out_log.parent.mkdir(parents=True, exist_ok=True)
        with open(out_log, "a") as qf:
            qf.write("QUEUED\n")

        job = {
            "cmd": command,
            "out_log": str(out_log),
            "user": username,
            "mode": mode,
            "work_name": work_name,
            "weight_name": weightFile,
            "work_dir": work_dir,
            "info_dir": f"{work_dir}/output/{weightFile}",
            "email": recipient,
            "output_dir": str(new_output),
        }
        _task_queue.put(job)
        ref_f.write(f"Run Queued (queue size {_task_queue.qsize()})\n")

    count_dir = Path(DATA_DIR) / "submit_count.txt"
    try:
        c = int(count_dir.read_text().strip()) + 1
    except (FileNotFoundError, ValueError):
        c = 1
    count_dir.write_text(str(c))
    _send_submission_email(job)
    return {"result": "work submit success", "task_count": c}


def _validated_run_request(data):
    username = g.current_user["username"]
    work_dir = data["work_dir"]
    parts = Path(work_dir).parts if isinstance(work_dir, str) else ()
    if len(parts) != 3 or parts[:2] != ("Work", username) or not valid_path_component(parts[2]):
        return None, None, _error("work_dir must be Work/<authenticated user>/<work id>")
    if not valid_path_component(data["weightFile"]):
        return None, None, _error("weightFile must be a single valid path component")
    fork = data.get("fork")
    if fork and not re.fullmatch(r"fork-[1-9]\d*", fork):
        return None, None, _error("fork must be fork-N")
    output = _run_output(data, parts[2], username)
    if not output.is_dir():
        return None, None, _error("Run output not found", 404)
    return output, username, None


def _analysis_read_files(folder, names=None):
    """Return text files from an already validated Run/input directory."""
    result = {"_files": []}
    try:
        entries = list(folder.iterdir()) if folder.is_dir() else []
    except OSError:
        entries = []
    for entry in entries:
        if entry.is_file() and not entry.is_symlink():
            result["_files"].append(entry.name)
    result["_files"].sort()
    wanted = names or ()
    for name in wanted:
        path = folder / name
        if not path.is_file() or path.is_symlink():
            continue
        try:
            if name == "process.log":
                with path.open("rb") as stream:
                    stream.seek(0, os.SEEK_END)
                    size = stream.tell()
                    stream.seek(max(0, size - 256 * 1024), os.SEEK_SET)
                    result[name] = stream.read().decode(errors="replace")
            else:
                result[name] = path.read_text(errors="replace")
        except OSError:
            result[name] = ""
    return result


def _analysis_signature(folder):
    """Fingerprint only files Analyze reads, avoiding recursive work trees."""
    folder = Path(folder)
    values = []
    def add(path):
        try:
            stat = path.stat()
            values.append((str(path.relative_to(folder)), stat.st_mtime_ns, stat.st_size))
        except OSError:
            pass
    for name in ("basis.txt", "test_set/manifest.json"):
        add(folder / "input" / name)
    output = folder / "output"
    for run_id, run_dir in _analysis_run_dirs(output):
        add(run_dir)
        for name in _ANALYSIS_FILE_NAMES:
            add(run_dir / name)
        add(run_dir / "input" / "basis.txt")
    return tuple(values)


def _analysis_timestamp(path):
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(path.stat().st_mtime))
    except OSError:
        return ""


def _analysis_input_mue(text):
    if not text:
        return None
    for line in text.splitlines():
        cells = re.split(r"\t+|\s{2,}", line.strip())
        if len(cells) >= 2 and cells[0].strip().lower() == "input":
            try:
                value = float(cells[1].strip())
                return value if value >= 0 else None
            except (TypeError, ValueError):
                continue
    return None


def _analysis_run_status(files):
    if str(files.get("Mue", "")).strip():
        return "completed"
    log = str(files.get("process.log", ""))
    if "[Error]" in log or "Traceback" in log or "ERROR" in log:
        return "failed"
    if "QUEUED" in log or "running" in log.lower() or "starts running" in log.lower():
        return "running"
    return "unknown"


def _analysis_run_dirs(output):
    if not output.is_dir():
        return []
    result = []
    try:
        weights = sorted(
            (entry for entry in output.iterdir() if entry.is_dir() and re.fullmatch(r"weight_[0-9]+", entry.name)),
            key=lambda entry: int(entry.name.split("_", 1)[1]),
        )
    except (OSError, ValueError):
        weights = []
    for weight in weights:
        result.append((weight.name, weight))
        try:
            forks = sorted(
                (entry for entry in weight.iterdir() if entry.is_dir() and re.fullmatch(r"fork-[1-9][0-9]*", entry.name)),
                key=lambda entry: int(entry.name.split("-", 1)[1]),
            )
        except (OSError, ValueError):
            forks = []
        result.extend((f"{weight.name}/{fork.name}", fork) for fork in forks)
    return result


def _analysis_job_payload(username, job_id, job_dir):
    input_dir = job_dir / "input"
    input_files = _analysis_read_files(input_dir, ("basis.txt",))
    listed, files = [], {}
    for run_id, output in _analysis_run_dirs(job_dir / "output"):
        run_files = _analysis_read_files(output, _ANALYSIS_FILE_NAMES)
        if "/" in run_id and (output / "input").is_dir():
            run_files["_input"] = _analysis_read_files(output / "input", ("basis.txt",))
        listed.append({
            "id": run_id,
            "date": _analysis_timestamp(output),
            "status": _analysis_run_status(run_files),
            "rawStatus": _analysis_run_status(run_files),
            "mue": _analysis_input_mue(run_files.get("Mue", "")),
        })
        # Status is derived above; process.log is intentionally omitted from
        # the browser snapshot because it can be megabytes while Analyze only
        # needs the terminal state.
        run_files.pop("process.log", None)
        files[run_id] = run_files
    return {"id": job_id, "runs": listed, "files": files, "input": input_files}


def _analysis_cached_job(username, job_id):
    job_dir = resolve_owned_path(f"Work/{username}/{job_id}", username, minimum_user_depth=1)
    if not job_dir.is_dir():
        return None
    key = (username, job_id)
    signature = _analysis_signature(job_dir)
    now = time.monotonic()
    cached = _ANALYSIS_CACHE.get(key)
    if cached and cached[0] >= now and cached[1] == signature:
        return cached[2]
    payload = _analysis_job_payload(username, job_id, job_dir)
    _ANALYSIS_CACHE[key] = (now + _ANALYSIS_CACHE_TTL, signature, payload)
    # Keep a bounded cache when users create many short-lived Jobs.
    if len(_ANALYSIS_CACHE) > 256:
        for old_key, old_value in sorted(_ANALYSIS_CACHE.items(), key=lambda item: item[1][0])[:64]:
            _ANALYSIS_CACHE.pop(old_key, None)
    return payload


def _analysis_cached_summary(username, job_id):
    """Read only the files needed for the Job picker and cache that summary."""
    job_dir = resolve_owned_path(f"Work/{username}/{job_id}", username, minimum_user_depth=1)
    if not job_dir.is_dir():
        return None
    key = (username, job_id)
    signature = _analysis_signature(job_dir)
    now = time.monotonic()
    cached = _ANALYSIS_SUMMARY_CACHE.get(key)
    if cached and cached[0] >= now and cached[1] == signature:
        return cached[2]
    full = _ANALYSIS_CACHE.get(key)
    if full and full[0] >= now and full[1] == signature:
        payload = {"id": job_id, "runs": full[2]["runs"]}
    else:
        listed = []
        for run_id, output in _analysis_run_dirs(job_dir / "output"):
            run_files = _analysis_read_files(output, ("Mue", "process.log"))
            listed.append({
                "id": run_id,
                "date": _analysis_timestamp(output),
                "status": _analysis_run_status(run_files),
                "rawStatus": _analysis_run_status(run_files),
                "mue": _analysis_input_mue(run_files.get("Mue", "")),
            })
        payload = {"id": job_id, "runs": listed}
    _ANALYSIS_SUMMARY_CACHE[key] = (now + _ANALYSIS_CACHE_TTL, signature, payload)
    if len(_ANALYSIS_SUMMARY_CACHE) > 256:
        for old_key, old_value in sorted(_ANALYSIS_SUMMARY_CACHE.items(), key=lambda item: item[1][0])[:64]:
            _ANALYSIS_SUMMARY_CACHE.pop(old_key, None)
    return payload


def _analysis_summary(username, job_id, payload=None):
    if payload is None:
        payload = _analysis_cached_job(username, job_id)
    if payload is None:
        return None
    completed = [run for run in payload["runs"] if run.get("status") == "completed"]
    values = [run["mue"] for run in completed if isinstance(run.get("mue"), (int, float))]
    job_dir = Path(DATA_DIR) / "Work" / username / job_id
    return {
        "id": job_id,
        "runs": len(payload["runs"]),
        "completed": len(completed),
        "bestInput": min(values) if values else None,
        "updated": _analysis_timestamp(job_dir),
    }


@app.get("/analysis")
@app.get("/analysis/summary")
@app.doc(summary="Read cached Analyze data", description="Return a compact, cached snapshot of the authenticated user's Jobs and Runs for MUE analysis. Use summary=1 for lightweight Job summaries.", security=[{"bearerAuth": []}])
@login_required
def analysis_data():
    username = g.current_user["username"]
    user_root = resolve_owned_path(f"Work/{username}", username)
    if not user_root.is_dir():
        return {"version": 1, "jobs": [], "summaries": []}
    requested = [value.strip() for value in request.args.get("jobs", "").split(",") if value.strip()]
    if requested:
        if any(not valid_path_component(value) for value in requested):
            return _error("jobs must contain valid Job IDs")
        job_ids = list(dict.fromkeys(requested))
    else:
        try:
            job_ids = sorted((entry.name for entry in user_root.iterdir() if entry.is_dir() and valid_path_component(entry.name)))
        except OSError:
            job_ids = []
    summary_only = request.path.endswith("/summary") or request.args.get("summary", "").lower() in {"1", "true", "yes"}
    jobs, summaries = [], []
    for job_id in job_ids:
        payload = _analysis_cached_summary(username, job_id) if summary_only else _analysis_cached_job(username, job_id)
        if payload is None:
            continue
        summaries.append(_analysis_summary(username, job_id, payload))
        if not summary_only:
            jobs.append(payload)
    return {"version": 1, "cached": True, "jobs": jobs, "summaries": summaries}


@app.post("/cancel")
@app.doc(summary="Cancel a calculation", description="Request cancellation of a queued or running calculation owned by the authenticated user.", security=[{"bearerAuth": []}])
@login_required
@app.input(CANCEL_IN)
def cancel_task(json_data):
    output, _username, error = _validated_run_request(json_data)
    if error:
        return error
    scope = json_data.get("spe_scope")
    if not _task_processes(output, scope) and not _queued_task(output, scope):
        return _error("No queued or running calculation was found", 409)
    _mark_cancelled(output, scope)
    stopped = _stop_task_processes(output, scope)
    return {"result": "cancel requested", "stopped": stopped, "scope": scope}


@app.delete("/delete_run/<path:run_path>")
@app.doc(summary="Delete a Run", description="Delete a completed or stopped Run owned by the authenticated user.", security=[{"bearerAuth": []}])
@login_required
def delete_run(run_path):
    username = g.current_user["username"]
    parts = Path(run_path).parts
    if len(parts) not in (5, 6) or parts[:2] != ("Work", username) or parts[3] != "output":
        return _error("run_path must be Work/<authenticated user>/<job>/output/<weight>[/fork]")
    if not valid_path_component(parts[2]) or not valid_path_component(parts[4]):
        return _error("Invalid run path")
    if len(parts) == 6 and not re.fullmatch(r"fork-[1-9]\d*", parts[5]):
        return _error("Invalid fork path")
    output = resolve_owned_path(run_path, username, minimum_user_depth=3)
    if not output.is_dir():
        return _error("Run output not found", 404)
    if len(parts) == 5 and any(child.is_dir() and re.fullmatch(r"fork-[1-9]\d*", child.name) for child in output.iterdir()):
        return _error("Delete fork runs before deleting the parent weight run", 409)
    _discard_pending_tasks(output, recursive=True)
    _mark_cancelled(output)
    _stop_task_processes(output)
    if _task_processes(output):
        return _error("The run is still stopping. Try again in a moment.", 409)
    shutil.rmtree(output)
    return {"result": "run delete success"}

# 然后用appx实现蓝图
appx = APIFlask(__name__, title="DFThub API", version="2.0.0",
                openapi_blueprint_url_prefix='/api_dft')
appx.config["DFTHUB_TASK_ACTIVITY"] = lambda: _task_queue.activity()
appx.config.update({
    "SERVERS": [{"url": "/", "description": "This DFThub server"}],
    "SECURITY_SCHEMES": {"bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}},
    "SWAGGER_UI_CSS": "/vendor/swagger/swagger-ui.css",
    "SWAGGER_UI_BUNDLE_JS": "/vendor/swagger/swagger-ui-bundle.js",
    "SWAGGER_UI_STANDALONE_PRESET_JS": "/vendor/swagger/swagger-ui-standalone-preset.js",
})

@appx.after_request
def _security_headers(response):
    if os.environ.get("DFTHUB_ENABLE_HSTS") == "1":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
    response.headers.setdefault("Content-Security-Policy-Report-Only", "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data: blob:; connect-src 'self'")
    return response

@appx.after_request
def _docs_mobile_meta(response):
    if request.path == "/api_dft/docs" and response.mimetype == "text/html":
        body = response.get_data(as_text=True)
        if 'name="viewport"' not in body:
            body = body.replace('<meta charset="UTF-8">', '<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">', 1)
            response.set_data(body)
    return response

appx.register_blueprint(app,url_prefix='/api_dft')
appx.register_blueprint(file_api_app,url_prefix='/api_dft')
appx.register_blueprint(auth_app,url_prefix='/api_dft')

appx.config.from_object(DefaltMailConfig)
appx.config.update({
    "SERVERS": [{"url": "/", "description": "This DFThub server"}],
    "SECURITY_SCHEMES": {"bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}},
    "SWAGGER_UI_CSS": "/vendor/swagger/swagger-ui.css",
    "SWAGGER_UI_BUNDLE_JS": "/vendor/swagger/swagger-ui-bundle.js",
    "SWAGGER_UI_STANDALONE_PRESET_JS": "/vendor/swagger/swagger-ui-standalone-preset.js",
})
mail.init_app(appx)
appx.config.update(DOCS_FAVICON="/favicon.svg", SWAGGER_UI_CONFIG={"validatorUrl": None})

if __name__ == "__main__":
    run_simple(
        hostname="0.0.0.0",
        port=2012,
        application=appx,
        use_debugger=True,
        use_reloader=True,
    )
