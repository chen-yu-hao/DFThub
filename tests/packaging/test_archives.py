import io
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile
from dfthub.archives import extract_geometry_archive


class GeometryArchives(unittest.TestCase):
    def test_tar_and_zip_extract_without_new_tarfile_filter_api(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for suffix in ('tgz', 'zip'):
                path = root / ('input.' + suffix)
                if suffix == 'zip':
                    with zipfile.ZipFile(path, 'w') as archive:
                        archive.writestr('geometry/H2.xyz', b'geometry')
                else:
                    with tarfile.open(path, 'w:gz') as archive:
                        info = tarfile.TarInfo('geometry/H2.xyz')
                        info.size = 8
                        archive.addfile(info, io.BytesIO(b'geometry'))
                output = root / suffix
                extract_geometry_archive(path, output)
                self.assertEqual((output / 'geometry/H2.xyz').read_bytes(), b'geometry')

    def test_tar_traversal_and_links_are_rejected_before_writing(self):
        for name, kind in [('../escape', tarfile.REGTYPE), ('/absolute', tarfile.REGTYPE),
                           ('link', tarfile.SYMTYPE), ('device', tarfile.CHRTYPE)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                with tarfile.open(root/'input.tgz', 'w:gz') as archive:
                    info = tarfile.TarInfo(name)
                    info.type = kind
                    info.linkname = '../outside'
                    archive.addfile(info)
                with self.assertRaises(ValueError):
                    extract_geometry_archive(root/'input.tgz', root/'out')
                self.assertEqual(list((root/'out').iterdir()), [])

    def test_zip_traversal_and_case_collisions_are_rejected(self):
        for names in (['../escape'], ['H2.xyz', 'h2.xyz']):
            with self.subTest(names=names), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                with zipfile.ZipFile(root/'input.zip', 'w') as archive:
                    for name in names:
                        archive.writestr(name, 'geometry')
                with self.assertRaises(ValueError):
                    extract_geometry_archive(root/'input.zip', root/'out')
