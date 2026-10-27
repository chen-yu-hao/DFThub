
# python
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

# modules
from apiflask import APIBlueprint, APIFlask, Schema, abort
from apiflask.validators import OneOf

# from Flask import jsonify, input
from apiflask.fields import String, List, File

from flask import current_app, g, has_app_context, send_file
from werkzeug import run_simple
from werkzeug.utils import secure_filename

from dfthub.api.auth import authenticate_request, login_required
from dfthub.api.config import DATA_DIR

app = APIBlueprint("File",__name__)

def _safe_path(*user_parts):
    """Resolve a user-supplied path under DATA_DIR, rejecting path traversal.

    Joins the requested parts onto DATA_DIR, fully resolves the result, and
    aborts with 400 if it escapes DATA_DIR (e.g. via ``..`` or absolute paths).
    """
    path_parts = [str(part) for part in user_parts]
    if any(
        not character.isprintable()
        for path_part in path_parts
        for character in path_part
    ):
        abort(400, message="Invalid path")
    try:
        base = Path(DATA_DIR).resolve()
        target = base.joinpath(*path_parts).resolve()
    except (OSError, RuntimeError, ValueError):
        abort(400, message="Invalid path")
    if not target.is_relative_to(base):
        abort(400, message="Invalid path")
    return target


def valid_path_component(value):
    if not isinstance(value, str) or len(value) > 128 or not value.strip():
        return False
    if value in (".", "..") or "/" in value or "\\" in value:
        return False
    return all(character.isprintable() for character in value)


def resolve_owned_path(user_path, username, minimum_user_depth=0):
    if not isinstance(user_path, str) or "\\" in user_path:
        abort(400, message="Invalid path")
    lexical_path = Path(user_path)
    parts = lexical_path.parts
    if lexical_path.is_absolute() or ".." in parts:
        abort(400, message="Invalid path")
    if len(parts) < 2 or parts[0] != "Work" or parts[1] != username:
        abort(403, message="Path does not belong to the authenticated user")
    user_parts = parts[2:]
    if len(user_parts) < minimum_user_depth or not all(
        valid_path_component(part) for part in user_parts
    ):
        abort(400, message="Invalid path")

    target = _safe_path(user_path)
    user_root = (Path(DATA_DIR) / "Work" / username).resolve()
    if not target.is_relative_to(user_root):
        abort(403, message="Path does not belong to the authenticated user")
    return target


def _validate_upload_target(folder_dir, username):
    target = resolve_owned_path(folder_dir, username, minimum_user_depth=2)
    relative_parts = target.relative_to(
        (Path(DATA_DIR) / "Work" / username).resolve()
    ).parts
    is_input_upload = len(relative_parts) == 2 and relative_parts[1] == "upload"
    is_weight_upload = (
        len(relative_parts) == 3
        and relative_parts[1] == "output"
        and valid_path_component(relative_parts[2])
    )
    is_energy_upload = (
        len(relative_parts) in (5, 6)
        and relative_parts[1] == "output"
        and valid_path_component(relative_parts[2])
        and (relative_parts[3] == "energy_input" or (
            len(relative_parts) == 6
            and re.fullmatch(r"fork-[1-9]\d*", relative_parts[3])
            and relative_parts[4] == "energy_input"
        ))
        and valid_path_component(relative_parts[-1])
    )
    if not (is_input_upload or is_weight_upload or is_energy_upload):
        abort(400, message="Uploads must target a work upload, weight output or energy input folder")
    return target, "energy" if is_energy_upload else "weight" if is_weight_upload else "input"


def _live_task_activity():
    from dfthub.processes import tasks
    return {(p['output'], p['scope']): {'status': 'Running', 'mode': p['mode']}
            for p in tasks()}


def _task_activity():
    provider = current_app.config.get("DFTHUB_TASK_ACTIVITY") if has_app_context() else None
    activity = provider() if provider else {}
    activity.update(_live_task_activity())
    return activity


def _log_tail(path):
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            stream.seek(max(0, stream.tell() - 256 * 1024))
            return stream.read().decode(errors="replace")
    except OSError:
        return ""


def _run_folders(folder):
    if (folder / "output").is_dir():
        weights = [p for p in (folder / "output").glob("weight_*") if p.is_dir()]
        return weights + [fork for weight in weights for fork in weight.glob("fork-*") if fork.is_dir()]
    return [folder] if folder.is_dir() else []


def _folder_activity(folder, activity):
    roots = {p.resolve() for p in _run_folders(folder)}
    return {key: state for key, state in activity.items()
            if Path(key[0]) in roots or any(Path(key[0]).is_relative_to(root / "energy_input") for root in roots)}


def _activity_label(output, scope, state):
    if scope == "optimization":
        if state["status"] == "Queued":
            return "Optimization queued"
        stage = _derive_stage(_log_tail(Path(output) / "process.log"))
        if stage not in (None, "Queued", "Success", "Failed", "Interrupted"):
            return stage
        return "Optimizing parameters" if state.get("mode") in ("optim", "refine") else "Running"
    title = {"input": "SCF Input", "ame418": "SCF AME418", "energy": "DFT energy", "overlap": "Wavefunction overlap"}.get(scope, scope)
    return f"{title} {state['status'].lower()}"


def _display_activity(folder, activity):
    active = _folder_activity(folder, activity)
    if not active:
        return {}
    state = "running" if any(item["status"] == "Running" for item in active.values()) else "queued"
    labels = list(dict.fromkeys(_activity_label(output, scope, item) for (output, scope), item in active.items()))
    return {"activity_state": state, "activity_status": " · ".join(labels)}


def _derive_stage(blob):
    """Determine the computation stage from the LATEST run in the log.

    The log may contain multiple runs (each starting with QUEUED). We isolate
    the last run's content and find its most advanced stage marker.

    Stages (in order of progress):
      Queued -> Submitted -> File Prepared -> Initial Density Calc...
      -> Descriptor Calc... -> Optimizing... -> Outputting Results -> Success
    For SPE runs: Queued -> SPE Running (N/736) -> Success
    """
    import re

    # Isolate the last run: split by QUEUED and take the last segment
    parts = re.split(r"(?:^|\n)QUEUED\b", blob)
    latest = parts[-1] if parts else blob

    terminal = list(re.finditer(r"SUCCESS!|\[Error\]|\[Interrupted\]", latest))
    if terminal:
        return {"SUCCESS!": "Success", "[Error]": "Failed", "[Interrupted]": "Interrupted"}[terminal[-1].group()]

    # Stage markers: checked in order from most advanced to least
    _STAGE_MARKERS = [
        ("SUCCESS!",                           "Success"),
        ("[Error]",                             "Failed"),
        ("Parameters optimization finished",   "Outputting Results"),
        ("Optimizing parameters",              "Optimizing..."),
        ("Descriptor calculations finished",   "Descriptor Calc Done"),
        ("successfully calculated Rhos",       "Descriptor Calc..."),
        ("Initial density calculation",        "Initial Density Calc..."),
        ("File decompression completed",       "File Prepared"),
        ("The program starts running",         "Submitted"),
        ("AME418 SRP single-point energy",     "SPE Running"),
    ]

    # Check progress markers like [N/M] for density/descriptor/SPE progress
    progress_match = None
    for line in reversed(latest.splitlines()):
        m = re.match(r"\s*\[\s*(\d+)/(\d+)\]", line.strip())
        if m:
            progress_match = f"({m.group(1)}/{m.group(2)})"
            break

    for marker, label in _STAGE_MARKERS:
        if marker in latest:
            if label in ("Initial Density Calc...", "Descriptor Calc...", "SPE Running") and progress_match:
                return f"{label} {progress_match}"
            return label

    if "QUEUED" in blob or "Run Queued" in blob:
        return "Queued"
    return None


def _derive_status(folder, activity=None):
    """Optimization completion stays separate from optional SCF activity."""
    if activity is None:
        activity = _task_activity()
    active = {key: state for key, state in _folder_activity(folder, activity).items() if key[1] == "optimization"}
    if active:
        (output, scope), state = max(active.items(), key=lambda item: item[1]["status"] == "Running")
        return _activity_label(output, scope, state)
    roots = _run_folders(folder)
    logs = [root / "process.log" for root in roots if (root / "process.log").is_file()]
    if not logs and (folder / "process.log").is_file():
        logs = [folder / "process.log"]
    states = []
    for log in logs:
        stage = _derive_stage(_log_tail(log))
        if (log.parent / ".cancel_requested").exists():
            stage = "Interrupted"
        states.append(stage if stage in ("Success", "Failed", "Interrupted") else "Interrupted")
    for terminal in ("Failed", "Interrupted", "Success"):
        if terminal in states:
            return terminal
    return "Success" if any((root / "Mue").is_file() for root in roots) else "No Process"


# @app.route("/")
# def api_index():
#     req = "See <a href='docs'>DOCS</a>"
#     return req

class PUT_FILES(Schema):
    folder_dir = String(required=True)
    files = List(File(), required=True)

# @app.post("/upload")
@app.post("/upload")
@app.put("/upload")
@app.doc(summary="Upload input files", description="Upload a dataset archive, reference file and initial weights into the authenticated user's upload folder.", security=[{"bearerAuth": []}])
@login_required
@app.input(PUT_FILES, location="form_and_files")
def file_upload(form_and_files_data):
    data = form_and_files_data
    folder_dir, upload_kind = _validate_upload_target(
        data["folder_dir"], g.current_user["username"]
    )
    files = []
    for file in data["files"]:
        filename = secure_filename(file.filename)
        if not filename:
            abort(400, message="Invalid filename")
        if upload_kind == "weight" and filename != "weight.csv":
            abort(400, message="Only weight.csv may be uploaded to a weight folder")
        if upload_kind == "energy" and not filename.lower().endswith((".tgz", ".tar.gz", ".zip")):
            abort(400, message="Energy input must be a .tgz, .tar.gz or .zip archive")
        files.append((file, filename))
    folder_dir.mkdir(parents=True, exist_ok=True)
    for file, filename in files:
        file.save(folder_dir / filename)
    return {"result": "file upload success"}

#!删除文件
@app.delete("/delete/<path:file_folder_dir>")
@app.doc(summary="Delete a file or folder", description="Delete a file or folder inside the authenticated user's Work directory.", security=[{"bearerAuth": []}])
@login_required
def file_delete(file_folder_dir):
    file_folder_dir = resolve_owned_path(
        file_folder_dir, g.current_user["username"], minimum_user_depth=1
    )
    if any(Path(output).is_relative_to(file_folder_dir) or file_folder_dir.is_relative_to(Path(output))
           for output, _scope in _task_activity()):
        abort(409, message="This job has a queued or running calculation. Stop it or wait for it to finish before deleting.")
    if file_folder_dir.is_dir():
        shutil.rmtree(file_folder_dir)
    elif file_folder_dir.exists():
        file_folder_dir.unlink()
    else:
        abort(404, message="File or folder not found")
    return {"result": "file delete success"}

class FILE_LIST(Schema):
    # NOTE: 之前跑不通是这里接口写反了
    file_dir = String(required=True)
    file_filter = String(required=True, dump_default="*")
    file_or_folder = String(
        required=True, dump_default="all", validate=OneOf(["all", "file", "folder"])
    )


@app.post("/file_list")
@app.doc(summary="List files or folders", description="List files or folders inside the authenticated user's Work directory.", security=[{"bearerAuth": []}])
@login_required
@app.input(FILE_LIST)
def get_file_list(json_data):
    data = json_data
    p = resolve_owned_path(data["file_dir"], g.current_user["username"])
    file_filter = data["file_filter"]
    if (
        len(file_filter) > 128
        or "/" in file_filter
        or "\\" in file_filter
        or ".." in file_filter
        or not all(character.isprintable() for character in file_filter)
    ):
        abort(400, message="Invalid file filter")
    file_iter = p.glob(file_filter)
    base = (Path(DATA_DIR) / "Work" / g.current_user["username"]).resolve()
    activity = _task_activity() if data["file_or_folder"] != "file" else {}
    result = []
    for f in file_iter:
        # guard against a `..` in file_filter letting glob escape DATA_DIR
        if not f.resolve().is_relative_to(base):
            continue
        if data["file_or_folder"] == "file" and not f.is_file():
            continue
        elif data["file_or_folder"] == "folder" and not f.is_dir():
            continue
        else:
            r = {}
            r["path"] = Path(data["file_dir"]).as_posix()
            r["name"] = f.name
            r["is_type"] = "file" if f.is_file() else "folder"
            r["file_suffix"] = f.suffix
            r["file_size"] = f.stat().st_size
            r["time_active"] = f.stat().st_atime
            r["time_modify"] = f.stat().st_mtime
            display_order = f.joinpath(".display_order")
            if display_order.exists():
                try:
                    r["_display_order"] = int(display_order.read_text().strip())
                except ValueError:
                    r["_display_order"] = 0
            r["status"] = _derive_status(f, activity)
            r.update(_display_activity(f, activity))
            mue=f.joinpath('Mue')
            if mue.exists():
                with open(mue,'r') as ft:
                    r["total_mue"]=ft.readlines()[-1]
            else:
                r["total_mue"] = "No Mue"
            result += [r]
    if any("_display_order" in item for item in result):
        # The frontend reverses the returned list before rendering, so return
        # descending order here to make rows display as 1, 2, 3, ...
        result.sort(key=lambda item: item.get("_display_order", 0), reverse=True)
    return {"input": data, "result": result}

# 下载文件或者目录
@app.get("/download/<path:filepath>")
@app.doc(summary="Download a file or template", description="Download the public template/count files, or a private file owned by the authenticated user. The template and submit count are public; all other paths require Bearer authentication.")
def download_files(filepath=""):
    path = _safe_path(filepath)
    submit_count = (Path(DATA_DIR) / "submit_count.txt").resolve()
    template_root = (Path(DATA_DIR) / "Work" / "template").resolve()
    is_public = path == submit_count or path == template_root or path.is_relative_to(template_root)
    if not is_public:
        auth_error = authenticate_request()
        if auth_error:
            return auth_error
        path = resolve_owned_path(filepath, g.current_user["username"])

    if path.is_file():
        return send_file(path, as_attachment=False)
    if path.is_dir():
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w:gz") as archive:
            archive.add(path, arcname=path.name)
        data.seek(0)
        d_name = secure_filename(path.name) + ".tgz"
        return send_file(data, download_name=d_name, as_attachment=True)
    abort(404, message="File or folder not found")


appx = APIFlask(__name__,title="Flask API")
appx.register_blueprint(app)

if __name__ == "__main__":
    # app.run(host="0.0.0.0", port=2003)
    run_simple(
        hostname="0.0.0.0",
        port=2002,
        application=appx,
        threaded=True,
        use_debugger=True,
        use_reloader=True,
    )
