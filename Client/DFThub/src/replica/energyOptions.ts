export type SolventModelId = "none" | "ief-pcm" | "c-pcm" | "smd" | "cosmo" | "ssvpe" | "ddcosmo";
export type VibModelId = "qrrho-grimme" | "qrrho-full" | "rrho";
export type PressureUnit = "atm" | "bar" | "kPa" | "Pa";

export type SolventPreset = {
  id: string;
  name: string;
  eps: number;
  category: string;
  common?: boolean;
};

export type EnergyTaskOptionsPayload = {
  basis?: string;
  grid_level: number;
  with_d3: boolean;
  solvent_model: SolventModelId;
  solvent_name: string;
  solvent_eps: number | null;
  optimize_geometry: boolean;
  calc_thermo: boolean;
  temperature_k: number;
  pressure_pa: number;
  vib_model: VibModelId;
  qrrho_freq0: number;
  freq_scale: number;
  solution_standard_state: boolean;
};

export const HARTREE_TO_KCAL = 627.509474063;
export const BOLTZMANN_SI = 1.380649e-23;
export const AVOGADRO_SI = 6.02214076e23;
export const HARTREE_TO_J = 4.3597447222071e-18;
export const R_HARTREE_PER_K = BOLTZMANN_SI / HARTREE_TO_J;

export const SOLVENT_MODEL_OPTIONS: {
  id: SolventModelId;
  label: string;
  shortLabel: string;
  badge: string;
  description: string;
  supportsCustomEps: boolean;
}[] = [
  {
    id: "none",
    label: "Gas phase (Vacuum)",
    shortLabel: "Gas phase",
    badge: "Vacuum",
    description: "No implicit solvent reaction field; evaluates isolated gas-phase electronic structure.",
    supportsCustomEps: false,
  },
  {
    id: "smd",
    label: "SMD (Universal Solvation)",
    shortLabel: "SMD",
    badge: "Electrostatic + CDS",
    description: "Truhlar–Cramer universal continuum model combining IEF-PCM electrostatics with non-electrostatic cavitation, dispersion, and solvent-structure (CDS) free energy.",
    supportsCustomEps: true,
  },
  {
    id: "ief-pcm",
    label: "IEF-PCM",
    shortLabel: "IEF-PCM",
    badge: "Integral Equation PCM",
    description: "Integral Equation Formalism Polarizable Continuum Model with smooth analytical nuclear gradients and Hessian.",
    supportsCustomEps: true,
  },
  {
    id: "c-pcm",
    label: "C-PCM",
    shortLabel: "C-PCM",
    badge: "Conductor-like PCM",
    description: "Conductor-like polarizable continuum boundary condition; fast and reliable for moderate-to-high dielectric solvents.",
    supportsCustomEps: true,
  },
  {
    id: "cosmo",
    label: "COSMO",
    shortLabel: "COSMO",
    badge: "Conductor Screening",
    description: "COnductor-like Screening MOdel with scaled conductor screening factor f(ε) = (ε − 1)/(ε + 0.5).",
    supportsCustomEps: true,
  },
  {
    id: "ssvpe",
    label: "SS(V)PE",
    shortLabel: "SS(V)PE",
    badge: "Surface & Volume",
    description: "Surface and Simulation of Volume Polarization for Electrostatics continuum formulation.",
    supportsCustomEps: true,
  },
  {
    id: "ddcosmo",
    label: "ddCOSMO",
    shortLabel: "ddCOSMO",
    badge: "Domain Decomposition",
    description: "Grid-free domain-decomposition COSMO solver with linear scaling across molecular cages and larger systems.",
    supportsCustomEps: true,
  },
];

export const VIB_MODEL_OPTIONS: {
  id: VibModelId;
  label: string;
  shortLabel: string;
  description: string;
}[] = [
  {
    id: "qrrho-grimme",
    label: "Quasi-RRHO (Grimme S damping)",
    shortLabel: "Quasi-RRHO (Grimme)",
    description: "Interpolates low-frequency vibrational entropy toward a free-rotor limit below ω₀ to avoid artificial entropy spikes.",
  },
  {
    id: "qrrho-full",
    label: "Quasi-RRHO (Grimme S + Head-Gordon H)",
    shortLabel: "Quasi-RRHO (S + H)",
    description: "Applies both Grimme free-rotor entropy damping and Head-Gordon thermal internal energy/enthalpy damping below ω₀.",
  },
  {
    id: "rrho",
    label: "Standard RRHO (Harmonic)",
    shortLabel: "Standard RRHO",
    description: "Undamped rigid-rotor harmonic-oscillator partition function across all positive vibrational modes.",
  },
];

export const TEMPERATURE_PRESETS = [
  { label: "0 °C (273.15 K)", value: 273.15 },
  { label: "25 °C (298.15 K)", value: 298.15 },
  { label: "37 °C (310.15 K)", value: 310.15 },
  { label: "100 °C (373.15 K)", value: 373.15 },
];

export const DEFAULT_COMMON_SOLVENTS: SolventPreset[] = [
  { id: "water", name: "Water (H2O)", eps: 78.3553, category: "Polar protic", common: true },
  { id: "acetonitrile", name: "Acetonitrile (MeCN)", eps: 35.688, category: "Polar aprotic", common: true },
  { id: "dimethylsulfoxide", name: "Dimethyl sulfoxide (DMSO)", eps: 46.826, category: "Polar aprotic", common: true },
  { id: "methanol", name: "Methanol (MeOH)", eps: 32.613, category: "Polar protic", common: true },
  { id: "ethanol", name: "Ethanol (EtOH)", eps: 24.852, category: "Polar protic", common: true },
  { id: "n,n-dimethylformamide", name: "N,N-Dimethylformamide (DMF)", eps: 37.219, category: "Polar aprotic", common: true },
  { id: "tetrahydrofuran", name: "Tetrahydrofuran (THF)", eps: 7.4257, category: "Ethereal", common: true },
  { id: "dichloromethane", name: "Dichloromethane (DCM)", eps: 8.93, category: "Halogenated", common: true },
  { id: "chloroform", name: "Chloroform (CHCl3)", eps: 4.7113, category: "Halogenated", common: true },
  { id: "acetone", name: "Acetone", eps: 20.493, category: "Polar aprotic", common: true },
  { id: "toluene", name: "Toluene", eps: 2.3741, category: "Aromatic", common: true },
  { id: "benzene", name: "Benzene", eps: 2.2706, category: "Aromatic", common: true },
  { id: "chlorobenzene", name: "Chlorobenzene", eps: 5.6968, category: "Aromatic", common: true },
  { id: "1,4-dioxane", name: "1,4-Dioxane", eps: 2.2099, category: "Ethereal", common: true },
  { id: "diethylether", name: "Diethyl ether (Et2O)", eps: 4.24, category: "Ethereal", common: true },
  { id: "ethylacetate", name: "Ethyl acetate (EtOAc)", eps: 5.9867, category: "Ester", common: true },
  { id: "n-hexane", name: "n-Hexane", eps: 1.8819, category: "Nonpolar alkane", common: true },
  { id: "cyclohexane", name: "Cyclohexane", eps: 2.0165, category: "Nonpolar alkane", common: true },
  { id: "n-heptane", name: "n-Heptane", eps: 1.9113, category: "Nonpolar alkane", common: true },
  { id: "carbon tetrachloride", name: "Carbon tetrachloride (CCl4)", eps: 2.228, category: "Halogenated", common: true },
  { id: "1,2-dichloroethane", name: "1,2-Dichloroethane (DCE)", eps: 10.125, category: "Halogenated", common: true },
  { id: "2-propanol", name: "2-Propanol (iPrOH)", eps: 19.264, category: "Polar protic", common: true },
  { id: "1-octanol", name: "1-Octanol", eps: 9.8629, category: "Polar protic", common: true },
  { id: "acetic acid", name: "Acetic acid (AcOH)", eps: 6.2528, category: "Polar protic", common: true },
  { id: "pyridine", name: "Pyridine", eps: 12.978, category: "Aromatic", common: true },
  { id: "nitromethane", name: "Nitromethane", eps: 36.562, category: "Polar aprotic", common: true },
];

export function pressureToPa(value: number, unit: PressureUnit): number {
  if (!Number.isFinite(value) || value <= 0) return 101325.0;
  switch (unit) {
    case "atm":
      return value * 101325.0;
    case "bar":
      return value * 100000.0;
    case "kPa":
      return value * 1000.0;
    case "Pa":
    default:
      return value;
  }
}

export function solutionStandardStateCorrectionKcal(temperatureK: number, pressurePa: number): number {
  if (!Number.isFinite(temperatureK) || temperatureK <= 0 || !Number.isFinite(pressurePa) || pressurePa <= 0) {
    return 0;
  }
  const ratio = (1000.0 * BOLTZMANN_SI * AVOGADRO_SI * temperatureK) / pressurePa;
  if (ratio <= 0) return 0;
  return R_HARTREE_PER_K * temperatureK * Math.log(ratio) * HARTREE_TO_KCAL;
}

export function formatSolventBadge(options?: any, solvation?: any): string | null {
  const model = (solvation?.model || options?.solvent_model || "none").toLowerCase();
  if (!model || model === "none") return null;
  const modelOption = SOLVENT_MODEL_OPTIONS.find((item) => item.id === model);
  const label = solvation?.method_label || modelOption?.shortLabel || model.toUpperCase();
  const solvent = solvation?.solvent || (options?.solvent_eps != null ? `ε=${options.solvent_eps}` : options?.solvent_name || "water");
  return `${label} · ${solvent}`;
}
