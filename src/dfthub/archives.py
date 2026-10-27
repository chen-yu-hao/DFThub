"""Safe geometry extraction on all supported Python patch versions."""
from pathlib import Path, PurePosixPath
import shutil
import stat
import tarfile
import zipfile


def extract_geometry_archive(archive, destination):
    archive, root = Path(archive), Path(destination).resolve()
    root.mkdir(parents=True, exist_ok=True)
    seen = {}

    def target(name, directory):
        parts = PurePosixPath(name)
        if parts.is_absolute() or '..' in parts.parts or '\\' in name:
            raise ValueError('Unsafe archive path: ' + name)
        path = root.joinpath(*parts.parts).resolve()
        if not path.is_relative_to(root):
            raise ValueError('Archive path escapes extraction directory')
        # File identities must remain distinct on macOS's default filesystem.
        key = str(parts).casefold()
        if key in seen and (not directory or seen[key] != (str(parts), True)):
            raise ValueError('Duplicate or case-colliding archive path: ' + name)
        seen[key] = (str(parts), directory)
        return path

    if archive.name.endswith('.zip'):
        with zipfile.ZipFile(archive) as handle:
            plan = []
            for member in handle.infolist():
                if stat.S_ISLNK(member.external_attr >> 16):
                    raise ValueError('Archive links are not supported')
                plan.append((member, target(member.filename, member.is_dir())))
            for member, path in plan:
                if member.is_dir():
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with handle.open(member) as source, path.open('wb') as output:
                        shutil.copyfileobj(source, output)
    elif archive.name.endswith(('.tgz', '.tar.gz')):
        with tarfile.open(archive, 'r:gz') as handle:
            plan = []
            for member in handle.getmembers():
                if not (member.isfile() or member.isdir()):
                    raise ValueError('Archive links and special files are not supported')
                plan.append((member, target(member.name, member.isdir())))
            for member, path in plan:
                if member.isdir():
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with handle.extractfile(member) as source, path.open('wb') as output:
                        shutil.copyfileobj(source, output)
    else:
        raise ValueError('Unsupported archive format: ' + str(archive))
