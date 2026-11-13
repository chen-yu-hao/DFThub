import { datasetKey } from "./mue";

const aliases: Record<string, string> = {
  "sr-mgm-be8": "sr-mgm-be9",
  "sr-tm-be15": "sr-tml-be11",
  pie3: "πie3",
  piie3: "πie3",
  ppa10: "πpa10",
  pipa10: "πpa10",
};

// The TMB11 reaction definitions identify complexation energies, isomerization
// energies and proton affinities, respectively. "built-in" describes a source,
// not a scientific category. Keep these corrections in display metadata so that
// historical weight files and optimization inputs retain their original bytes.
const categoryFallbacks: Record<string, string> = {
  ncce30: "NC",
  "πie3": "IE",
  "πpa10": "TC",
};
const scientificTypes = new Set(["BH", "EE", "TC", "NC", "IE"]);

export function datasetMetadataKey(name: string): string {
  const key = datasetKey(name);
  return aliases[key] || key;
}

export function datasetType(name: string, rawType = ""): string {
  const type = rawType.trim();
  if (scientificTypes.has(type.toUpperCase())) return type.toUpperCase();
  return categoryFallbacks[datasetMetadataKey(name)] || type;
}
