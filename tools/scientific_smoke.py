#!/usr/bin/env python3
"""Small, real DFThub/PySCF compatibility checks; production files are read only."""
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        os.environ[key] = '1'
    os.environ['DFTHUB_MOLECULE_THREADS'] = '1'

    import numpy as np
    import pyscf
    from pyscf import dft, gto, lib
    from pyscf.dft import libxc
    from pyscf.scf import chkfile
    from dfthub.pipeline.cf22d_baseline import native_cf22d_parameters
    from dfthub.pipeline.main import generate_demo_script
    from dfthub.pipeline.refinement import save_scf_descriptors
    from dfthub.pipeline.scf_resume import atomic_checkpoint, completed_energy, run_staged_scf

    lib.num_threads(1)
    started = time.monotonic()
    report = {
        'pyscf_version': pyscf.__version__,
        'pyscf_path': str(Path(pyscf.__file__).resolve()),
        'python': sys.executable,
        'libxc_version': libxc.libxc_version(),
        'settings': {'basis': 'sto-3g', 'grid_level': 0, 'threads': 1, 'conv_tol': 1e-10},
        'checks': {},
    }
    output_log = io.StringIO()
    try:
        with contextlib.redirect_stdout(output_log), tempfile.TemporaryDirectory(prefix='dfthub-pyscf-smoke-') as temporary:
            directory = Path(temporary)
            native = native_cf22d_parameters()
            coefficients = np.asarray(native['coefficients'])
            assert coefficients.shape == (59,) and np.isfinite(coefficients).all()
            report['native_parameters'] = {
                'count': len(coefficients), 'sha256': native['parameter_sha256'],
                'hf': float(coefficients[-1]),
                'component_ids': sorted(int(value) for value in libxc._get_xc('CF22D,CF22D').obj_by_id()),
            }
            params = directory / 'params.txt'
            np.savetxt(params, coefficients, fmt='%.17g')
            module_path = directory / 'CF22D_smoke.py'
            generate_demo_script(params, module_path, dataset_name='temporary compatibility smoke')
            spec = importlib.util.spec_from_file_location('dfthub_smoke_functional', module_path)
            functional = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(functional)
            report['generated_functional_sha256'] = hashlib.sha256(module_path.read_bytes()).hexdigest()

            for label, atom, spin in [('RKS_H2', 'H 0 0 0; H 0 0 0.74', 0), ('UKS_H', 'H 0 0 0', 1)]:
                section = report['checks'][label] = {}
                mol = gto.M(atom=atom, basis='sto-3g', spin=spin, verbose=0)
                constructor = dft.RKS if spin == 0 else dft.UKS

                def make_mf():
                    mf = constructor(mol)
                    mf.grids.level = 0
                    mf.max_memory = 512
                    mf.conv_tol = 1e-10
                    mf.max_cycle = 50
                    mf.chkfile = None
                    return mf

                reference = make_mf()
                reference.xc = 'CF22D,CF22D'
                reference.kernel()
                assert reference.converged, f'{label}: native SCF not converged'
                section['native_energy'] = float(reference.e_tot)
                mf = make_mf()
                xc_name = 'dfthub_smoke_' + label.lower()
                functional.register_cf22d_srp(mf, name=xc_name)
                section['custom_hybrid_coeff'] = libxc.hybrid_coeff(mf.xc)
                assert abs(section['custom_hybrid_coeff'] - coefficients[-1]) < 1e-14
                mf.kernel(dm0=reference.make_rdm1())
                assert mf.converged, f'{label}: custom SCF not converged'
                section['custom_energy'] = float(mf.e_tot)
                section['native_custom_error'] = abs(float(mf.e_tot - reference.e_tot))
                assert section['native_custom_error'] < 1e-8

                checkpoint = directory / (label + '.chk')
                mf.chkfile = str(checkpoint)
                descriptor = checkpoint.with_suffix('.desc.npy')
                save_scf_descriptors(mf, functional, descriptor)
                values = np.load(descriptor, allow_pickle=False)
                details = json.loads(descriptor.with_suffix('.json').read_text())
                section['descriptor_count'] = int(values.size)
                section['descriptor_finite'] = bool(np.isfinite(values).all())
                section['descriptor_reconstructed_energy'] = details['reconstructed_energy']
                section['descriptor_energy_error'] = abs(details['energy'] - details['reconstructed_energy'])
                assert values.shape == (62,) and section['descriptor_finite']
                assert section['descriptor_energy_error'] <= 1e-6

                atomic_checkpoint(mf, checkpoint)
                restored_mol, data = chkfile.load_scf(str(checkpoint))
                section['checkpoint_same_molecule'] = bool(gto.same_mol(mol, restored_mol, cmp_basis=True))
                section['checkpoint_energy_error'] = abs(float(data['e_tot']) - mf.e_tot)
                section['checkpoint_mo_error'] = float(np.max(np.abs(data['mo_coeff'] - mf.mo_coeff)))
                assert section['checkpoint_same_molecule']
                assert section['checkpoint_energy_error'] < 1e-14 and section['checkpoint_mo_error'] == 0.0

                # H/sto-3g has no occupied-to-virtual orbital rotations in either
                # spin channel.  The old engine's Newton solver raises TypeError
                # for that degenerate problem; exercise second derivatives and
                # staged stability with H2, which has a nonempty rotation space.
                occupations = np.atleast_2d(mf.mo_occ)
                rotations = sum(int(np.count_nonzero(occ > 0) * np.count_nonzero(occ == 0)) for occ in occupations)
                section['orbital_rotation_count'] = rotations
                if rotations == 0:
                    section['newton_stability_skipped'] = 'No occupied-to-virtual orbital rotations for H/sto-3g.'
                    section['passed'] = True
                    continue

                newton = mf.newton()
                newton.chkfile = None
                newton.kernel(dm0=mf.make_rdm1())
                section['newton_converged'] = bool(newton.converged)
                section['newton_energy'] = float(newton.e_tot)
                section['newton_energy_error'] = abs(float(newton.e_tot - mf.e_tot))
                assert newton.converged and section['newton_energy_error'] < 1e-8
                stability = mf.stability(internal=True, return_status=True)
                section['stability_return_count'] = len(stability)
                section['internally_stable'] = bool(stability[2] if len(stability) >= 4 else stability[1])
                assert section['internally_stable']

                staged = make_mf()
                functional.register_cf22d_srp(staged, name=xc_name + '_staged')
                staged_path = directory / (label + '_staged.chk')
                identity = 'isolated-smoke-' + label
                staged_energy = run_staged_scf(staged, functional, staged_path, identity)
                section['staged_energy'] = float(staged_energy)
                section['verified_completed_energy'] = completed_energy(staged_path, identity, 0)
                assert section['verified_completed_energy'] is not None
                assert abs(section['verified_completed_energy'] - section['custom_energy']) < 1e-8
                resumed = make_mf()
                functional.register_cf22d_srp(resumed, name=xc_name + '_resumed')
                def forbid_recomputation(*args, **kwargs):
                    raise AssertionError('completed checkpoint was recalculated')
                resumed.kernel = forbid_recomputation
                resumed.stability = forbid_recomputation
                section['resumed_energy'] = float(run_staged_scf(resumed, functional, staged_path, identity))
                assert section['resumed_energy'] == section['staged_energy']
                section['passed'] = True
        report['passed'] = True
    except Exception:
        report['passed'] = False
        report['error'] = traceback.format_exc()
    report['elapsed_seconds'] = round(time.monotonic() - started, 3)
    report['calculation_log'] = output_log.getvalue()
    payload = json.dumps(report, indent=2, sort_keys=True) + '\n'
    if args.output:
        args.output.write_text(payload)
    print(payload, end='')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
