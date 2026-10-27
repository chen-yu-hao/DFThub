"""Verified, atomic checkpoints for the SCF, stability and descriptor stages."""
import hashlib
import json
import math
import os
from pathlib import Path

from dfthub.pipeline.refinement import file_hash, write_json

PROTOCOL = 1


def job_identity(xyz, basis, functional, grid):
    from dfthub.pipeline.basis_presets import load_basis_preset
    lines = Path(xyz).read_text().strip().splitlines()
    resolved = load_basis_preset('\n'.join(lines[2:]), basis)
    payload = {'protocol': PROTOCOL, 'geometry': file_hash(xyz), 'basis': resolved,
               'functional': file_hash(functional), 'grid': grid, 'conv_tol': 1e-8}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def progress_path(checkpoint):
    return Path(checkpoint).with_suffix('.progress.json')


def read_progress(checkpoint, identity):
    try:
        record = json.loads(progress_path(checkpoint).read_text())
        if record.get('identity') != identity:
            return None
        return record
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def descriptor_valid(checkpoint, grid):
    import numpy as np
    checkpoint = Path(checkpoint)
    try:
        values = np.load(checkpoint.with_suffix('.desc.npy'), allow_pickle=False)
        info = json.loads(checkpoint.with_suffix('.desc.json').read_text())
        return (values.shape == (62,) and bool(np.all(np.isfinite(values))) and
                info.get('converged') is True and info.get('grid_level') == grid and
                math.isfinite(info['energy']) and
                abs(info['energy'] - info['reconstructed_energy']) <= 1e-6)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def completed_energy(checkpoint, identity, grid):
    checkpoint = Path(checkpoint)
    record = read_progress(checkpoint, identity)
    if not record or record.get('stage') != 'complete' or not descriptor_valid(checkpoint, grid):
        return None
    try:
        paths = {'checkpoint': checkpoint, 'descriptor': checkpoint.with_suffix('.desc.npy'),
                 'details': checkpoint.with_suffix('.desc.json')}
        if any(file_hash(path) != record['hashes'][key] for key, path in paths.items()):
            return None
        energy = record['energy']
        return energy if math.isfinite(energy) else None
    except (OSError, KeyError, TypeError, ValueError):
        return None


def atomic_checkpoint(mf, path):
    from pyscf.scf import chkfile
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    # A fresh HDF5 file avoids retaining unrelated/stale checkpoint keys.
    temporary.unlink(missing_ok=True)
    chkfile.dump_scf(mf.mol, str(temporary), mf.e_tot, mf.mo_energy, mf.mo_coeff, mf.mo_occ)
    os.replace(temporary, path)


def save_stage(mf, checkpoint, identity, stage, rounds=0):
    checkpoint = Path(checkpoint)
    path = checkpoint.with_suffix('.scf.chk' if stage == 'scf' else '.stable.chk')
    atomic_checkpoint(mf, path)
    write_json(progress_path(checkpoint), {
        'identity': identity, 'stage': stage, 'rounds': rounds,
        'checkpoint_sha256': file_hash(path), 'energy': float(mf.e_tot),
    })
    print(f'Checkpoint saved: {stage} ({path.name})', flush=True)


def restore_stage(mf, checkpoint, identity):
    import numpy as np
    from pyscf import gto
    from pyscf.scf import chkfile
    record = read_progress(checkpoint, identity)
    if not record or record.get('stage') not in ('scf', 'stable', 'complete'):
        return None
    stage = record['stage']
    path = Path(checkpoint).with_suffix('.scf.chk' if stage == 'scf' else '.stable.chk')
    try:
        if file_hash(path) != record['checkpoint_sha256']:
            return None
        mol, data = chkfile.load_scf(str(path))
        if (mol.spin != mf.mol.spin or mol.charge != mf.mol.charge or
                mol.nao_nr() != mf.mol.nao_nr() or not gto.same_mol(mol, mf.mol, cmp_basis=True)):
            return None
        if not all(np.all(np.isfinite(data[key])) for key in ('e_tot', 'mo_energy', 'mo_coeff', 'mo_occ')):
            return None
        for key in ('e_tot', 'mo_energy', 'mo_coeff', 'mo_occ'):
            setattr(mf, key, data[key])
        mf.converged = True
        print(f'Resuming after {stage}: {path.name}', flush=True)
        return record
    except (OSError, KeyError, TypeError, ValueError):
        return None


def mark_complete(mf, checkpoint, identity, rounds):
    checkpoint = Path(checkpoint)
    if not descriptor_valid(checkpoint, mf.grids.level):
        raise RuntimeError('SCF descriptors are incomplete or invalid')
    atomic_checkpoint(mf, checkpoint)
    stable = checkpoint.with_suffix('.stable.chk')
    write_json(progress_path(checkpoint), {
        'identity': identity, 'stage': 'complete', 'rounds': rounds,
        'energy': float(mf.e_tot), 'checkpoint_sha256': file_hash(stable),
        'hashes': {'checkpoint': file_hash(checkpoint),
                   'descriptor': file_hash(checkpoint.with_suffix('.desc.npy')),
                   'details': file_hash(checkpoint.with_suffix('.desc.json'))},
    })


def run_staged_scf(mf, functional, checkpoint, identity, dm0=None):
    """Only stable densities with verified descriptors become completed results."""
    from dfthub.pipeline.refinement import save_scf_descriptors
    checkpoint = Path(checkpoint)
    record = restore_stage(mf, checkpoint, identity)
    if record and record['stage'] == 'complete':
        energy = completed_energy(checkpoint, identity, mf.grids.level)
        if energy is not None:
            print('Reusing completed SCF, stability and descriptors', flush=True)
            return energy
    mf.chkfile = None
    if not record:
        mf.kernel(dm0=dm0)
        if not mf.converged:
            dm = mf.make_rdm1()
            mf = mf.newton()
            mf.kernel(dm0=dm)
        if not mf.converged:
            raise RuntimeError('Input SCF did not converge after Newton retry')
        save_stage(mf, checkpoint, identity, 'scf')
    rounds = record.get('rounds', 0) if record else 0
    stable = bool(record and record['stage'] in ('stable', 'complete'))
    if not stable:
        for index in range(rounds, 5):
            result = mf.stability(internal=True, return_status=True)
            unstable_mo, stable = result[0], bool(result[2] if len(result) >= 4 else result[1])
            print(f'  stability round {index + 1}: internal={stable}', flush=True)
            if stable:
                rounds = index + 1
                save_stage(mf, checkpoint, identity, 'stable', rounds)
                break
            if unstable_mo is None:
                break
            dm = mf.make_rdm1(unstable_mo, mf.mo_occ)
            mf.kernel(dm0=dm)
            if not mf.converged:
                dm = mf.make_rdm1()
                mf = mf.newton()
                mf.kernel(dm0=dm)
            if not mf.converged:
                raise RuntimeError('Input SCF did not converge during stability recovery')
            save_stage(mf, checkpoint, identity, 'scf', index + 1)
        if not stable:
            raise RuntimeError('SCF density remains internally unstable after 5 stability rounds')
    mf.chkfile = str(checkpoint)
    # Retain .stable.chk throughout descriptor evaluation, even if it fails.
    atomic_checkpoint(mf, checkpoint)
    save_scf_descriptors(mf, functional, checkpoint.with_suffix('.desc.npy'),
                         stability={'internal': True, 'rounds': rounds})
    mark_complete(mf, checkpoint, identity, rounds)
    return float(mf.e_tot)
