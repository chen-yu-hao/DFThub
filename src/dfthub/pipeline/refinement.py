"""Immutable Input SCF descriptors and optimizer inputs for iterative fits."""
import hashlib
import json
import math
import os
import shutil
import time
import uuid
from pathlib import Path
from dfthub.pipeline.testset_inheritance import preserve_test_manifest


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def read_input_rows(path):
    rows = {}
    for line in Path(path).read_text().splitlines():
        fields = line.split()
        if fields:
            values = [float(value) for value in fields[1:]]
            if fields[0] in rows or len(values) != 62 or not all(math.isfinite(value) for value in values):
                raise ValueError("Invalid Input descriptors")
            rows[fields[0]] = values
    if not rows:
        raise ValueError("Input descriptors are empty")
    return rows


def correct_input_energies(electronic_energies, fit_file):
    """Use the unchanged D3 and shift columns inherited from the initial fit."""
    rows = read_input_rows(fit_file)
    corrections = {name: values[60:] for name, values in sorted(rows.items())}
    digest = hashlib.sha256(json.dumps(corrections, sort_keys=True).encode()).hexdigest()
    energies, details = {}, {}
    for name, electronic in electronic_energies.items():
        if name not in corrections or not math.isfinite(electronic):
            raise ValueError(f"Missing corrections or invalid SCF energy: {name}")
        d3, shift = corrections[name]
        total = electronic + d3 + shift / 627.509
        energies[name] = total
        details[name] = {"electronic_hartree": electronic, "d3_hartree": d3,
                         "energy_shift_kcal_mol": shift, "total_hartree": total}
    return energies, details, digest


def optimizer_files(source, target):
    shutil.copytree(source / "Database_updated", target / "Database_updated")
    for name in ("opt.py", "dataset.py", "saver.py", "params.txt"):
        shutil.copy2(source / name, target / name)
    # copytree/copy2 preserve read-only site-packages permissions. The new
    # workspace must be writable even when all packaged resources are 0444/0555.
    for path in [target, *target.rglob('*')]:
        path.chmod(path.stat().st_mode | (0o700 if path.is_dir() else 0o600))


def ensure_optimizer_snapshot(output):
    """Recover historical fits only from a matching retained optimizer workspace."""
    target = output / "optimizer_snapshot"
    if target.is_dir():
        return target
    from dfthub.paths import data_dir
    demo_root = Path(os.environ.get("DFTHUB_DEMO_ROOT", str(data_dir() / "optimizer")))
    expected = {name: file_hash(output / name) for name in ("NEW-params.txt", "INPUT", "INPUT_ref")}
    for demo in sorted(demo_root.glob("demo_*"), reverse=True):
        candidates = {"NEW-params.txt": demo / "NEW-params.txt", "INPUT": demo / "Database_updated/fit/INPUT", "INPUT_ref": demo / "Database_updated/ref/INPUT_ref"}
        if all(path.is_file() and file_hash(path) == expected[name] for name, path in candidates.items()):
            temporary = output / (".optimizer_snapshot-" + uuid.uuid4().hex)
            temporary.mkdir()
            optimizer_files(demo, temporary)
            temporary.rename(target)
            return target
    raise ValueError("The original optimizer workspace is unavailable. Create a new weight optimization before refining.")


def source_hash(path):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    if path.is_file():
        return file_hash(path)
    return hashlib.sha256(''.join(str(p.relative_to(path)) + file_hash(p)
                                 for p in sorted(path.rglob('*')) if p.is_file()).encode()).hexdigest()


def prepare_input_snapshot(output, geometry, reference, functional, basis, grid,
                           test_geometry=None, test_reference=None, force=False):
    """Capture sources before SCF; the ready manifest is published only on success."""
    if file_hash(reference) != file_hash(output / "INPUT_ref"):
        raise ValueError("Input reference differs from the parent optimization")
    context = {
        'grid_level': grid, 'basis': basis, 'geometry': geometry.name,
        'geometry_sha256': source_hash(geometry), 'reference_sha256': file_hash(reference),
        'parameter_sha256': file_hash(output / 'NEW-params.txt'),
        'functional_sha256': file_hash(functional), 'source_input_sha256': file_hash(output / 'INPUT'),
        'weight_sha256': file_hash(output / 'weight.csv'),
        'lineage_sha256': file_hash(output / 'run.json') if (output / 'run.json').exists() else None,
        'test_geometry_sha256': source_hash(test_geometry) if test_geometry else None,
        'test_reference_sha256': file_hash(test_reference) if test_reference else None,
        'test_input_sha256': file_hash(output / 'TEST_INPUT') if test_geometry and (output / 'TEST_INPUT').is_file() else None,
    }
    if not force:
        candidates = sorted((output / 'input_srp').glob('*/manifest.json'),
                            key=lambda p: p.stat().st_mtime, reverse=True)
        for manifest in candidates:
            try:
                previous = json.loads(manifest.read_text())
                if not isinstance(previous, dict):
                    continue
                # Older Input snapshots captured the optional test files but
                # did not hash them. Verify those copies before adopting one.
                if 'test_geometry_sha256' not in previous and test_geometry:
                    test_root = manifest.parent / 'input/test_set'
                    previous['test_geometry_sha256'] = source_hash(test_root / test_geometry.name)
                    previous['test_reference_sha256'] = file_hash(test_root / test_reference.name)
                    # Old snapshots did not capture TEST_INPUT; only reuse the
                    # training checkpoints. Test molecules use a fresh stage.
                    previous['test_input_sha256'] = context['test_input_sha256']
                if any(previous.get(key) != value for key, value in context.items()):
                    continue
                saved = manifest.parent
                copies = {'parameter_sha256': saved / 'NEW-params.txt',
                          'functional_sha256': saved / 'CF22D_optimized.py',
                          'source_input_sha256': saved / 'source-INPUT',
                          'reference_sha256': saved / 'input/INPUT_ref',
                          'geometry_sha256': saved / 'input' / geometry.name,
                          'weight_sha256': saved / 'weight.csv'}
                if any(source_hash(path) != context[key] for key, path in copies.items()):
                    continue
                if test_geometry:
                    for source in (test_geometry, test_reference):
                        if source_hash(saved / 'input/test_set' / source.name) != source_hash(source):
                            raise ValueError('Test snapshot changed')
                    if (output / 'TEST_INPUT').is_file() and not (saved / 'source-TEST_INPUT').exists():
                        shutil.copy2(output / 'TEST_INPUT', saved / 'source-TEST_INPUT')
                    if context['test_input_sha256'] is not None and file_hash(saved / 'source-TEST_INPUT') != context['test_input_sha256']:
                        raise ValueError('Test corrections snapshot changed')
                    preserve_test_manifest(test_geometry, test_reference, saved / 'input/test_set')
                print(f'Reusing Input snapshot: {saved.name}', flush=True)
                previous.update(context)
                return saved, previous
            except (OSError, ValueError, KeyError, TypeError):
                continue
    snapshot = output / "input_srp" / uuid.uuid4().hex
    snapshot.mkdir(parents=True)
    inputs = snapshot / "input"
    inputs.mkdir()
    geometry_target = inputs / geometry.name
    if geometry.is_dir():
        shutil.copytree(geometry, geometry_target)
        geometry_hash = hashlib.sha256("".join(p.name + file_hash(p) for p in sorted(geometry.glob("*.xyz"))).encode()).hexdigest()
    else:
        shutil.copy2(geometry, geometry_target)
        geometry_hash = file_hash(geometry)
    shutil.copy2(reference, inputs / "INPUT_ref")
    if test_geometry and test_reference:
        optional_test = inputs / 'test_set'
        optional_test.mkdir()
        if test_geometry.is_dir():
            shutil.copytree(test_geometry, optional_test / test_geometry.name)
        else:
            shutil.copy2(test_geometry, optional_test / test_geometry.name)
        shutil.copy2(test_reference, optional_test / test_reference.name)
        preserve_test_manifest(test_geometry, test_reference, optional_test)
        if (output / 'TEST_INPUT').is_file():
            shutil.copy2(output / 'TEST_INPUT', snapshot / 'source-TEST_INPUT')
    (inputs / "basis.txt").write_text(basis + "\n")
    for name in ("INPUT", "NEW-params.txt", "weight.csv"):
        shutil.copy2(output / name, snapshot / ("source-INPUT" if name == "INPUT" else name))
    shutil.copy2(functional, snapshot / "CF22D_optimized.py")
    metadata = {
        "id": snapshot.name, "complete": False, "created_at": time.time(),
        "grid_level": grid, "basis": basis, "geometry": geometry.name,
        "geometry_sha256": geometry_hash, "reference_sha256": file_hash(reference),
        "parameter_sha256": file_hash(snapshot / "NEW-params.txt"),
        "functional_sha256": file_hash(snapshot / "CF22D_optimized.py"),
        "source_input_sha256": file_hash(snapshot / "source-INPUT"),
        "weight_sha256": file_hash(snapshot / "weight.csv"),
    }
    metadata.update(context)
    write_json(snapshot / "manifest.json", metadata)
    return snapshot, metadata


def save_scf_descriptors(mf, functional, output, stability=None):
    """Save descriptors from the final density and verify its electronic energy."""
    import numpy as np
    from xclib.CFXXD import CF22D_nxc, CF22D_nxc_rks
    from dfthub.pipeline.main import fit_row

    if not mf.converged:
        raise RuntimeError("Input SCF did not converge after Newton retry")
    # Refresh energy components and checkpoint before xclib temporarily changes XC.
    energy = float(mf.energy_tot(dm=mf.make_rdm1()))
    mf.e_tot = energy
    mf.dump_chk({"e_tot": energy, "mo_energy": mf.mo_energy,
                 "mo_coeff": mf.mo_coeff, "mo_occ": mf.mo_occ})
    original_xc = mf.xc
    try:
        raw = (CF22D_nxc_rks if mf.mol.spin == 0 else CF22D_nxc)(mf)
    finally:
        mf.xc = original_xc
    row = fit_row(np.asarray(raw, dtype=float), 0.0)
    coefficients = np.r_[functional.CX, functional.CY, functional.CZ, functional.HF_COEFF]
    reconstructed = float(row[0] + (row[1:60] - row[0]) @ coefficients)
    if not np.all(np.isfinite(row)) or not math.isfinite(energy) or abs(reconstructed - energy) > 1e-6:
        raise RuntimeError(f"Descriptor energy mismatch: SCF={energy}, reconstructed={reconstructed}")
    np.save(output, row)
    details = {
        "converged": True, "energy": energy, "reconstructed_energy": reconstructed,
        "grid_level": mf.grids.level, "basis": mf.mol._basis, "ecp": mf.mol._ecp,
    }
    if stability is not None:
        details["stability"] = stability
    write_json(Path(output).with_suffix(".json"), details)


def publish_input_snapshot(output, snapshot, metadata, jobs):
    import numpy as np
    parent_rows = read_input_rows(snapshot / "source-INPUT")
    if set(parent_rows) != {job.name for job in jobs}:
        raise ValueError("Input descriptor names do not match the parent dataset")
    rows, systems = [], {}
    for job in sorted(jobs, key=lambda j: j.name):
        descriptor = job.stage_chk.with_suffix(".desc.npy")
        row = np.load(descriptor, allow_pickle=False)
        details = json.loads(descriptor.with_suffix(".json").read_text())
        if row.shape != (62,) or not np.all(np.isfinite(row)) or not details["converged"] or details["grid_level"] != metadata["grid_level"]:
            raise ValueError(f"Invalid self-consistent descriptors: {job.name}")
        row[60:] = parent_rows[job.name][60:]
        rows.append(job.name + " " + " ".join(f"{v:.17g}" for v in row))
        systems[job.name] = details
    (snapshot / "INPUT").write_text("\n".join(rows) + "\n")
    metadata.update(complete=True, descriptor_sha256=file_hash(snapshot / "INPUT"), systems=systems)
    write_json(snapshot / "manifest.json", metadata)
    # The frontend reads a small manifest; full molecule provenance stays in the snapshot.
    write_json(output / "InputDescriptors.json", {k: v for k, v in metadata.items() if k != "systems"})
    return metadata["id"]
