import type { DatasetMue } from "./mue";
import { datasetMetadataKey, datasetType } from "./datasetMetadata";

export type Comparison = DatasetMue & { original: number | null; delta: number | null; type: string; points: number | null };
export type TypeComparison = { key: string; name: string; original: number; value: number; points: number | null; datasets: number };
export const typeNames: Record<string, string> = {
  Input: "Your data set", BH: "Barrier heights", EE: "Excitation energies", TC: "Thermochemistry",
  NC: "Noncovalent interactions", IE: "Isomerization energies", Other: "Other / unclassified",
};

export function compareDatasets(rows: DatasetMue[], original: Map<string, number>, weights: string, counts: Record<string, number>): Comparison[] {
  const lines = weights.trim().split(/\r?\n/);
  const headers = (lines.shift() || "").split("\t").map((value) => value.trim().toLowerCase());
  const typeIndex = headers.indexOf("type");
  const sourceIndex = headers.indexOf("source");
  const countIndex = headers.indexOf("number");
  const metadata = new Map<string, { type: string; points: number | null }>();
  for (const line of lines) {
    const cells = line.split("\t");
    const key = sourceIndex >= 0 && cells[sourceIndex]?.trim().toLowerCase() === "uploaded" ? "input" : datasetMetadataKey(cells[0] || "");
    const rawPoints = countIndex >= 0 ? cells[countIndex]?.trim() : "";
    const points = rawPoints ? Number(rawPoints) : NaN;
    const rawType = datasetType(cells[0] || "", typeIndex >= 0 ? cells[typeIndex] : "");
    metadata.set(key, { type: typeNames[rawType] ? rawType : "Other", points: Number.isInteger(points) && points > 0 ? points : null });
  }
  return rows.map((row) => {
    const canonicalKey = datasetMetadataKey(row.key);
    const meta = metadata.get(canonicalKey);
    const originalValue = original.get(row.key) ?? original.get(canonicalKey);
    const baseline = originalValue !== undefined && Number.isFinite(originalValue) && originalValue >= 0 ? originalValue : null;
    const actualCount = counts[row.key] ?? counts[canonicalKey];
    return { ...row, original: baseline, delta: baseline === null ? null : row.value - baseline,
      type: row.key === "input" ? "Input" : meta?.type || datasetType(row.key) || "Other",
      points: Number.isInteger(actualCount) && actualCount > 0 ? actualCount : meta?.points || null };
  });
}

export function overallByType(rows: Comparison[]): TypeComparison[] {
  const groups = new Map<string, TypeComparison>();
  for (const row of rows) {
    if (row.type === "Input" && row.original !== null) {
      groups.set("Input", { key: "Input", name: typeNames.Input, original: row.original, value: row.value, points: row.points, datasets: 1 });
      continue;
    }
    if (row.original === null || row.points === null) continue;
    const group = groups.get(row.type) || { key: row.type, name: typeNames[row.type] || row.type, original: 0, value: 0, points: 0, datasets: 0 };
    group.original += row.original * row.points;
    group.value += row.value * row.points;
    group.points += row.points;
    group.datasets++;
    groups.set(row.type, group);
  }
  const order = Object.keys(typeNames);
  return [...groups.values()].map((group) => group.key === "Input" ? group : ({ ...group, original: group.original / group.points!, value: group.value / group.points! }))
    .sort((a, b) => order.indexOf(a.key) - order.indexOf(b.key));
}

export function overviewStats(rows: Comparison[]) {
  const reference = rows.filter((row) => row.key !== "input" && row.original !== null);
  const changed = reference.map((row) => ({ ...row, delta: row.delta! }));
  const worse = changed.filter((row) => row.delta > 1e-10).sort((a, b) => b.delta - a.delta);
  const improved = changed.filter((row) => row.delta < -1e-10).sort((a, b) => a.delta - b.delta);
  return {
    input: rows.find((row) => row.key === "input") || null, references: reference.length,
    totalReferences: rows.filter((row) => row.key !== "input").length,
    improved, worse, unchanged: reference.length - improved.length - worse.length,
    beforeAccurate: reference.filter((row) => row.original! < 1).length,
    afterAccurate: reference.filter((row) => row.value < 1).length,
  };
}

export function reportedTotalMue(text: string): number | null {
  const match = text.match(/^(?:new_)?total[_\s]*mue\s*[:=\t]\s*([-+]?\d*\.?\d+(?:e[-+]?\d+)?)\s*$/im);
  return match && Number.isFinite(Number(match[1])) && Number(match[1]) >= 0 ? Number(match[1]) : null;
}
