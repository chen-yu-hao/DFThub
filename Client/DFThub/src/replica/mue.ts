import nativeCF22D from "./cf22d-native.json";

export type DatasetMue = { name: string; key: string; value: number };
export type BaselineMetadata = { source?: string; parameter_sha256?: string };
export function datasetKey(name: string): string {
  return name.trim().replace(/_ref$/i, "").toLowerCase();
}

export function originalMueForRun(text: string, metadata: BaselineMetadata | null): Map<string, number> {
  const values = new Map<string, number>(Object.entries(nativeCF22D.datasets).map(([name, value]) => [datasetKey(name), value]));
  // Built-in datasets use the audited fixed values. Input is private and job-specific.
  values.delete("input");
  if (metadata?.source === "libxc-native-cf22d" && metadata.parameter_sha256 === nativeCF22D.parameter_sha256) {
    const input = parseDatasetMue(text).find((row) => row.key === "input");
    if (input) values.set("input", input.value);
  }
  return values;
}
/** Dataset errors only: optimizer losses and aggregate statistics are not MUE rows. */
export function parseDatasetMue(text: string): DatasetMue[] {
  const rows: DatasetMue[] = [];
  let valueIndex = 1;
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (/^-+\s*LOSS\s*-+$/i.test(line)) break;
    if (!line || /^-+/.test(line)) continue;
    const cells = line.split(/\t+|\s{2,}/).map((cell) => cell.trim());
    const headerIndex = cells.findIndex((cell) => /^(MUE|MAE|Mean unsigned error)$/i.test(cell));
    if (headerIndex > 0) { valueIndex = headerIndex; continue; }
    const name = cells[0];
    const key = datasetKey(name);
    if (!/^[\p{L}\p{N}_.+()\-]+$/u.test(name) ||
        /^(?:new[_ -]*)?total\b|^(?:new_)?total_|weighted.*mue|regularization|^(?:loss|mue|rmse|mae)$/i.test(name)) continue;
    const rawValue = cells[valueIndex];
    if (!rawValue || !/^[-+]?\d*\.?\d+(?:e[-+]?\d+)?$/i.test(rawValue)) continue;
    const value = Number(rawValue);
    if (Number.isFinite(value) && value >= 0) rows.push({ name: key === "input" ? "Input" : name, key, value });
  }
  return rows.sort((a, b) => Number(b.key === "input") - Number(a.key === "input"));
}
