"""Solvation models, geometry optimization and harmonic thermochemistry for DFThub."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Any

HARTREE_TO_KCAL = 627.509474063
BOLTZMANN_SI = 1.380649e-23
AVOGADRO_SI = 6.02214076e23
HARTREE_TO_J = 4.3597447222071e-18
R_HARTREE_PER_K = BOLTZMANN_SI / HARTREE_TO_J

SOLVENT_MODELS = ("none", "ief-pcm", "c-pcm", "ssvpe", "cosmo", "smd", "ddcosmo")
PCM_METHOD_MAP = {
    "ief-pcm": "IEF-PCM",
    "c-pcm": "C-PCM",
    "ssvpe": "SS(V)PE",
    "cosmo": "COSMO",
}
VIB_MODELS = ("rrho", "qrrho-grimme", "qrrho-full")

# Curated common solvents with exact names from PySCF's Minnesota Solvent Descriptor Database
COMMON_SOLVENTS = (
    {"id": "water", "name": "Water (H2O)", "eps": 78.3553, "category": "Polar protic"},
    {"id": "acetonitrile", "name": "Acetonitrile (MeCN)", "eps": 35.688, "category": "Polar aprotic"},
    {"id": "dimethylsulfoxide", "name": "Dimethyl sulfoxide (DMSO)", "eps": 46.826, "category": "Polar aprotic"},
    {"id": "methanol", "name": "Methanol (MeOH)", "eps": 32.613, "category": "Polar protic"},
    {"id": "ethanol", "name": "Ethanol (EtOH)", "eps": 24.852, "category": "Polar protic"},
    {"id": "n,n-dimethylformamide", "name": "N,N-Dimethylformamide (DMF)", "eps": 37.219, "category": "Polar aprotic"},
    {"id": "tetrahydrofuran", "name": "Tetrahydrofuran (THF)", "eps": 7.4257, "category": "Ethereal"},
    {"id": "dichloromethane", "name": "Dichloromethane (DCM)", "eps": 8.93, "category": "Halogenated"},
    {"id": "chloroform", "name": "Chloroform (CHCl3)", "eps": 4.7113, "category": "Halogenated"},
    {"id": "acetone", "name": "Acetone", "eps": 20.493, "category": "Polar aprotic"},
    {"id": "toluene", "name": "Toluene", "eps": 2.3741, "category": "Aromatic"},
    {"id": "benzene", "name": "Benzene", "eps": 2.2706, "category": "Aromatic"},
    {"id": "chlorobenzene", "name": "Chlorobenzene", "eps": 5.6968, "category": "Aromatic"},
    {"id": "1,4-dioxane", "name": "1,4-Dioxane", "eps": 2.2099, "category": "Ethereal"},
    {"id": "diethylether", "name": "Diethyl ether (Et2O)", "eps": 4.24, "category": "Ethereal"},
    {"id": "ethylacetate", "name": "Ethyl acetate (EtOAc)", "eps": 5.9867, "category": "Ester"},
    {"id": "n-hexane", "name": "n-Hexane", "eps": 1.8819, "category": "Nonpolar alkane"},
    {"id": "cyclohexane", "name": "Cyclohexane", "eps": 2.0165, "category": "Nonpolar alkane"},
    {"id": "n-heptane", "name": "n-Heptane", "eps": 1.9113, "category": "Nonpolar alkane"},
    {"id": "carbon tetrachloride", "name": "Carbon tetrachloride (CCl4)", "eps": 2.228, "category": "Halogenated"},
    {"id": "1,2-dichloroethane", "name": "1,2-Dichloroethane (DCE)", "eps": 10.125, "category": "Halogenated"},
    {"id": "2-propanol", "name": "2-Propanol (iPrOH)", "eps": 19.264, "category": "Polar protic"},
    {"id": "1-octanol", "name": "1-Octanol", "eps": 9.8629, "category": "Polar protic"},
    {"id": "acetic acid", "name": "Acetic acid (AcOH)", "eps": 6.2528, "category": "Polar protic"},
    {"id": "pyridine", "name": "Pyridine", "eps": 12.978, "category": "Aromatic"},
    {"id": "nitromethane", "name": "Nitromethane", "eps": 36.562, "category": "Polar aprotic"},
)


@dataclass(frozen=True)
class EnergyTaskOptions:
    basis: str = ""
    grid_level: int = 6
    with_d3: bool = True
    solvent_model: str = "none"
    solvent_name: str = "water"
    solvent_eps: float | None = None
    optimize_geometry: bool = False
    calc_thermo: bool = False
    temperature_k: float = 298.15
    pressure_pa: float = 101325.0
    vib_model: str = "qrrho-grimme"
    qrrho_freq0: float = 100.0
    freq_scale: float = 1.0
    solution_standard_state: bool = False

    def normalized(self, default_basis: str = "def2-qzvp") -> "EnergyTaskOptions":
        from dfthub.pipeline.basis_presets import SUPPORTED_BASIS

        basis = (self.basis or default_basis).strip().lower()
        if basis not in SUPPORTED_BASIS:
            raise ValueError(f"Unsupported basis preset: {basis}")
        grid = int(self.grid_level)
        if grid < 0 or grid > 9:
            raise ValueError("grid_level must be between 0 and 9")
        model = (self.solvent_model or "none").strip().lower()
        if model not in SOLVENT_MODELS:
            raise ValueError(f"Unsupported solvent_model: {model}")
        solvent = (self.solvent_name or "water").strip()
        eps = None
        if self.solvent_eps is not None and str(self.solvent_eps).strip() != "":
            eps = float(self.solvent_eps)
            if not math.isfinite(eps) or eps <= 1.0:
                raise ValueError("solvent_eps must be a finite dielectric constant > 1.0")
        if model == "smd" and eps is not None and not solvent:
            raise ValueError("SMD requires a named solvent from the Minnesota database")
        if model != "none" and eps is None:
            resolved_name, resolved_eps = resolve_solvent_entry(solvent)
            solvent = resolved_name
        temp = float(self.temperature_k)
        if not math.isfinite(temp) or temp <= 0.0 or temp > 10000.0:
            raise ValueError("temperature_k must be between 0 and 10000 K")
        press = float(self.pressure_pa)
        if not math.isfinite(press) or press <= 0.0 or press > 1e10:
            raise ValueError("pressure_pa must be positive")
        vib = (self.vib_model or "qrrho-grimme").strip().lower()
        if vib not in VIB_MODELS:
            raise ValueError(f"Unsupported vib_model: {vib}")
        freq0 = float(self.qrrho_freq0)
        if not math.isfinite(freq0) or freq0 <= 0.0 or freq0 > 1000.0:
            raise ValueError("qrrho_freq0 must be between 0 and 1000 cm^-1")
        scale = float(self.freq_scale)
        if not math.isfinite(scale) or scale <= 0.1 or scale > 2.0:
            raise ValueError("freq_scale must be between 0.1 and 2.0")
        return EnergyTaskOptions(
            basis=basis,
            grid_level=grid,
            with_d3=bool(self.with_d3),
            solvent_model=model,
            solvent_name=solvent if model != "none" else "water",
            solvent_eps=eps if model != "none" else None,
            optimize_geometry=bool(self.optimize_geometry),
            calc_thermo=bool(self.calc_thermo),
            temperature_k=temp,
            pressure_pa=press,
            vib_model=vib,
            qrrho_freq0=freq0,
            freq_scale=scale,
            solution_standard_state=bool(self.solution_standard_state),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None, default_basis: str = "def2-qzvp") -> "EnergyTaskOptions":
        if not data:
            return cls(basis=default_basis).normalized(default_basis)
        fields = {}
        for key in cls.__dataclass_fields__:
            if key in data and data[key] is not None:
                fields[key] = data[key]
        return cls(**fields).normalized(default_basis)

    def signature(self) -> str:
        payload = self.to_dict()
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def resolve_solvent_entry(solvent_name: str) -> tuple[str, float]:
    """Validate and normalize a solvent name against PySCF's solvent database."""
    raw = (solvent_name or "water").strip()
    try:
        from pyscf.solvent import _solvent_data

        canonical = _solvent_data.resolve_solvent_name(raw)
        if canonical not in _solvent_data.solvent_db:
            raise KeyError(raw)
        eps = float(_solvent_data.solvent_db[canonical][5])
        return canonical, eps
    except ImportError:
        for item in COMMON_SOLVENTS:
            if item["id"].lower() == raw.lower() or item["name"].lower() == raw.lower():
                return item["id"], float(item["eps"])
        return raw.lower(), 78.3553
    except Exception as exc:
        raise ValueError(f"Unknown solvent {raw!r}; choose a supported solvent or specify custom epsilon") from exc


def list_supported_solvents() -> list[dict[str, Any]]:
    """Return common solvents first, followed by the full Minnesota database."""
    common_ids = {item["id"] for item in COMMON_SOLVENTS}
    result = [dict(item, common=True) for item in COMMON_SOLVENTS]
    try:
        from pyscf.solvent import _solvent_data

        for name, values in sorted(_solvent_data.solvent_db.items()):
            if name in common_ids:
                continue
            result.append({
                "id": name,
                "name": name,
                "eps": float(values[5]),
                "category": "Minnesota Database",
                "common": False,
            })
    except ImportError:
        pass
    return result


def ensure_smd_cds_support() -> None:
    """Enable pure-Python SMD CDS energy and gradient when libsolvent is absent."""
    from pyscf.solvent import smd, smd_experiment
    import numpy as np

    if getattr(smd, "_dfthub_cds_patched", False):
        return
    for attr in (
        "sigma_water", "sigma_n", "sigma_alpha", "sigma_beta",
        "r_zz", "swtich_function", "atomic_surface_tension", "molecular_surface_tension",
    ):
        if not hasattr(smd, attr) and hasattr(smd_experiment, attr):
            setattr(smd, attr, getattr(smd_experiment, attr))
    from pyscf.solvent.grad import smd_experiment as smd_grad_exp

    orig_get_cds = smd.get_cds_legacy

    def _get_cds_with_fallback(smdobj):
        if smd.libsolvent is not None:
            return orig_get_cds(smdobj)
        smdobj._solvent = smdobj.solvent
        e_cds = float(smd_experiment.get_cds(smdobj))
        d_cds = np.asarray(smd_grad_exp.get_cds(smdobj), dtype=float)
        return e_cds, d_cds

    smd.get_cds_legacy = _get_cds_with_fallback
    smd._dfthub_cds_patched = True


def attach_solvation(mf, options: EnergyTaskOptions):
    """Attach the configured implicit solvation model to a PySCF Kohn-Sham object."""
    model = options.solvent_model.lower()
    if model == "none":
        return mf
    if model in PCM_METHOD_MAP:
        mf = mf.PCM()
        mf.with_solvent.method = PCM_METHOD_MAP[model]
        if options.solvent_eps is not None:
            mf.with_solvent.eps = float(options.solvent_eps)
        else:
            canonical, _ = resolve_solvent_entry(options.solvent_name)
            mf.with_solvent.solvent = canonical
        return mf
    if model == "smd":
        ensure_smd_cds_support()
        mf = mf.SMD()
        canonical, _ = resolve_solvent_entry(options.solvent_name)
        mf.with_solvent.solvent = canonical
        if options.solvent_eps is not None:
            mf.with_solvent.eps = float(options.solvent_eps)
        return mf
    if model == "ddcosmo":
        mf = mf.ddCOSMO()
        if options.solvent_eps is not None:
            mf.with_solvent.eps = float(options.solvent_eps)
        else:
            _, eps = resolve_solvent_entry(options.solvent_name)
            mf.with_solvent.eps = eps
        return mf
    raise ValueError(f"Unsupported solvent model: {options.solvent_model}")


def extract_solvation_summary(mf, options: EnergyTaskOptions) -> dict[str, Any] | None:
    """Extract dielectric constant, electrostatic solvation energy and CDS term."""
    if options.solvent_model == "none":
        return None
    ws = getattr(mf, "with_solvent", None)
    if ws is None:
        return None
    e_solv = getattr(ws, "e", None)
    e_cds = getattr(ws, "e_cds", None)
    eps = getattr(ws, "eps", None)
    if eps is None and options.solvent_name:
        try:
            _, eps = resolve_solvent_entry(options.solvent_name)
        except ValueError:
            eps = None
    return {
        "model": options.solvent_model,
        "method_label": PCM_METHOD_MAP.get(options.solvent_model, options.solvent_model.upper()),
        "solvent": options.solvent_name if options.solvent_eps is None else f"custom (eps={options.solvent_eps:g})",
        "eps": float(eps) if eps is not None and math.isfinite(float(eps)) else None,
        "e_solvent_hartree": float(e_solv) if e_solv is not None and math.isfinite(float(e_solv)) else None,
        "e_cds_hartree": float(e_cds) if e_cds is not None and math.isfinite(float(e_cds)) else None,
    }


def solution_standard_state_correction_hartree(temperature_k: float, pressure_pa: float) -> float:
    """Free-energy change for compressing 1 mol ideal gas at (T, P) to 1 mol/L (1000 mol/m^3).

    Delta G^{0 -> *} = R T ln(V_gas / V_1M) = R T ln(1000 * k_B * N_A * T / P)
    At 298.15 K and 101325 Pa (1 atm), this equals +1.894 kcal/mol (+0.003019 Eh).
    """
    if temperature_k <= 0 or pressure_pa <= 0:
        return 0.0
    molar_volume_ratio = (1000.0 * BOLTZMANN_SI * AVOGADRO_SI * temperature_k) / pressure_pa
    if molar_volume_ratio <= 0:
        return 0.0
    return float(R_HARTREE_PER_K * temperature_k * math.log(molar_volume_ratio))


def format_xyz_string(mol, comment: str = "") -> str:
    """Format a PySCF Mole object into a standard XYZ text block (in Angstrom)."""
    coords = mol.atom_coords(unit="A")
    lines = [str(mol.natm), comment or f"charge={mol.charge} mult={mol.multiplicity}"]
    for idx in range(mol.natm):
        sym = mol.atom_symbol(idx)
        x, y, z = coords[idx]
        lines.append(f"{sym:<4s} {x:16.10f} {y:16.10f} {z:16.10f}")
    return "\n".join(lines) + "\n"


def optimize_geometry_bfgs(mf_factory, mol0, dm0=None, max_steps: int = 50,
                           fmax_tol: float = 4.5e-4, frms_tol: float = 3.0e-4):
    """Relax molecular geometry with internal-coordinate-projected BFGS and analytical gradients."""
    import numpy as np
    from pyscf.hessian import thermo

    if mol0.natm <= 1:
        mf = mf_factory(mol0, dm0)
        return mf, mol0, {
            "converged": True,
            "steps": 0,
            "initial_energy_hartree": float(mf.e_tot),
            "final_energy_hartree": float(mf.e_tot),
            "energy_change_kcal_mol": 0.0,
            "max_grad_hartree_bohr": 0.0,
            "rms_grad_hartree_bohr": 0.0,
            "optimized_xyz": format_xyz_string(mol0, f"Optimized E={mf.e_tot:.10f} Eh"),
        }

    natm = mol0.natm
    ndim = natm * 3

    def project_internal(coords_bohr, vec):
        mass = np.ones(natm)
        tr_list = [row for row in thermo._get_TR(mass, coords_bohr) if np.linalg.norm(row) > 1e-12]
        if not tr_list:
            return vec.reshape(natm, 3)
        q, _ = np.linalg.qr(np.vstack(tr_list).T)
        flat = vec.ravel()
        flat = flat - q @ (q.T @ flat)
        return flat.reshape(natm, 3)

    coords = mol0.atom_coords(unit="B").copy()
    mf = mf_factory(mol0, dm0)
    e_curr = float(mf.e_tot)
    e_init = e_curr
    g_raw = np.asarray(mf.nuc_grad_method().kernel(), dtype=float)
    g_curr = project_internal(coords, g_raw)
    last_dm = mf.make_rdm1()

    h_inv = np.eye(ndim) / 0.5
    max_step = 0.25  # Bohr
    converged = False
    steps_taken = 0

    for step in range(1, max_steps + 1):
        fmax = float(np.max(np.abs(g_curr)))
        frms = float(np.sqrt(np.mean(g_curr ** 2)))
        print(
            f"  [GeomOpt] step {step - 1:2d}: E = {e_curr:18.10f} Eh  "
            f"max|F| = {fmax:.6f}  rms|F| = {frms:.6f} Eh/Bohr",
            flush=True,
        )
        if fmax <= fmax_tol and frms <= frms_tol:
            converged = True
            steps_taken = step - 1
            break

        dx = -(h_inv @ g_curr.ravel()).reshape(natm, 3)
        dx = project_internal(coords, dx)
        max_disp = float(np.max(np.abs(dx)))
        if max_disp > max_step:
            dx = dx * (max_step / max_disp)

        alpha = 1.0
        for _ls in range(4):
            c_try = coords + alpha * dx
            mol_try = mol0.copy()
            mol_try.set_geom_(c_try, unit="B")
            mf_try = mf_factory(mol_try, last_dm)
            e_try = float(mf_try.e_tot)
            g_try_raw = np.asarray(mf_try.nuc_grad_method().kernel(), dtype=float)
            g_try = project_internal(c_try, g_try_raw)
            if e_try <= e_curr + 5e-6 or float(np.max(np.abs(g_try))) < fmax:
                break
            alpha *= 0.5

        s = (c_try - coords).ravel()
        y = (g_try - g_curr).ravel()
        ys = float(np.dot(y, s))
        if ys > 1e-10:
            rho = 1.0 / ys
            ident = np.eye(ndim)
            v_mat = ident - rho * np.outer(s, y)
            h_inv = v_mat @ h_inv @ v_mat.T + rho * np.outer(s, s)

        coords = c_try
        mf = mf_try
        e_curr = e_try
        g_curr = g_try
        last_dm = mf.make_rdm1()
        steps_taken = step

    fmax = float(np.max(np.abs(g_curr)))
    frms = float(np.sqrt(np.mean(g_curr ** 2)))
    if not converged and fmax <= fmax_tol and frms <= frms_tol:
        converged = True
    print(
        f"  [GeomOpt] final ({'converged' if converged else 'max_steps'} after {steps_taken} steps): "
        f"E = {e_curr:18.10f} Eh  max|F| = {fmax:.6f} Eh/Bohr",
        flush=True,
    )
    mol_final = mf.mol
    return mf, mol_final, {
        "converged": converged,
        "steps": steps_taken,
        "initial_energy_hartree": e_init,
        "final_energy_hartree": e_curr,
        "energy_change_kcal_mol": (e_curr - e_init) * HARTREE_TO_KCAL,
        "max_grad_hartree_bohr": fmax,
        "rms_grad_hartree_bohr": frms,
        "optimized_xyz": format_xyz_string(mol_final, f"Optimized E={e_curr:.10f} Eh"),
    }


def _numerical_hessian_from_grad(mf_factory, mol0, dm0, step_bohr: float = 1e-3):
    """Finite-difference Hessian from analytical nuclear gradients (used for ddCOSMO)."""
    import numpy as np

    natm = mol0.natm
    coords0 = mol0.atom_coords(unit="B").copy()
    hess = np.zeros((natm, natm, 3, 3), dtype=float)
    for ia in range(natm):
        for ix in range(3):
            c_plus = coords0.copy()
            c_plus[ia, ix] += step_bohr
            mol_p = mol0.copy()
            mol_p.set_geom_(c_plus, unit="B")
            mf_p = mf_factory(mol_p, dm0)
            g_plus = np.asarray(mf_p.nuc_grad_method().kernel(), dtype=float)

            c_minus = coords0.copy()
            c_minus[ia, ix] -= step_bohr
            mol_m = mol0.copy()
            mol_m.set_geom_(c_minus, unit="B")
            mf_m = mf_factory(mol_m, dm0)
            g_minus = np.asarray(mf_m.nuc_grad_method().kernel(), dtype=float)

            hess[ia, :, ix, :] = (g_plus - g_minus) / (2.0 * step_bohr)
    return hess


def compute_thermochemistry(mf, options: EnergyTaskOptions, mf_factory=None) -> dict[str, Any]:
    """Compute molecular Hessian, vibrational frequencies, and RRHO/Quasi-RRHO thermochemistry."""
    import numpy as np
    from pyscf.hessian import thermo

    mol = mf.mol
    if options.solvent_model == "ddcosmo":
        if mf_factory is None:
            raise RuntimeError("mf_factory is required for ddCOSMO numerical Hessian")
        print("  [Thermo] Computing semi-numerical Hessian for ddCOSMO...", flush=True)
        hess = _numerical_hessian_from_grad(mf_factory, mol, mf.make_rdm1())
    else:
        print("  [Thermo] Computing analytical nuclear Hessian...", flush=True)
        hess = mf.Hessian().kernel()

    harm = thermo.harmonic_analysis(mol, hess, imaginary_freq=True)
    freq_au = np.asarray(harm["freq_au"])
    freq_wn_raw = np.asarray(harm["freq_wavenumber"])

    # Convert complex imaginary frequencies into negative real numbers (cm^-1) for display
    freqs_cm1: list[float] = []
    for val in freq_wn_raw:
        if np.iscomplexobj(val) and abs(val.imag) > abs(val.real):
            freqs_cm1.append(-float(abs(val.imag)) * options.freq_scale)
        else:
            freqs_cm1.append(float(np.real(val)) * options.freq_scale)
    freqs_cm1.sort()
    imag_freqs = [f for f in freqs_cm1 if f < -1e-2]
    real_freqs = [f for f in freqs_cm1 if f >= -1e-2]

    scaled_freq_au = freq_au * options.freq_scale
    use_qrrho_s = options.vib_model in ("qrrho-grimme", "qrrho-full")
    use_qrrho_h = options.vib_model == "qrrho-full"

    th = thermo.thermo(
        mf,
        scaled_freq_au,
        temperature=options.temperature_k,
        pressure=options.pressure_pa,
        qrrho=use_qrrho_s,
        qrrho_enthalpy=use_qrrho_h,
        qrrho_freq0=options.qrrho_freq0,
    )

    e0 = float(th["E0"][0])
    zpe = float(th["ZPE"][0])
    e_0k = float(th["E_0K"][0])
    e_tot = float(th["E_tot"][0])
    h_tot = float(th["H_tot"][0])
    g_gas_or_raw = float(th["G_tot"][0])
    s_tot = float(th["S_tot"][0])

    dg_conc = (
        solution_standard_state_correction_hartree(options.temperature_k, options.pressure_pa)
        if options.solution_standard_state
        else 0.0
    )
    g_final = g_gas_or_raw + dg_conc

    print(
        f"  [Thermo] T={options.temperature_k:.2f} K  P={options.pressure_pa:.1f} Pa  "
        f"ZPE={zpe:.8f} Eh  H={h_tot:.8f} Eh  G={g_final:.8f} Eh  "
        f"N_imag={len(imag_freqs)}",
        flush=True,
    )

    return {
        "temperature_k": options.temperature_k,
        "pressure_pa": options.pressure_pa,
        "vib_model": options.vib_model,
        "qrrho_freq0_cm1": options.qrrho_freq0,
        "freq_scale": options.freq_scale,
        "solution_standard_state": options.solution_standard_state,
        "standard_state_correction_hartree": dg_conc,
        "standard_state_correction_kcal_mol": dg_conc * HARTREE_TO_KCAL,
        "zpe_hartree": zpe,
        "zpe_kcal_mol": zpe * HARTREE_TO_KCAL,
        "e_0k_hartree": e_0k,
        "u_tot_hartree": e_tot,
        "h_tot_hartree": h_tot,
        "g_tot_hartree": g_final,
        "g_uncorrected_hartree": g_gas_or_raw,
        "thermal_correction_e_hartree": e_tot - e0,
        "thermal_correction_h_hartree": h_tot - e0,
        "thermal_correction_g_hartree": g_final - e0,
        "s_tot_hartree_per_k": s_tot,
        "s_tot_cal_mol_k": s_tot * HARTREE_TO_KCAL * 1000.0,
        "ts_tot_hartree": options.temperature_k * s_tot,
        "ts_tot_kcal_mol": options.temperature_k * s_tot * HARTREE_TO_KCAL,
        "imaginary_count": len(imag_freqs),
        "imaginary_frequencies_cm1": [round(f, 2) for f in imag_freqs],
        "lowest_frequency_cm1": round(freqs_cm1[0], 2) if freqs_cm1 else None,
        "frequencies_cm1": [round(f, 2) for f in freqs_cm1],
        "positive_frequencies_count": len(real_freqs),
        "symmetry_number": int(th["sym_number"][0]),
    }


def configure_cf22d_mf(mf, functional_path: str | None, options: EnergyTaskOptions):
    """Apply CF22D parameters, optional D3(0) dispersion, and implicit solvation to *mf*."""
    import importlib.util
    from pathlib import Path
    from dfthub.functional.pyscf import CF22D_D3_DISPERSION, _enable_dftd3_dispersion

    mf.grids.level = int(options.grid_level)
    mf.conv_tol = 1e-8
    mf.max_cycle = 500
    mf.chkfile = None

    mod = None
    if functional_path and Path(functional_path).is_file():
        spec = importlib.util.spec_from_file_location("cf22d_srp", str(functional_path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if hasattr(mod, "register_cf22d"):
            mod.register_cf22d(mf, with_d3=bool(options.with_d3))
        else:
            mod.register_cf22d_srp(mf)
            if options.with_d3:
                _enable_dftd3_dispersion(mf)
                mf.disp = CF22D_D3_DISPERSION
            else:
                mf.disp = False
    else:
        mf.xc = "CF22D,CF22D"
        if options.with_d3:
            _enable_dftd3_dispersion(mf)
            mf.disp = CF22D_D3_DISPERSION
        else:
            mf.disp = False

    mf = attach_solvation(mf, options)
    return mf, mod


def _solve_stable_scf(mf, dm0=None, check_stability: bool = True):
    """Run SCF with Newton fallback and optional internal stability verification."""
    mf.kernel(dm0=dm0)
    if not mf.converged:
        dm = mf.make_rdm1()
        mf_newton = mf.newton()
        mf_newton.kernel(dm0=dm)
        if mf_newton.converged:
            mf = mf_newton
    if not mf.converged:
        raise RuntimeError("SCF did not converge after Newton retry")

    rounds = 0
    stable = True
    if check_stability:
        for idx in range(5):
            result = mf.stability(internal=True, return_status=True)
            unstable_mo, stable = result[0], bool(result[2] if len(result) >= 4 else result[1])
            rounds = idx + 1
            print(f"  stability round {rounds}: internal={stable}", flush=True)
            if stable or unstable_mo is None:
                break
            dm = mf.make_rdm1(unstable_mo, mf.mo_occ)
            mf.kernel(dm0=dm)
            if not mf.converged:
                dm = mf.make_rdm1()
                mf_newton = mf.newton()
                mf_newton.kernel(dm0=dm)
                if mf_newton.converged:
                    mf = mf_newton
            if not mf.converged:
                raise RuntimeError("SCF did not converge during stability recovery")
        if not stable:
            raise RuntimeError("SCF density remains internally unstable after 5 stability rounds")
    return mf, rounds


def evaluate_molecule_energy(
    xyz_path,
    functional_path: str,
    options: EnergyTaskOptions,
    stage_dir,
    name: str,
    threads: int = 8,
) -> dict[str, Any]:
    """Run single-point, optional BFGS relaxation, solvation, and thermochemistry for one molecule."""
    import os
    from pathlib import Path
    from pyscf import dft, gto, lib
    from dfthub.pipeline.basis_presets import resolve_basis_sources
    from dfthub.pipeline.run_ame418_srp import parse_xyz
    from dfthub.pipeline.scf_resume import atomic_checkpoint

    xyz_path = Path(xyz_path)
    stage_dir = Path(stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)
    lib.num_threads(max(1, int(threads)))

    charge, spin, atom_block, natom = parse_xyz(xyz_path)
    ks_cls = dft.RKS if spin == 0 else dft.UKS
    basis_sources, ecp_sources = resolve_basis_sources(atom_block, options.basis)
    basis_dict = {el: gto.basis.load(src, el) for el, src in basis_sources.items()}
    ecp_dict = {el: gto.basis.load_ecp(src, el) for el, src in ecp_sources.items()} if ecp_sources else {}

    max_mem = int(os.environ.get("DFTHUB_MAXMEM", "6000"))
    mol = gto.M(
        atom=atom_block,
        basis=basis_dict,
        ecp=ecp_dict,
        charge=charge,
        spin=spin,
        verbose=4,
        max_memory=max_mem,
    )

    def build_and_solve(mol_obj, dm_guess=None, verify_stability: bool = False):
        ks = ks_cls(mol_obj)
        ks, _ = configure_cf22d_mf(ks, functional_path, options)
        ks, _ = _solve_stable_scf(ks, dm0=dm_guess, check_stability=verify_stability)
        return ks

    geom_opt_summary = None
    if options.optimize_geometry:
        print(f"=== Pre-optimizing geometry (BFGS) for {name} ===", flush=True)
        mf, mol, geom_opt_summary = optimize_geometry_bfgs(
            lambda m, dm: build_and_solve(m, dm, verify_stability=False),
            mol,
        )
        # Verify internal wavefunction stability at the relaxed geometry
        mf, stability_rounds = _solve_stable_scf(mf, dm0=mf.make_rdm1(), check_stability=True)
        opt_xyz_path = stage_dir / f"{name}.opt.xyz"
        opt_xyz_path.write_text(geom_opt_summary["optimized_xyz"])
    else:
        mf = ks_cls(mol)
        mf, _ = configure_cf22d_mf(mf, functional_path, options)
        mf, stability_rounds = _solve_stable_scf(mf, check_stability=True)

    chk_path = stage_dir / f"{name}.chk"
    atomic_checkpoint(mf, chk_path)

    e_tot = float(mf.e_tot)
    scf_summary = getattr(mf, "scf_summary", {}) or {}
    e_d3 = scf_summary.get("dispersion")
    e_d3_val = float(e_d3) if e_d3 is not None and math.isfinite(float(e_d3)) else None

    solvation_summary = extract_solvation_summary(mf, options)
    thermo_summary = None
    if options.calc_thermo:
        print(f"=== Running harmonic vibrational & thermochemical analysis for {name} ===", flush=True)
        thermo_summary = compute_thermochemistry(
            mf,
            options,
            mf_factory=lambda m, dm: build_and_solve(m, dm, verify_stability=False),
        )

    print(f"  E(total)      = {e_tot:20.10f} Hartree", flush=True)
    print("FINAL ENERGY (Hartree):", e_tot, flush=True)

    result: dict[str, Any] = {
        "name": name,
        "status": "ok",
        "natom": int(natom),
        "charge": int(charge),
        "multiplicity": int(spin + 1),
        "basis": options.basis,
        "grid_level": int(options.grid_level),
        "with_d3": bool(options.with_d3),
        "energy_hartree": e_tot,
        "e_d3_hartree": e_d3_val,
        "stability_rounds": int(stability_rounds),
        "solvation": solvation_summary,
        "geometry_optimization": geom_opt_summary,
        "thermochemistry": thermo_summary,
    }
    if solvation_summary:
        result["e_solvent_hartree"] = solvation_summary.get("e_solvent_hartree")
        result["e_cds_hartree"] = solvation_summary.get("e_cds_hartree")
        result["solvent_model"] = solvation_summary.get("model")
        result["solvent_name"] = solvation_summary.get("solvent")
        result["solvent_eps"] = solvation_summary.get("eps")
    if geom_opt_summary:
        result["opt_converged"] = geom_opt_summary.get("converged")
        result["opt_steps"] = geom_opt_summary.get("steps")
        result["initial_energy_hartree"] = geom_opt_summary.get("initial_energy_hartree")
        result["opt_energy_change_kcal_mol"] = geom_opt_summary.get("energy_change_kcal_mol")
        result["optimized_xyz"] = geom_opt_summary.get("optimized_xyz")
    if thermo_summary:
        result["zpe_hartree"] = thermo_summary.get("zpe_hartree")
        result["e_0k_hartree"] = thermo_summary.get("e_0k_hartree")
        result["u_tot_hartree"] = thermo_summary.get("u_tot_hartree")
        result["h_tot_hartree"] = thermo_summary.get("h_tot_hartree")
        result["g_tot_hartree"] = thermo_summary.get("g_tot_hartree")
        result["s_tot_cal_mol_k"] = thermo_summary.get("s_tot_cal_mol_k")
        result["ts_tot_hartree"] = thermo_summary.get("ts_tot_hartree")
        result["thermal_correction_g_hartree"] = thermo_summary.get("thermal_correction_g_hartree")
        result["standard_state_correction_hartree"] = thermo_summary.get("standard_state_correction_hartree")
        result["imaginary_count"] = thermo_summary.get("imaginary_count")
        result["imaginary_frequencies_cm1"] = thermo_summary.get("imaginary_frequencies_cm1")
        result["lowest_frequency_cm1"] = thermo_summary.get("lowest_frequency_cm1")
        result["frequencies_cm1"] = thermo_summary.get("frequencies_cm1")
    return result

