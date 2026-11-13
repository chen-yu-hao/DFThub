import hashlib
from pathlib import Path
import tempfile
import unittest

from dfthub.functional.parameters import (
    CF22DParameters, CX_LABELS, CY_LABELS, CZ_LABELS, DEFAULT_HF, ORIGINAL, ParametersError,
    format_parameters, load_parameters, parse_parameters, parse_vector, read_parameters, read_vector,
)

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "Parameters"
OPTIMIZER_START = ROOT / "src/dfthub/resources/optimizer/params.txt"


def legacy_generate_parameters(values):
    """The pre-refactor opt_demo.generate_parameters formatting, kept as the reference."""
    groups = [(0, 0, 6), (0, 1, 5), (0, 2, 4), (0, 3, 3), (1, 0, 5), (1, 1, 4), (1, 2, 3), (2, 0, 4), (2, 1, 3), (3, 0, 3)]
    lines = ["Parameters"]
    idx = 0
    for n, j, count in groups:
        for k in range(count):
            lines.append(f"Cx({n},{j},{k}) = {float(values[idx]):.16e}")
            idx += 1
    lines.append(f"HF% = {float(values[58]) * 100:.16e}")
    for i in range(9):
        lines.append(f"Cy({i}) = {float(values[40 + i]):.16e}")
    for i in range(9):
        lines.append(f"Cz({i}) = {float(values[49 + i]):.16e}")
    return "\n".join(lines) + "\n"


def sample_vector():
    return [0.01 * (i + 1) * (-1) ** i for i in range(58)] + [0.4321]


class ParametersFileTests(unittest.TestCase):
    def test_example_file(self):
        params = read_parameters(EXAMPLE)
        self.assertAlmostEqual(params.cx[0], -1.8691297464873982e-01, places=17)
        self.assertAlmostEqual(params.cz[-1], 2.1755410885538375e+01, places=14)
        self.assertAlmostEqual(params.hf, 0.58103542452473214, places=15)

    def test_key_rules(self):
        text = format_parameters(CF22DParameters.from_vector(sample_vector()))
        shuffled = "\n".join(reversed(text.splitlines()))
        messy = (shuffled.replace("Cx(0,0,0)", " cx( 0 , 0 , 0 ) ")
                 .replace("e-01", "D-01").replace("Cy(3)", "CY(3)")
                 + "\n# a comment\nunknown = 3\nCz(8) = 7.5  # repeated key keeps the last value\n")
        params = parse_parameters(messy)
        expected = sample_vector()
        expected[57] = 7.5
        self.assertEqual(params.vector(), expected)

    def test_hf_and_hf_percent_agree(self):
        base = "\n".join(f"{label} = 0.1" for label in CX_LABELS + CY_LABELS + CZ_LABELS)
        self.assertAlmostEqual(parse_parameters(base + "\nHF% = 42.5").hf, 0.425, places=15)
        self.assertEqual(parse_parameters(base + "\nHF = 0.425").hf, 0.425)

    def test_missing_values_are_reported(self):
        text = format_parameters(ORIGINAL)
        without = "\n".join(line for line in text.splitlines() if not line.startswith(("Cy(4)", "HF%")))
        with self.assertRaises(ParametersError) as caught:
            parse_parameters(without, "demo")
        self.assertIn("Cy(4)", str(caught.exception))
        self.assertIn("HF% or HF", str(caught.exception))
        self.assertIsInstance(caught.exception, ValueError)

    def test_unparsable_value(self):
        with self.assertRaises(ParametersError) as caught:
            parse_parameters("Cx(0,0,0) = abc")
        self.assertIn("line 1", str(caught.exception))

    def test_missing_file(self):
        with self.assertRaises(ParametersError):
            read_parameters(ROOT / "does-not-exist")

    def test_round_trip(self):
        params = CF22DParameters.from_vector(sample_vector())
        self.assertEqual(parse_parameters(format_parameters(params)).vector(), params.vector())


class VectorTests(unittest.TestCase):
    def test_output_matches_previous_generator(self):
        values = sample_vector()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "NEW-params.txt"
            path.write_text("\n".join(f"{v:.17g}" for v in values) + "\n")
            self.assertEqual(format_parameters(read_vector(path)), legacy_generate_parameters(values))

    def test_whitespace_and_length(self):
        params = parse_vector(" ".join(map(str, sample_vector())))
        self.assertEqual(params.hf, 0.4321)
        with self.assertRaises(ParametersError):
            parse_vector(" ".join(map(str, sample_vector()[:58])))
        self.assertEqual(parse_vector(" ".join(map(str, sample_vector()[:58])), default_hf=DEFAULT_HF).hf, DEFAULT_HF)

    def test_optimizer_start_is_original_set(self):
        params = read_vector(OPTIMIZER_START, default_hf=DEFAULT_HF)
        for ours, embedded in zip(params.vector(), ORIGINAL.vector()):
            self.assertAlmostEqual(ours, embedded, delta=1e-14)

    def test_load_detects_format(self):
        with tempfile.TemporaryDirectory() as temporary:
            vector = Path(temporary) / "params.txt"
            vector.write_text("\t".join(map(str, sample_vector())))
            self.assertEqual(load_parameters(vector).vector(), sample_vector())
        self.assertEqual(load_parameters(EXAMPLE), read_parameters(EXAMPLE))


class LibXCMappingTests(unittest.TestCase):
    def test_libxc_vectors(self):
        params = CF22DParameters.from_vector(sample_vector())
        x, c = params.libxc_x_params(), params.libxc_c_params()
        self.assertEqual(len(x), 41)
        self.assertEqual(x[40], params.hf)
        self.assertEqual(len(c), 24)
        self.assertEqual(c[:9], list(params.cy))
        self.assertEqual(c[12:21], list(params.cz))
        self.assertEqual(c[9:12] + c[21:], [0.0] * 6)
        named = params.libxc_x_named()
        self.assertEqual(list(named)[:3], ["_CC000", "_CC001", "_CC002"])
        self.assertEqual(list(named)[-2:], ["_CC302", "_ax"])
        self.assertEqual(params.libxc_c_named()["_b0"], params.cz[0])

    def test_sha256_matches_pipeline_convention(self):
        import numpy as np
        params = read_parameters(EXAMPLE)
        expected = hashlib.sha256(np.asarray(params.vector(), dtype="<f8").tobytes()).hexdigest()
        self.assertEqual(params.sha256(), expected)

    def test_rejects_non_finite(self):
        values = sample_vector()
        values[3] = float("nan")
        with self.assertRaises(ParametersError):
            CF22DParameters.from_vector(values)


if __name__ == "__main__":
    unittest.main()
