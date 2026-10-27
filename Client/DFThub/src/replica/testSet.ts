import nativeCF22D from "./cf22d-native.json";
import { parseDatasetMue } from "./mue";

export type WorkspaceTestSet = {
  value: number | null;
  original: number | null;
  points: number | null;
  complete: boolean;
};

function optionalJson(text: string | undefined) {
  try { return text ? JSON.parse(text) : null; }
  catch { return null; }
}

function mue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}

export function workspaceTestSet(files: Record<string, any>): WorkspaceTestSet | null {
  const result = optionalJson(files["TestMue.json"]);
  const baseline = optionalJson(files["TestOriginalMue.meta.json"]);
  const names: string[] = files._files || [];
  if (!files.TestMue && !files.TestOriginalMue && !result &&
      !["TEST_INPUT", "TEST_INPUT_ref", "TestDescriptors.json"].some((name) => names.includes(name))) return null;
  const completeResult = result?.complete !== false;
  const value = completeResult ? parseDatasetMue(files.TestMue || "").find((row) => row.key === "test_input")?.value ?? mue(result?.targetMue) : null;
  const verifiedBaseline = baseline?.source === "libxc-native-cf22d" && baseline.parameter_sha256 === nativeCF22D.parameter_sha256;
  const original = verifiedBaseline ? parseDatasetMue(files.TestOriginalMue || "").find((row) => row.key === "test_input")?.value ?? mue(result?.originalMue) : null;
  const count = result?.count ?? (Array.isArray(result?.targetRows) ? result.targetRows.length : null);
  return { value, original, complete: completeResult && value !== null,
    points: Number.isInteger(count) && count > 0 ? count : null };
}
