"""Shared PySCF basis and ECP preset resolution for DFThub jobs."""

from pathlib import Path


PROGRAM_DIR = Path(__file__).resolve().parent
BASIS_DATA_DIR = PROGRAM_DIR / "basis_data"

DEFAULT_BASIS = "def2-qzvp"
BASIS_PRESETS = {
    "sto-3g": ("sto-3g", None),
    "3-21g": ("3-21g", None),
    "6-31g": ("6-31g", None),
    "6-31g(d)": ("6-31g(d)", None),
    "6-31g(d,p)": ("6-31g(d,p)", None),
    "6-31+g(d,p)": ("6-31+g(d,p)", None),
    "6-31++g(d,p)": ("6-31++g(d,p)", None),
    "6-311g": ("6-311g", None),
    "6-311g(d,p)": ("6-311g(d,p)", None),
    "6-311+g(d,p)": ("6-311+g(d,p)", None),
    "6-311++g(2d,2p)": ("6-311++g(2d,2p)", None),
    "6-311++g(3df,3pd)": ("6-311++g(3df,3pd)", None),
    "def2-svp": ("def2-svp", None),
    "def2-tzvp": ("def2-tzvp", None),
    "def2-tzvpd": ("def2-tzvpd", None),
    "cc-pvdz": ("cc-pvdz", None),
    "aug-cc-pvdz": ("aug-cc-pvdz", None),
    "cc-pvtz": ("cc-pvtz", None),
    "aug-cc-pvtz": ("aug-cc-pvtz", None),
    "def2-qzvppd": ("def2-qzvppd", None),
    "def2-qzvp": ("def2-qzvp", None),
    "def2-qzvpp": ("def2-qzvpp", None),
    "aug-pc-3": ("aug-pc-3", None),
    "aug-pc-4": ("aug-pc-4", None),
    "aug-cc-pvqz": ("aug-cc-pvqz", None),
    "cc-pvqz": ("cc-pvqz", None),
    "cc-pv5z": ("cc-pv5z", None),
    "aug-cc-pv5z": ("aug-cc-pv5z", None),
    "pc-1": ("pc-1", None),
    "aug-pc-1": ("aug-pc-1", None),
    "pc-2": ("pc-2", None),
    "aug-pc-2": ("aug-pc-2", None),
    "pc-3": ("pc-3", None),
    "pc-4": ("pc-4", None),
    "aug-cc-pcv5z": (str(BASIS_DATA_DIR / "aug-cc-pCV5Z.nwchem"), None),
    "d-aug-cc-pv5z": (str(BASIS_DATA_DIR / "d-aug-cc-pV5Z.nwchem"), None),
    "aug-cc-pwcvqz-pp": (
        str(BASIS_DATA_DIR / "aug-cc-pwCVQZ-PP.nwchem"),
        str(BASIS_DATA_DIR / "aug-cc-pwCVQZ-PP.nwchem"),
    ),
    "lanl2dz-ecp": ("lanl2dz", "lanl2dz"),
    "def2-svp-ecp": ("def2-svp", "def2-svp"),
    "def2-tzvp-ecp": ("def2-tzvp", "def2-tzvp"),
    "def2-qzvppd-ecp": ("def2-qzvppd", "def2-qzvppd"),
    "def2-qzvp-ecp": ("def2-qzvp", "def2-qzvp"),
}
SUPPORTED_BASIS = tuple(BASIS_PRESETS)

CUSTOM_BASIS_ELEMENTS = {
    "aug-cc-pcv5z": frozenset(
        "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar".split()
    ),
    "d-aug-cc-pv5z": frozenset("H He B C N O F Ne Ar Kr".split()),
    "aug-cc-pwcvqz-pp": frozenset(
        "Cu Zn Ga Ge As Se Br Kr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe "
        "Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn".split()
    ),
}
CUSTOM_BASIS_FALLBACKS = {
    "aug-cc-pcv5z": {
        element: str(BASIS_DATA_DIR / "aug-cc-pV5Z.nwchem")
        for element in ("H", "He", "Li", "Be")
    },
}
DEF2_ALL_ELECTRON_PRESETS = frozenset(
    {
        "def2-svp",
        "def2-tzvp",
        "def2-tzvpd",
        "def2-qzvp",
        "def2-qzvpp",
        "def2-qzvppd",
    }
)
REQUIRE_ECP_PRESETS = frozenset({"aug-cc-pwcvqz-pp"})


def elements_from_atom_block(atom_block):
    """Return unique canonical PySCF element symbols from an XYZ atom block."""
    from pyscf.data.elements import _std_symbol

    elements = set()
    for line in atom_block.splitlines():
        fields = line.split()
        if not fields:
            continue
        label = fields[0]
        try:
            elements.add(_std_symbol(label))
        except Exception as exc:
            raise ValueError(f"Invalid element label: {label}") from exc
    if not elements:
        raise ValueError("No atoms found in the XYZ atom block")
    return tuple(sorted(elements))


def resolve_basis_sources(atom_block, preset=DEFAULT_BASIS):
    """Resolve per-element basis/ECP sources and reject unsafe def2 use."""
    from pyscf import gto

    if preset not in BASIS_PRESETS:
        raise ValueError(f"Unsupported basis preset: {preset}")

    basis_source, ecp_source = BASIS_PRESETS[preset]
    elements = elements_from_atom_block(atom_block)
    supported = CUSTOM_BASIS_ELEMENTS.get(preset)
    if supported is not None:
        unsupported = [element for element in elements if element not in supported]
        if unsupported:
            raise ValueError(
                f"Basis preset {preset} does not support: {', '.join(unsupported)}"
            )

    fallbacks = CUSTOM_BASIS_FALLBACKS.get(preset, {})
    basis_sources = {
        element: fallbacks.get(element, basis_source) for element in elements
    }

    if preset in DEF2_ALL_ELECTRON_PRESETS:
        ecp_required = [
            element for element in elements
            if gto.basis.load_ecp(basis_source, element)
        ]
        if ecp_required:
            raise ValueError(
                f"Basis preset {preset} requires an ECP for: "
                f"{', '.join(ecp_required)}. Choose a matching ECP preset."
            )

    ecp_sources = {}
    if ecp_source:
        for element in elements:
            if gto.basis.load_ecp(ecp_source, element):
                ecp_sources[element] = ecp_source
            elif preset in REQUIRE_ECP_PRESETS:
                raise ValueError(
                    f"Basis preset {preset} has no matching ECP for: {element}"
                )
    return basis_sources, ecp_sources or None


def load_basis_preset(atom_block, preset=DEFAULT_BASIS):
    """Load validated per-element PySCF basis and ECP data."""
    from pyscf import gto

    basis_sources, ecp_sources = resolve_basis_sources(atom_block, preset)
    try:
        basis = {
            element: gto.basis.load(source, element)
            for element, source in basis_sources.items()
        }
        ecp = None
        if ecp_sources:
            ecp = {
                element: gto.basis.load_ecp(source, element)
                for element, source in ecp_sources.items()
            }
    except Exception as exc:
        raise ValueError(f"Basis preset {preset} could not be loaded: {exc}") from exc
    return basis, ecp
