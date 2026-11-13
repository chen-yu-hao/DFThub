from pathlib import Path
import tarfile
import tempfile
import types
import unittest

from dfthub.functional import gaussian
from dfthub.functional.parameters import CF22DParameters, CX_LABELS

CX_LINES = "\n".join(f"        {label.upper()} = 0.0D0" for label in CX_LABELS)
CY_LINES = "\n".join(f"        CY({n}) = 0.0d0" for n in range(9))

UTILNZ = f"""\
*Deck N12xP
      Subroutine N12xP(IFunc,CX)
C     IFunc.eq.6 in a comment is ignored
      If(IFunc.eq.5) then
{CX_LINES.replace('0.0D0', '5.0D0')}
      Else If(IFunc.eq.6) then
{CX_LINES}
      Else
        Call Abort
      EndIf
      Return
      End
*Deck Other
      If(IFunc.eq.6) then
        CX(0,0,0) = 9.0D0
      EndIf
"""

UTILAM = f"""\
      If(IFunc.eq.36) then
{CY_LINES}
      ElseIf(IFunc.eq.37) then
{CY_LINES}
      EndIf
      If(IMOpt.eq.-25) then
        IMHF = 440000
      ElseIf(IMOpt.eq.-26) then
        IMHF = 000000
      EndIf
"""


def sample():
    return CF22DParameters.from_vector([0.5 + i for i in range(58)] + [0.4321014])


def make_tree(root: Path, nested: bool = False) -> Path:
    top = root / "g16"
    src = top / "g16" if nested else top
    (src / "bsd").mkdir(parents=True)
    (src / "bsd/g16.profile").write_text("# profile\n")
    (src / "utilnz.F").write_text(UTILNZ)
    (src / "utilam.F").write_text(UTILAM)
    return top


class FortranFormatTests(unittest.TestCase):
    def test_values(self):
        cx, cy, cz, imhf = gaussian.fortran_values(sample())
        self.assertEqual(cx[0], "5.00000000000000D-01")
        self.assertEqual(cy[0], "4.05000000000000d+01")
        self.assertEqual(cz[8], "5.75000000000000d+01")
        self.assertEqual(imhf, "432101")
        self.assertEqual(len(cx), 40)


class PatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.top = make_tree(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def test_dry_run_writes_nothing(self):
        report = gaussian.patch_sources(self.top, sample(), dry_run=True)
        self.assertEqual((self.top / "utilnz.F").read_text(), UTILNZ)
        self.assertEqual((self.top / "utilam.F").read_text(), UTILAM)
        self.assertEqual(report.changed, 59)
        self.assertFalse(report.written)
        self.assertEqual(report.cx_lines, (46, 85))

    def test_patch_only_target_blocks(self):
        report = gaussian.patch_sources(self.top, sample())
        nz = (self.top / "utilnz.F").read_text().splitlines()
        am = (self.top / "utilam.F").read_text().splitlines()
        self.assertTrue(report.written)
        self.assertEqual(nz[report.cx_lines[0] - 1], "        CX(0,0,0) = 5.00000000000000D-01")
        self.assertEqual(nz[report.cx_lines[1] - 1], "        CX(3,0,2) = 3.95000000000000D+01")
        self.assertIn("CX(0,0,0) = 5.0D0", "\n".join(nz))   # IFunc.eq.5 block untouched
        self.assertIn("CX(0,0,0) = 9.0D0", "\n".join(nz))   # other deck untouched
        self.assertEqual(am[1], "        CY(0) = 4.05000000000000d+01")
        self.assertEqual(am[11], "        CY(0) = 4.95000000000000d+01")
        self.assertEqual(am[22], "        IMHF = 432101")
        self.assertEqual(am[24], "        IMHF = 000000")
        again = gaussian.patch_sources(self.top, sample(), dry_run=True)
        self.assertEqual(again.changed, 0)

    def test_ambiguous_block_leaves_sources_unchanged(self):
        (self.top / "utilam.F").write_text(UTILAM + UTILAM)
        with self.assertRaises(gaussian.GaussianBuildError) as caught:
            gaussian.patch_sources(self.top, sample())
        self.assertIn("IFUNC.EQ.36", str(caught.exception))
        self.assertEqual((self.top / "utilnz.F").read_text(), UTILNZ)

    def test_missing_files(self):
        (self.top / "utilam.F").unlink()
        with self.assertRaises(gaussian.GaussianBuildError):
            gaussian.patch_sources(self.top, sample())


class SourceTreeTests(unittest.TestCase):
    def test_layouts_and_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            top = make_tree(root / "plain")
            self.assertEqual(gaussian.detect_source_root(top), top)
            nested = make_tree(root / "nested", nested=True)
            self.assertEqual(gaussian.detect_source_root(nested), nested / "g16")

            archive = root / "work" / "g16.tar.gz"
            archive.parent.mkdir()
            with tarfile.open(archive, "w:gz") as tar:
                tar.add(top, arcname="g16")
            extracted = gaussian.prepare_source(root / "work" / "g16", [root / "work" / "missing.tgz", archive])
            self.assertTrue((extracted / "utilnz.F").is_file())
            with self.assertRaises(gaussian.GaussianBuildError):
                gaussian.prepare_source(root / "none" / "g16", [root / "none.tgz"])

    def test_build_and_finalize(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            top = make_tree(root)
            calls = []

            def runner(command, **kwargs):
                calls.append((command, kwargs))
                return types.SimpleNamespace(returncode=0)

            gaussian.build(top, runner=runner)
            command, kwargs = calls[0]
            self.assertIn(f'g16root="{root.resolve()}"', command)
            self.assertIn("./bsd/bldg16", command)
            self.assertEqual(kwargs["cwd"], top.resolve())
            with self.assertRaises(gaussian.GaussianBuildError):
                gaussian.build(top, runner=lambda *a, **k: types.SimpleNamespace(returncode=2))
            (root / "g16-opt").mkdir()
            (root / "g16-opt" / "stale").write_text("old")
            final = gaussian.finalize(top, root / "g16-opt")
            self.assertTrue((final / "utilnz.F").is_file())
            self.assertFalse((final / "stale").exists())
            self.assertFalse(top.exists())

    def test_source_root_must_be_named_g16(self):
        with tempfile.TemporaryDirectory() as temporary:
            other = Path(temporary) / "gaussian"
            other.mkdir()
            with self.assertRaises(gaussian.GaussianBuildError):
                gaussian.build(other, runner=lambda *a, **k: types.SimpleNamespace(returncode=0))


class InputTemplateTests(unittest.TestCase):
    def test_route(self):
        text = gaussian.render_input(sample())
        self.assertIn("#P MN15/def2QZVP\nEmpiricalDispersion=GD3 IOp(3/174=1000000,3/175=-1,3/176=1530000)\n", text)
        self.assertTrue(all(len(line) <= 80 for line in text.splitlines()))
        no_d3 = gaussian.render_input(sample(), keyword="CF22D", basis="6-31G(d)", with_d3=False)
        self.assertIn("#P CF22D/6-31G(d)\n\n", no_d3)
        self.assertNotIn("GD3", no_d3)


if __name__ == "__main__":
    unittest.main()
