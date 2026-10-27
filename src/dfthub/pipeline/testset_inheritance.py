"""Copy optional test inputs through a fork chain without copying results."""
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from pathlib import Path


def digest(source):
    if isinstance(source, bytes):
        return hashlib.sha256(source).hexdigest()
    result = hashlib.sha256()
    with Path(source).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, allow_nan=False) + '\n').encode()


def safe_name(name):
    if not isinstance(name, str) or not name or Path(name).name != name or name in ('.', '..'):
        raise ValueError('Invalid test-set filename')
    return name


def test_manifest(geometry, reference):
    geometry, reference = Path(geometry), Path(reference)
    path = geometry.parent / 'manifest.json'
    if path.is_file():
        value = json.loads(path.read_text())
        if not isinstance(value, dict) or value.get('geometry') != geometry.name or value.get('reference') != reference.name:
            raise ValueError('Test-set manifest does not match the supplied files')
        return value
    dataset = geometry.name.removeprefix('test_')
    for suffix in ('.tar.gz', '.tgz', '.zip'):
        if dataset.endswith(suffix):
            dataset = dataset[:-len(suffix)]
            break
    return {'geometry': safe_name(geometry.name), 'reference': safe_name(reference.name), 'dataset': dataset}


def install_missing(plan, dry_run=False):
    """Preflight every destination, then publish new files without replacing any."""
    missing = []
    for target, source in plan:
        target = Path(target)
        if target.exists():
            equal = digest(target) == digest(source)
            if not equal and target.name == 'manifest.json':
                expected = json.loads(source if isinstance(source, bytes) else Path(source).read_bytes())
                equal = json.loads(target.read_bytes()) == expected
            if not equal:
                raise ValueError(f'Existing test input differs; left unchanged: {target}')
        else:
            missing.append((target, source))
    if not dry_run:
        for target, source in missing:
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.' + target.name + '-', delete=False) as handle:
                temporary = Path(handle.name)
                if isinstance(source, bytes):
                    handle.write(source)
                else:
                    with Path(source).open('rb') as original:
                        shutil.copyfileobj(original, handle)
            try:
                # Link is atomic and fails if another worker created the file.
                try:
                    os.link(temporary, target)
                except FileExistsError:
                    if digest(target) != digest(source):
                        raise ValueError(f'Test input changed during inheritance: {target}')
            finally:
                temporary.unlink(missing_ok=True)
    return [str(target) for target, _ in missing]


def preserve_test_manifest(geometry, reference, destination):
    """Snapshots already contain the copied pair; also retain their manifest."""
    value = test_manifest(geometry, reference)
    return install_missing([(Path(destination) / 'manifest.json', encoded(value))])


def lineage(parent, work):
    root = (Path(work) / 'output').resolve()
    current, seen = Path(parent).resolve(), set()
    result = []
    while current not in seen:
        if root not in current.parents:
            raise ValueError('Test inheritance escaped the owning Job')
        seen.add(current); result.append(current)
        info = current / 'run.json'
        if not info.is_file():
            break
        run_id = json.loads(info.read_text()).get('parent')
        if not isinstance(run_id, str) or not re.fullmatch(r'weight_\d+(?:/fork-[1-9]\d*)*', run_id):
            raise ValueError('Invalid recorded parent for test inheritance')
        current = (root / run_id).resolve()
    else:
        raise ValueError('Circular test inheritance')
    return result


def inherit_test_set(parent, child, work, dry_run=False):
    """Inherit fixed evaluation descriptors, not parent MUE or SCF outputs."""
    parent, child, work = Path(parent), Path(child), Path(work)
    ancestors = lineage(parent, work)
    source_inputs = [path / 'input/test_set' for path in ancestors] + [work / 'input/test_set']
    test_root = next((path for path in source_inputs if (path / 'manifest.json').is_file()), None)
    if test_root is None:
        if (any(path.is_dir() and any(path.iterdir()) for path in source_inputs) or
                any((path / 'TEST_INPUT').exists() for path in ancestors)):
            raise ValueError('Test files exist but no ancestor has a valid manifest')
        return []
    manifest = json.loads((test_root / 'manifest.json').read_text())
    if not isinstance(manifest, dict):
        raise ValueError('Invalid test-set manifest')
    geometry = test_root / safe_name(manifest['geometry'])
    reference = test_root / safe_name(manifest['reference'])
    if not geometry.is_file() or not reference.is_file():
        raise ValueError('Inherited test archive/reference pair is incomplete')
    source = next((path for path in ancestors if all((path / name).is_file()
                  for name in ('TEST_INPUT', 'TEST_INPUT_ref', 'TestDescriptors.json'))), None)
    if source is None:
        raise ValueError('Test descriptors are missing in the recorded parent chain')
    if digest(source / 'TEST_INPUT_ref') != digest(reference):
        raise ValueError('Test descriptors and uploaded reference do not match')
    metadata = json.loads((source / 'TestDescriptors.json').read_text())
    if not isinstance(metadata, dict):
        raise ValueError('Invalid test descriptor metadata')
    basis_path = child / 'input/basis.txt'
    if basis_path.is_file() and metadata.get('basis') != basis_path.read_text().strip():
        raise ValueError('Inherited test basis differs from the fork basis')
    if metadata.get('dataset') and manifest.get('dataset') and metadata['dataset'] != manifest['dataset']:
        raise ValueError('Inherited test dataset names do not match')
    names = set()
    for row in (source / 'TEST_INPUT').read_text().splitlines():
        fields = row.split()
        if not fields:
            continue
        values = [float(value) for value in fields[1:]]
        if fields[0] in names or len(values) != 62 or not all(map(math.isfinite, values)):
            raise ValueError('Invalid inherited test descriptor row')
        names.add(fields[0])
    if not names or metadata.get('count', len(names)) != len(names):
        raise ValueError('Inherited test descriptor count does not match')
    target_test = child / 'input/test_set'
    plan = [(target_test / geometry.name, geometry), (target_test / reference.name, reference),
            (target_test / 'manifest.json', encoded(manifest))]
    plan += [(child / name, source / name) for name in ('TEST_INPUT', 'TEST_INPUT_ref', 'TestDescriptors.json')]
    return install_missing(plan, dry_run=dry_run)


def ensure_fork_test_set(output):
    """Worker-start compatibility for API processes loaded before this fix."""
    output = Path(output).resolve()
    if not re.fullmatch(r'fork-[1-9]\d*', output.name):
        return []
    info = output / 'run.json'
    if not info.is_file():
        return []
    roots = [path for path in output.parents if path.name == 'output']
    if not roots:
        raise ValueError('Fork is not inside a Job output directory')
    root = roots[0]
    parent_id = json.loads(info.read_text()).get('parent')
    if not isinstance(parent_id, str) or not re.fullmatch(r'weight_\d+(?:/fork-[1-9]\d*)*', parent_id):
        raise ValueError('Invalid fork parent')
    return inherit_test_set(root / parent_id, output, root.parent)
