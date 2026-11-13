"""UKS checkpoint helpers based on PySCF documentation.

This module wraps the workflow outlined in the PySCF manual for persisting
and restoring unrestricted Kohn–Sham (UKS) objects using checkpoint files.
"""

from pyscf import dft
from pyscf.scf import chkfile


def save_mf_uks(mf_uks, chk_path):
    """Write a ``pyscf.dft.UKS`` object to ``chk_path``.

    Parameters
    ----------
    mf_uks : pyscf.dft.UKS
        UKS mean-field object whose state should be saved. The object must
        have finished SCF iterations so that ``dump_chk`` captures the full
        solution (orbitals, occupations, energies, etc.).
    chk_path : str
        Target HDF5 checkpoint path. Existing files will be overwritten.
    """

    mf_uks.dump_chk(chk_path)


def load_mf_uks(chk_path):
    """Load a ``pyscf.dft.UKS`` object from ``chk_path``.

    Parameters
    ----------
    chk_path : str
        Path to the HDF5 checkpoint produced by :func:`save_mf_uks` or
        ``mf.dump_chk``.

    Returns
    -------
    pyscf.dft.UKS
        A UKS object populated with the saved molecular data and SCF results.
    """

    mol = chkfile.load_mol(chk_path)
    scf_group = chkfile.load(chk_path, "scf")
    if scf_group is None:
        raise ValueError(f"No SCF data found in '{chk_path}'.")

    mf_uks = dft.UKS(mol)
    mf_uks.__dict__.update(scf_group)
    mf_uks.chkfile = chk_path
    mf_uks.grids.level = 6
    mf_uks.grids.build()
    return mf_uks

def load_mf_rks(chk_path):
    """Load a ``pyscf.dft.UKS`` object from ``chk_path``.

    Parameters
    ----------
    chk_path : str
        Path to the HDF5 checkpoint produced by :func:`save_mf_uks` or
        ``mf.dump_chk``.

    Returns
    -------
    pyscf.dft.UKS
        A UKS object populated with the saved molecular data and SCF results.
    """

    mol = chkfile.load_mol(chk_path)
    scf_group = chkfile.load(chk_path, "scf")
    if scf_group is None:
        raise ValueError(f"No SCF data found in '{chk_path}'.")

    mf_uks = dft.RKS(mol)
    mf_uks.__dict__.update(scf_group)
    mf_uks.chkfile = chk_path
    mf_uks.grids.level = 6
    mf_uks.grids.build()
    return mf_uks

def load_mf_rks_from_uks(chk_path):
    """Load a ``pyscf.dft.UKS`` object from ``chk_path``.

    Parameters
    ----------
    chk_path : str
        Path to the HDF5 checkpoint produced by :func:`save_mf_uks` or
        ``mf.dump_chk``.

    Returns
    -------
    pyscf.dft.UKS
        A UKS object populated with the saved molecular data and SCF results.
    """

    mol = chkfile.load_mol(chk_path)
    scf_group = chkfile.load(chk_path, "scf")
    if scf_group is None:
        raise ValueError(f"No SCF data found in '{chk_path}'.")

    mf_rks = dft.RKS(mol)
    scf_group['mo_energy'] = scf_group['mo_energy'][0]
    scf_group['mo_coeff'] = scf_group['mo_coeff'][0]
    scf_group['mo_occ'] = scf_group['mo_occ'][0]+scf_group['mo_occ'][1]
    mf_rks.__dict__.update(scf_group)

    # mf_rks.chkfile = chk_path
    mf_rks.grids.level = 6
    mf_rks.grids.build()
    return mf_rks
