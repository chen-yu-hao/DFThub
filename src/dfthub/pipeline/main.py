"""DFThub computation pipeline (pyscf + CF25D edition).

Invoked by the web backend as:
    python main.py --input <job>/input/<dataset>.tgz --output <job>/output/<weightFile> --weight <...>/weight.csv

Steps:
  1. Uncompress the uploaded .tgz/.zip of .xyz geometries.
  2. DFT-D3 dispersion (zero damping, rs6=1.53) for every structure via dft_run.sh.
  3. Initial SCF with pyscf, xc = "CF22D,CF22D", using the selected basis and grids.level = 6,
     checkpoint saved as <name>.pychk.
  4. Descriptor calculation for every molecule with the CF25D library (xclib).
  5. Write descriptors / ref / inverse weight in the TMB11 optimizer format into a
     fresh demo folder (the TMB11 example itself is never modified) and run the
     parameter optimization.
  6. Copy the optimized parameters back to the job output directory.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path

from dfthub.pipeline.compute_scheduler import TASK_THREADS, enter_task, molecular_pool, molecule_environment, thread_environment, basis_size, threads_for_basis

os.environ.update(thread_environment(int(os.environ.get('DFTHUB_MOLECULE_THREADS', '1'))))

from dfthub.paths import pipeline_python
PIPELINE_PYTHON = pipeline_python()

if __name__ == "__main__" and PIPELINE_PYTHON and os.path.realpath(sys.executable) != os.path.realpath(PIPELINE_PYTHON):
    os.execv(PIPELINE_PYTHON, [PIPELINE_PYTHON] + sys.argv)

import numpy as np  # noqa: E402

from dfthub.pipeline.basis_presets import (  # noqa: E402
    BASIS_PRESETS,
    DEFAULT_BASIS,
    SUPPORTED_BASIS,
    elements_from_atom_block,
    load_basis_preset,
)

PROGRAM_DIR = Path(__file__).resolve().parent
COMMON_DIR = PROGRAM_DIR.parent

# Overridable for smoke tests; production values are the defaults.
BASIS_PRESET = os.environ.get("DFTHUB_BASIS", DEFAULT_BASIS)
BASIS, ECP = BASIS_PRESETS.get(BASIS_PRESET, BASIS_PRESETS[DEFAULT_BASIS])
GRID_LEVEL = int(os.environ.get("DFTHUB_GRID", "6"))
MAX_MEMORY_MB = int(os.environ.get("DFTHUB_MAXMEM", "8000"))
NUM_THREADS = int(os.environ.get("DFTHUB_MOLECULE_THREADS", "4"))


def log(msg):
    # The worker redirects stdout to this same file; flush it before appending.
    sys.stdout.flush()
    with open(LOG_FILE, "a") as f:
        f.write(msg.rstrip() + "\n")


def archive_name(input_file):
    name = os.path.basename(input_file)
    for suffix in (".tar.gz", ".tgz", ".zip"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return os.path.splitext(name)[0]


def uncompress(input_file, output_dir):
    if not os.path.isfile(input_file):
        raise FileNotFoundError(f'Input file "{input_file}" not found.')
    os.makedirs(output_dir, exist_ok=True)
    from dfthub.archives import extract_geometry_archive
    extract_geometry_archive(input_file, output_dir)


def parse_xyz(path):
    """Read an xyz file whose comment line carries 'charge multiplicity'."""
    with open(path) as f:
        lines = f.read().strip().splitlines()
    natom = int(lines[0].split()[0])
    charge, mult = 0, 1
    fields = lines[1].split()
    if len(fields) >= 2:
        try:
            charge, mult = int(fields[0]), int(fields[1])
        except ValueError:
            pass
    atom_block = "\n".join(lines[2 : 2 + natom])
    return charge, mult, atom_block


def preflight_basis(xyz_files, preset=None):
    """Validate every element used by the dataset before D3 or SCF starts."""
    preset = preset or BASIS_PRESET
    checked = set()
    for xyz in xyz_files:
        _, _, atom_block = parse_xyz(xyz)
        elements = set(elements_from_atom_block(atom_block))
        unseen = sorted(elements - checked)
        if not unseen:
            continue
        probe = "\n".join(f"{element} 0 0 0" for element in unseen)
        try:
            load_basis_preset(probe, preset)
        except Exception as exc:
            raise ValueError(f"{xyz.name}: {exc}") from exc
        checked.update(unseen)


def run_dftd3(xyz_dir):
    """Step 2: dispersion energies (Eh) for every .xyz via the dftd3 Python API.

    Zero damping with s6=1.0, s8=0.0, rs6=1.53, s9=0 (no ATM) — identical to
    `s-dftd3 run --zero-param 1.0 0.0 1.53` and the CF22D dispersion term.
    """
    from pyscf.data.elements import charge as element_charge
    from dftd3.interface import DispersionModel, ZeroDampingParam

    ANGSTROM_TO_BOHR = 1.0 / 0.52917721067
    d3_dir = xyz_dir / "dftd3"
    d3_dir.mkdir(parents=True, exist_ok=True)
    edisp = {}
    for xyz in sorted(xyz_dir.glob("*.xyz")):
        _, _, atom_block = parse_xyz(xyz)
        syms, coords = [], []
        for line in atom_block.splitlines():
            fields = line.split()
            syms.append(fields[0])
            coords.append([float(v) for v in fields[1:4]])
        numbers = np.array([element_charge(s) for s in syms])
        positions = np.array(coords) * ANGSTROM_TO_BOHR
        model = DispersionModel(numbers, positions)
        res = model.get_dispersion(ZeroDampingParam(s6=1.0, s8=0.0, rs6=1.53, s9=0.0), grad=False)
        energy = float(res.get("energy"))
        edisp[xyz.stem] = energy
        (d3_dir / f"{xyz.stem}.out").write_text(f"Dispersion energy: {energy:.13E} Eh\n")
    return edisp


def compute_molecule(xyz_path, work_dir):
    """Steps 3+4: SCF (chk saved) + CF25D descriptors. Returns the 78 raw values."""
    from pyscf import gto, dft, lib
    from xclib.CFXXD import CF22D_nxc, CF22D_nxc_rks
    from xclib.pyscf_io import save_mf_uks

    lib.num_threads(NUM_THREADS)
    name = xyz_path.stem
    cache = work_dir / f"{name}.desc.npy"
    if cache.exists():
        return np.load(cache)

    charge, mult, atom_block = parse_xyz(xyz_path)
    basis, ecp = load_basis_preset(atom_block, BASIS_PRESET)
    mol = gto.M(
        atom=atom_block, basis=basis, ecp=ecp,
        charge=charge, spin=mult - 1, verbose=0,
    )
    if mol.spin == 0:
        mf = dft.RKS(mol)
    else:
        mf = dft.UKS(mol)
    mf.xc = "CF22D,CF22D"
    mf.grids.level = GRID_LEVEL
    mf.max_memory = MAX_MEMORY_MB
    mf.kernel()
    if not mf.converged:
        log(f"SCF did not converge for {name}; retrying with the PySCF Newton solver.")
        mf = mf.newton()
        mf.max_cycle = max(mf.max_cycle, 50)
        mf.verbose = max(mf.verbose, 4)
        mf.kernel()
        if not mf.converged:
            raise RuntimeError(f"SCF not converged for {name} after Newton retry")
        log(f"Newton SCF converged for {name}: E = {mf.e_tot:.12f} Eh")
    save_mf_uks(mf, str(work_dir / f"{name}.pychk"))

    if mol.spin == 0:
        ee = CF22D_nxc_rks(mf)
    else:
        ee = CF22D_nxc(mf)
    ee = np.asarray(ee, dtype=float)
    temporary = cache.with_suffix('.tmp')
    with temporary.open('wb') as handle:
        np.save(handle, ee)
    temporary.replace(cache)
    return ee


def compute_molecule_process(xyz_path, work_dir, threads):
    """PySCF thread settings are process-global: isolate each molecule."""
    started = time.time()
    env = molecule_environment(threads)
    env.update(DFTHUB_MOLECULE_THREADS=str(threads), DFTHUB_GRID=str(GRID_LEVEL))
    molecule_log = work_dir / (xyz_path.stem + '.scf.log')
    with molecule_log.open('a') as output:
        result = subprocess.run(
            [sys.executable, '-u', str(PROGRAM_DIR / 'molecule_worker.py'),
             '--xyz', str(xyz_path), '--work-dir', str(work_dir),
             '--basis', BASIS_PRESET, '--threads', str(threads)],
            env=env, stdout=output, stderr=subprocess.STDOUT,
        )
    if result.returncode:
        with molecule_log.open('rb') as handle:
            handle.seek(max(0, molecule_log.stat().st_size - 2048))
            tail = handle.read().decode(errors='replace').strip().splitlines()
        detail = tail[-1] if tail else f'exit code {result.returncode}'
        raise RuntimeError(f'{xyz_path.stem}: {detail}; see {molecule_log}')
    values = np.load(work_dir / (xyz_path.stem + '.desc.npy'))
    if values.shape != (78,) or not np.all(np.isfinite(values)):
        raise ValueError(f'{xyz_path.stem}: invalid descriptors')
    return values, time.time() - started, threads


def fit_row(ee, edisp):
    """Map the 78 raw CF25D values + dispersion to the 62-column TMB11 fit row.

    col 0      : E0 (total energy minus the xc contribution)
    col 1..58  : E0 + descriptor energies ee[1:59]
    col 59     : E0 + exact-exchange energy ee[-1]
    col 60     : DFT-D3 dispersion energy (Eh)
    col 61     : extra energy shift in kcal/mol (0 here)
    """
    row = np.empty(62)
    row[0] = ee[0]
    row[1:59] = ee[0] + ee[1:59]
    row[59] = ee[0] + ee[-1]
    row[60] = edisp
    row[61] = 0.0
    return row


def find_ref_file(*dirs):
    for d in dirs:
        for f in sorted(Path(d).glob("*")):
            if f.is_file() and (f.name.endswith("_ref") or f.suffix == ".ref"):
                return f
    return None


def prepare_optional_test_set(output_dir):
    """Build evaluation-only descriptors for the optional test set.

    The returned ``TEST_INPUT`` is deliberately separate from ``INPUT`` and is
    never passed to opt_demo.py. This keeps the uploaded test set out of every
    optimization loss and weight calculation.
    """
    input_root = output_dir.parent.parent / "input"
    test_root = input_root / "test_set"
    manifest_path = test_root / "manifest.json"
    if not manifest_path.is_file():
        return None
    manifest = json.loads(manifest_path.read_text())
    archive = test_root / manifest["geometry"]
    reference = test_root / manifest["reference"]
    if not archive.is_file() or not reference.is_file():
        raise ValueError("Test set manifest references missing files")
    work_dir = output_dir / "test_work"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)
    dataset = str(manifest.get("dataset") or archive_name(str(archive)))
    uncompress(str(archive), str(work_dir))
    xyz_dir = work_dir / archive_name(str(archive))
    if not xyz_dir.is_dir():
        # Archives may contain a directory whose name omits the optional
        # `test_` upload prefix (Li4_IRC_10_points.tgz -> Li4_IRC_10_points/).
        # Prefer the only extracted subdirectory when the archive root itself
        # does not match the filename stem.
        subdirs = [path for path in work_dir.iterdir() if path.is_dir()]
        if len(subdirs) == 1:
            xyz_dir = subdirs[0]
    if not xyz_dir.is_dir():
        xyz_dir = work_dir
    xyz_files = sorted(xyz_dir.glob("*.xyz"))
    if not xyz_files:
        raise ValueError("Test geometry archive contains no .xyz files")
    preflight_basis(xyz_files, BASIS_PRESET)
    edisp = run_dftd3(xyz_dir)
    sizes = {xyz: int(xyz.read_text().splitlines()[0].split()[0]) for xyz in xyz_files}
    basis_sizes = {xyz: basis_size(xyz, BASIS_PRESET) for xyz in xyz_files}
    (work_dir / 'resources.json').write_text(json.dumps({
        xyz.stem: {'nao': nao, 'threads': min(TASK_THREADS, threads_for_basis(nao))} for xyz, nao in basis_sizes.items()
    }))
    rows = {}
    failures = []
    for _, (xyz, result, error) in enumerate(molecular_pool(
            xyz_files, sizes.__getitem__,
            lambda xyz, threads: compute_molecule_process(xyz, work_dir, threads),
            nao=basis_sizes.__getitem__), 1):
        if error is not None:
            failures.append(str(error))
            continue
        ee, _, _ = result
        rows[xyz.stem] = fit_row(ee, edisp[xyz.stem])
    if failures or len(rows) != len(xyz_files):
        raise RuntimeError("Test set density calculation failed: " + "; ".join(failures[:3]))
    descriptor_file = output_dir / "TEST_INPUT"
    with descriptor_file.open("w") as handle:
        for name, row in sorted(rows.items()):
            handle.write(name + " " + " ".join(f"{value:.10g}" for value in row) + "\n")
    shutil.copy2(reference, output_dir / "TEST_INPUT_ref")
    (output_dir / "TestDescriptors.json").write_text(json.dumps({
        "dataset": dataset, "count": len(rows), "basis": BASIS_PRESET,
        "source": "optional test set", "optimization": "excluded",
    }, indent=2) + "\n")
    log(f"Optional test set descriptors ready ({len(rows)} structures); excluded from optimization.")
    return descriptor_file


def generate_demo_script(params_file, output_file, dataset_name=""):
    """Generate a standalone Python script that registers the optimized CF22D functional."""
    params = np.loadtxt(params_file)
    if params.size == 59:
        cx, cy, cz, hf = params[:40], params[40:49], params[49:58], params[58]
    elif params.size == 58:
        cx, cy, cz, hf = params[:40], params[40:49], params[49:58], 0.462806
    else:
        return

    def _fmt_array(arr):
        lines = []
        for i in range(0, len(arr), 4):
            chunk = arr[i : i + 4]
            lines.append("    " + ", ".join(f"{v: .15e}" for v in chunk) + ",")
        return "\n".join(lines)

    script = f'''\
"""CF22D-SRP functional optimized by DFThub.

Dataset: {dataset_name}
Generated by DFThub  https://lrcwtech.com

Requirements: pyscf >= 2.13 (with libxc CF22D support)

Usage
-----
    from pyscf import gto, dft
    from CF22D_optimized import register_cf22d_srp

    mol = gto.M(atom="H 0 0 0; H 0 0 0.74", basis="def2-qzvp")
    mf = dft.RKS(mol)
    mf.grids.level = 6
    register_cf22d_srp(mf)
    mf.kernel()
"""

import numpy as np
from pyscf.dft import libxc

# 40 exchange coefficients  (Cx: _CC000 .. _CC302)
CX = np.array([
{_fmt_array(cx)}
])

# 9 LSDA correlation coefficients  (Cy: _a0 .. _a8)
CY = np.array([
{_fmt_array(cy)}
])

# 9 PBE-LSDA correlation coefficients  (Cz: _b0 .. _b8)
CZ = np.array([
{_fmt_array(cz)}
])

# HF exact-exchange mixing coefficient
HF_COEFF = {hf}


def register_cf22d_srp(mf, name="cf22d_srp"):
    """Register the optimized CF22D-SRP functional and apply it to *mf*.

    Note: pyscf lowercases xc names internally, so *name* must be lowercase.
    """
    x_params = np.zeros(41)
    x_params[:40] = CX
    x_params[40] = HF_COEFF

    c_params = np.zeros(24)
    c_params[:9] = CY
    c_params[12:21] = CZ

    name = name.lower()
    libxc.register_custom_functional_(
        name,
        "CF22D,CF22D",
        ext_params={{340: x_params, 341: c_params}},
    )
    mf.xc = name
    return mf


if __name__ == "__main__":
    from pyscf import gto, dft

    mol = gto.M(atom="H 0 0 0; H 0 0 0.74", basis="def2-qzvp", verbose=4)
    mf = dft.RKS(mol)
    mf.grids.level = 6
    register_cf22d_srp(mf)
    mf.kernel()
    print(f"Total energy: {{mf.e_tot:.10f}} Hartree")
'''
    Path(output_file).write_text(script)


def read_inverse_weight(weight_csv):
    """weight.csv: header + 'DARC\t...\t<inverse weight>' (written by the backend)."""
    with open(weight_csv) as f:
        lines = [l.strip() for l in f if l.strip()]
    for line in lines[1:]:
        fields = re.split(r"[\t,]", line)
        try:
            return float(fields[-1])
        except ValueError:
            continue
    return 0.02


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", dest="input_file", required=True, help="uploaded geometry archive")
    parser.add_argument("--output", required=True, help="job output directory")
    parser.add_argument("--weight", required=True, help="weight.csv with the dataset inverse weight")
    parser.add_argument("--basis", choices=SUPPORTED_BASIS,
                        default=BASIS_PRESET if BASIS_PRESET in SUPPORTED_BASIS else DEFAULT_BASIS,
                        help=f"PySCF basis/ECP preset (default: {DEFAULT_BASIS})")
    args = parser.parse_args()
    enter_task(args.output, TASK_THREADS)
    BASIS_PRESET = args.basis
    BASIS, ECP = BASIS_PRESETS[BASIS_PRESET]

    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    LOG_FILE = output_dir / "process.log"

    t0 = time.time()
    log("The program starts running!")
    log(
        f"engine: pyscf CF22D | preset={BASIS_PRESET} | basis={BASIS} | "
        f"ecp={ECP or 'none'} | grid level={GRID_LEVEL} | task thread budget={TASK_THREADS} | molecule threads follow basis size and task capacity"
    )

    # ---- Step 1: uncompress -------------------------------------------------
    dataset = archive_name(args.input_file)
    work_dir = output_dir / "work"
    basis_file = output_dir / "basis.txt"
    cached_basis = basis_file.read_text().strip() if basis_file.exists() else DEFAULT_BASIS
    if work_dir.exists():
        keep = []
        if cached_basis == BASIS_PRESET:
            keep = list(work_dir.glob("*.desc.npy")) + list(work_dir.glob("*.pychk"))
        tmp = {f.name: f.read_bytes() for f in keep}
        shutil.rmtree(work_dir)
        work_dir.mkdir(parents=True)
        for fname, data in tmp.items():
            (work_dir / fname).write_bytes(data)
    else:
        work_dir.mkdir(parents=True)
    basis_file.write_text(BASIS_PRESET + "\n")
    uncompress(args.input_file, work_dir)
    xyz_dir = work_dir / dataset
    if not xyz_dir.is_dir():
        xyz_dir = work_dir
    log("File decompression completed !")

    xyz_files = sorted(xyz_dir.glob("*.xyz"))
    if not xyz_files:
        log("[Error] no .xyz structures found, exiting.")
        sys.exit(1)
    log(f"Found {len(xyz_files)} structures in dataset '{dataset}'.")

    try:
        preflight_basis(xyz_files, BASIS_PRESET)
    except Exception as exc:
        log(f"[Error] basis preflight failed: {exc}. Exiting program.")
        sys.exit(1)
    log(f"Basis preflight completed for preset '{BASIS_PRESET}'.")

    # ---- Step 2: DFT-D3 dispersion -----------------------------------------
    log("DFT-D3 dispersion calculations......")
    edisp = run_dftd3(xyz_dir)
    t1 = time.time()
    log(f"DFT-D3 finished, total time spent: {(t1 - t0) / 60:.2f} min")

    # ---- Steps 3+4: SCF + descriptors ---------------------------------------
    log(f"Initial density calculation (pyscf, CF22D/{BASIS_PRESET})......")
    rows = {}
    failures = []
    sizes = {xyz: int(xyz.read_text().splitlines()[0].split()[0]) for xyz in xyz_files}
    basis_sizes = {xyz: basis_size(xyz, BASIS_PRESET) for xyz in xyz_files}
    (work_dir / 'resources.json').write_text(json.dumps({
        xyz.stem: {'nao': nao, 'threads': min(TASK_THREADS, threads_for_basis(nao))} for xyz, nao in basis_sizes.items()
    }))
    for i, (xyz, result, error) in enumerate(molecular_pool(
            xyz_files, sizes.__getitem__,
            lambda xyz, threads: compute_molecule_process(xyz, work_dir, threads),
            nao=basis_sizes.__getitem__), 1):
        name = xyz.stem
        if error is not None:
            failures.append(name)
            log(f"[Error] {error}")
            continue
        ee, elapsed, threads = result
        rows[name] = fit_row(ee, edisp[name])
        log(f"  [{i}/{len(xyz_files)}] {name} done ({elapsed / 60:.2f} min; threads={threads}), E0+Exc check passed")
    if failures:
        log(f"[Error] Failed molecules: {', '.join(failures)}. Optimization was not started.")
        sys.exit(1)
    t2 = time.time()
    log(f"Descriptor calculations finished, total time spent: {(t2 - t1) / 60:.2f} min")

    # Optional evaluation set: calculate its initial densities now, but keep
    # the descriptors outside INPUT so the optimizer never sees them.
    try:
        prepare_optional_test_set(output_dir)
    except Exception as exc:
        log(f"[Error] optional test set failed: {exc}. Optimization was not started.")
        sys.exit(1)

    # ---- Step 5: assemble optimizer inputs ----------------------------------
    fit_file = output_dir / "INPUT"
    with open(fit_file, "w") as f:
        for name, row in sorted(rows.items()):
            f.write(name + " " + " ".join(f"{v:.10g}" for v in row) + "\n")

    ref_src = find_ref_file(Path(args.input_file).parent, work_dir, xyz_dir)
    if ref_src is None:
        log("[Error] no *_ref/.ref reference file found, cannot optimize. Exiting.")
        sys.exit(1)
    ref_file = output_dir / "INPUT_ref"
    shutil.copy(ref_src, ref_file)
    inverse_weight = read_inverse_weight(args.weight)
    log(f"Optimizer inputs ready (ref: {ref_src.name}, inverse weight: {inverse_weight}).")

    # ---- Step 6: parameter optimization -------------------------------------
    log("Optimizing parameters.....")
    opt = subprocess.run(
        [
            sys.executable,
            str(PROGRAM_DIR / "opt_demo.py"),
            "--fit", str(fit_file),
            "--ref", str(ref_file),
            "--inverse-weight", str(inverse_weight),
            "--output", str(output_dir),
            "--demo-name", f"{Path(args.input_file).parents[1].name}_{dataset}",
        ],
        capture_output=True,
        text=True,
    )
    (output_dir / "optimize.log").write_text(opt.stdout + "\n" + opt.stderr)
    if opt.returncode != 0:
        log(f"[Error] optimization failed, see optimize.log. Exiting.")
        sys.exit(1)
    t3 = time.time()
    log(f"Parameters optimization finished ({(t3 - t2) / 60:.2f} min), outputting results......")

    # ---- Generate demo script for the optimized functional --------------------
    new_params = output_dir / "NEW-params.txt"
    demo_script = output_dir / "CF22D_optimized.py"
    if new_params.exists():
        generate_demo_script(new_params, demo_script, dataset_name=dataset)
        log(f"Demo script generated: {demo_script.name}")

    log(f"The total time taken to run the program is: {(t3 - t0) / 60:.2f} min")
    log("SUCCESS!")
