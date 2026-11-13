"""Build the pinned DFT source, repair native dependencies, and label its wheel.

Every release wheel is rebuilt from the exact DFT commit declared below. No
previous release wheel is accepted as a substitute, and no PySCF scientific
source is changed by this packaging operation.
"""
import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

COMMIT = "e7cb735789293acf461f8ebbb4ac6a08b68ba5d6"
VERSION = "2.14.0+dfthub.e7cb7357"
REMOTE = "https://github.com/chen-yu-hao/pyscf.git"


def run(*args, **kwargs):
    subprocess.run(list(args), check=True, **kwargs)


def relabel(wheel, output, source):
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(root)
        old = next(root.glob('*.dist-info'))
        new = root / f'dfthub_pyscf_dft-{VERSION}.dist-info'
        old.rename(new)
        metadata = (new / 'METADATA').read_text()
        header, _, body = metadata.partition('\n\n')
        lines = []
        for line in header.splitlines():
            if line.startswith('Provides-Extra:') or line.startswith('Requires-Dist:') and 'extra ==' in line:
                continue
            if line.startswith('Name:'):
                line = 'Name: dfthub-pyscf-dft'
            if line.startswith('Version:'):
                line = 'Version: ' + VERSION
            if line.startswith('Requires-Python:'):
                line = 'Requires-Python: >=3.10,<3.13'
            lines.append(line)
        (new / 'METADATA').write_text('\n'.join(lines) + '\n\n' + body)
        (new / 'RECORD').unlink()
        # Match every included Python source byte against the fixed Git revision.
        for path in (root / 'pyscf').rglob('*.py'):
            source_path = source / path.relative_to(root)
            if not source_path.is_file() or source_path.read_bytes() != path.read_bytes():
                raise RuntimeError(f'Wheel source differs from pinned checkout: {path.relative_to(root)}')
        files = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in root.rglob('*') if p.is_file() and not any(x.endswith('.dist-info') for x in p.parts)}
        manifest = {'remote': REMOTE, 'branch': 'DFT', 'commit': COMMIT,
                    'pyscf_version': '2.14.0', 'libxc_version': '7.1.2', 'libcint_version': '6.2.0',
                    'xcfun_commit': 'a89b783497d4fe146b477ac7a053303ce4189e9a',
                    'source_wheel_sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(),
                    'files': files}
        (root / 'pyscf/dfthub-provenance.json').write_text(json.dumps(manifest, indent=2) + '\n')
        output.mkdir(parents=True, exist_ok=True)
        run(sys.executable, '-m', 'wheel', 'pack', str(root), '--dest-dir', str(output))


def canonical_macos_openmp(wheel):
    """LLVM and Homebrew can expose two different libomp paths with one basename.

    Select one OpenMP runtime before delocate vendors the dependency closure.
    Only Mach-O load paths are changed; scientific source stays untouched.
    """
    library = Path(os.environ['DFTHUB_MACOS_LIBOMP']).resolve()
    if not library.is_file():
        raise RuntimeError('DFTHUB_MACOS_LIBOMP must name the arm64 libomp.dylib')
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp) / 'wheel'
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(root)
        for path in root.rglob('*'):
            if path.is_file() and path.suffix in {'.so', '.dylib'}:
                output = subprocess.check_output(['otool', '-L', str(path)], text=True)
                for line in output.splitlines()[1:]:
                    dependency = line.strip().split(' (', 1)[0]
                    if dependency.endswith('/libomp.dylib') and dependency != str(library):
                        run('install_name_tool', '-change', dependency, str(library), str(path))
        run(sys.executable, '-m', 'wheel', 'pack', str(root), '--dest-dir', str(wheel.parent))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=Path('.build/pyscf'))
    parser.add_argument('--input-wheel', type=Path)
    parser.add_argument('--output', type=Path, default=Path('dist/engine'))
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    if not source.exists():
        run('git', 'clone', '--branch', 'DFT', REMOTE, str(source))
        run('git', 'checkout', COMMIT, cwd=source)
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
    if actual != COMMIT or subprocess.check_output(['git', 'diff', 'HEAD', '--'], cwd=source):
        raise RuntimeError('Use a clean checkout of the pinned DFT commit')
    output.mkdir(parents=True, exist_ok=True)
    run('git', 'archive', '--format=tar.gz', '--prefix=pyscf-dft/',
        f'--output={output / "pyscf-dft-e7cb7357-source.tar.gz"}', COMMIT, cwd=source)
    if args.input_wheel:
        raise RuntimeError('The v0.1.1 engine must be rebuilt from the latest DFT source; input wheels are disabled')
    else:
        raw = source / 'dist-dfthub-raw'
        env = dict(os.environ)
        # setup.py invokes the `cmake` executable by name. Prefer the CMake
        # installed in the active build environment over an older system copy
        # (the latter may not understand -S/-B).
        active_bin = Path(sys.prefix).resolve() / 'bin'
        # distutils may resolve `cmake` before applying the child environment
        # on older Python/setuptools combinations. A tiny absolute-path shim
        # makes the active build CMake unambiguous in that case.
        cmake = active_bin / 'cmake'
        if cmake.is_file():
            wrapper_dir = Path(tempfile.mkdtemp(prefix='dfthub-cmake-'))
            wrapper = wrapper_dir / 'cmake'
            wrapper.write_text(f'#!/usr/bin/env bash\nexec {cmake} "$@"\n')
            wrapper.chmod(0o755)
            env['PATH'] = str(wrapper_dir) + os.pathsep + str(active_bin) + os.pathsep + env.get('PATH', '')
        else:
            env['PATH'] = str(active_bin) + os.pathsep + env.get('PATH', '')
        env.setdefault('CMAKE_BUILD_PARALLEL_LEVEL', '2')
        configure = (env.get('CMAKE_CONFIGURE_ARGS', '') +
                     ' -DBUILD_MARCH_NATIVE=OFF -DLIBCINT_VERSION=v6.2.0').strip()
        # The validated HPC build has BLAS in the shared Mambaforge prefix,
        # which CMake cannot discover from an isolated build environment.
        local_blas = Path('/home/share/mambaforge/lib/libblas.so')
        if local_blas.is_file() and 'BLAS_LIBRARIES' not in configure:
            configure += f' -DBLAS_LIBRARIES={local_blas}'
        local_deps = source / 'pyscf/lib/deps/lib'
        if (local_deps / 'libcint.so').is_file() and 'BUILD_LIBCINT' not in configure:
            configure += ' -DBUILD_LIBCINT=OFF -DBUILD_LIBXC=OFF -DBUILD_XCFUN=OFF'
        env['CMAKE_CONFIGURE_ARGS'] = configure
        env['LD_LIBRARY_PATH'] = os.pathsep.join([
            str(local_deps), '/home/share/mambaforge/lib',
            '/home/share/mambaforge/envs/pyscf/lib/python3.12/site-packages/pyscf.libs',
            env.get('LD_LIBRARY_PATH', ''),
        ])
        # Some legacy distutils launchers mishandle the joined `-S/path`
        # spelling even when the right CMake is on PATH. Patch only the local
        # build checkout's setup.py to pass split arguments and an absolute
        # executable; restore the source file immediately afterward.
        setup_file = source / 'setup.py'
        original_setup = setup_file.read_text()
        cmake_executable = str((active_bin / 'cmake').resolve()) if (active_bin / 'cmake').is_file() else 'cmake'
        patched_setup = original_setup.replace(
            "cmd = ['cmake', f'-S{src_dir}', f'-B{self.build_temp}']",
            f"cmd = [{cmake_executable!r}, '-S', src_dir, '-B', self.build_temp]",
        )
        if patched_setup == original_setup:
            raise RuntimeError('Unable to patch PySCF setup.py CMake invocation')
        setup_file.write_text(patched_setup)
        try:
            run(sys.executable, '-m', 'pip', 'wheel', '.', '--no-deps', '--no-build-isolation', '-w', str(raw), cwd=source, env=env)
        finally:
            setup_file.write_text(original_setup)
        original = next(raw.glob('pyscf-*.whl'))
        repaired = source / 'dist-dfthub-repaired'
        if sys.platform == 'darwin':
            canonical_macos_openmp(original)
            run('delocate-wheel', '--require-archs=arm64', '-w', str(repaired), str(original))
        else:
            auditwheel = Path(sys.prefix).resolve() / 'bin' / 'auditwheel'
            run(str(auditwheel) if auditwheel.is_file() else 'auditwheel',
                'repair', '-w', str(repaired), str(original), env=env)
        wheel = next(repaired.glob('*.whl'))
    relabel(wheel, output, source)
    run(sys.executable, str(Path(__file__).with_name('add_native_notices.py')), str(output))


if __name__ == '__main__':
    main()
